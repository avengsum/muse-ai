import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update

from .ai_service import stream_reply
from .browser_runtime import run_browser_for_agent
from .browser_service import browserbase_is_configured
from .conversation_service import compact_conversation_if_needed, prepare_chat_context
from .database import SessionLocal
from .memory_service import extract_and_persist_memories, get_user_memory_context
from .models import (
    AgentRun,
    AgentRunEvent,
    BrowserRun,
    Conversation,
    Message,
    MessageArtifact,
    UserSettings,
)
from .runtime_utils import as_utc, log_internal_error, public_error
from .schemas import AgentRunResponse
from .swiggy_runtime import swiggy_connection_token


memory_tasks: set[asyncio.Task] = set()
agent_tasks: dict[str, asyncio.Task] = {}


def schedule_memory_extraction(user_id: str, messages: list[dict[str, str]]):
    task = asyncio.create_task(extract_and_persist_memories(user_id, messages))
    memory_tasks.add(task)
    task.add_done_callback(memory_tasks.discard)

def schedule_memory_extraction(user_id: str, messages: list[dict[str, str]]):
    task = asyncio.create_task(extract_and_persist_memories(user_id, messages))
    memory_tasks.add(task)
    task.add_done_callback(memory_tasks.discard)


def schedule_conversation_compaction(conversation_id: str):
    task = asyncio.create_task(compact_conversation_if_needed(conversation_id))
    memory_tasks.add(task)
    task.add_done_callback(memory_tasks.discard)


def create_agent_run_record(
    database,
    *,
    run_id: str,
    user_id: str,
    conversation_id: str,
    prompt: str,
    timezone: str,
    callback_url: str | None,
    dispatch_mode: str,
):
    run = AgentRun(
        id=run_id,
        user_id=user_id,
        conversation_id=conversation_id,
        prompt=prompt,
        timezone=timezone or "UTC",
        callback_url=callback_url,
        dispatch_mode=dispatch_mode,
        status="queued",
    )
    database.add(run)
    database.commit()
    database.refresh(run)
    return run


def append_agent_run_event(database, run_id: str, kind: str, payload: dict[str, Any]):
    event = AgentRunEvent(
        run_id=run_id,
        sequence=0,
        kind=kind[:40],
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    database.add(event)
    database.flush()
    event.sequence = event.id
    database.commit()
    return event


def owned_agent_run(database, run_id: str, user_id: str):
    run = database.get(AgentRun, run_id)
    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def agent_run_payload(run: AgentRun):
    return AgentRunResponse(
        id=run.id,
        status=run.status,
        conversation_id=run.conversation_id,
        result_message_id=run.result_message_id,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def execute_agent_run(run_id: str):
    with SessionLocal() as database:
        run = database.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if run is None:
            return {"status": "missing"}
        if run.status in {"completed", "cancelled"}:
            return {"status": run.status}
        if (
            run.status == "running"
            and run.started_at
            and datetime.now(UTC) - as_utc(run.started_at) < timedelta(minutes=10)
        ):
            return {"status": "already_running"}
        run.status = "running"
        run.started_at = datetime.now(UTC)
        settings = database.get(UserSettings, run.user_id)
        agent_label = (settings.agent_name if settings and settings.agent_name else "Cooper").strip()
        database.commit()
        append_agent_run_event(
            database,
            run_id,
            "status",
            {"message": f"{agent_label} is working..."},
        )
        conversation_id = run.conversation_id
        user_id = run.user_id
        timezone = run.timezone
        callback_url = run.callback_url
        run_prompt = (run.prompt or "").strip()

    try:
        packed_ctx = await asyncio.to_thread(
            prepare_chat_context, conversation_id, user_id
        )
        if len(packed_ctx) == 4:
            history, composio_session_id, active_agent, agent_name = packed_ctx
        else:
            history, composio_session_id = packed_ctx
            active_agent = "cooper"
            agent_name = "Cooper"

        # CRITICAL FIX: Agar run kisi silent [UI Event: ...] se trigger hua hai,
        # toh woh Message table mein save nahi hua tha. Isliye hume use history
        # mein append karna hoga taaki LLM ko event dikh sake!
        if run_prompt and (
            not history
            or history[-1].get("role") != "user"
            or history[-1].get("content") != run_prompt
        ):
            history.append({"role": "user", "content": run_prompt})

        with SessionLocal() as database:
            memory_context = get_user_memory_context(database, user_id)
            swiggy_access_token = swiggy_connection_token(database, user_id)

        browser_handler = lambda task, emit, cancel: run_browser_for_agent(
            user_id, conversation_id, task, emit, cancel
        )

        text_parts: list[str] = []
        pending_deltas: list[str] = []
        last_delta_flush = time.monotonic()
        final_output = None
        action_event = None
        resulting_agent = active_agent

        def flush_deltas():
            nonlocal last_delta_flush
            if not pending_deltas:
                return
            text = "".join(pending_deltas)
            pending_deltas.clear()
            with SessionLocal() as database:
                append_agent_run_event(database, run_id, "delta", {"text": text})
            last_delta_flush = time.monotonic()

        async for item in stream_reply(
            history,
            composio_session_id,
            timezone,
            callback_url,
            browser_handler,
            swiggy_access_token,
            callback_url,
            active_agent,
            memory_context,
            agent_name,
        ):
            if isinstance(item, str):
                text_parts.append(item)
                pending_deltas.append(item)
                if len("".join(pending_deltas)) >= 256 or time.monotonic() - last_delta_flush >= 0.25:
                    flush_deltas()
                continue

            flush_deltas()
            event_type = item.get("type") if isinstance(item, dict) else None
            if event_type == "agent_switched" and item.get("agent"):
                resulting_agent = str(item["agent"])
            elif event_type == "agent_final":
                final_output = item.get("output") or ""
                if item.get("active_agent"):
                    resulting_agent = str(item["active_agent"])
            elif event_type != "heartbeat" and item.get("action"):
                action_event = item
                if item.get("_active_agent"):
                    resulting_agent = str(item["_active_agent"])
            with SessionLocal() as database:
                append_agent_run_event(database, run_id, event_type or "event", item)

        flush_deltas()
        streamed_text = "".join(text_parts).strip()
        reply_text = (final_output if final_output is not None else streamed_text).strip()
        artifact = (action_event or {}).get("artifact") or {}
        if action_event:
            action_msg = (action_event.get("message") or action_event.get("output") or "").strip()
            if not reply_text:
                reply_text = action_msg
            elif action_msg and action_msg not in reply_text:
                reply_text = f"{reply_text}\n\n{action_msg}"

        with SessionLocal() as database:
            assistant_message = Message(
                conversation_id=conversation_id,
                sender="agent",
                text=reply_text.strip() or f"{agent_name} completed the step.",
            )
            database.add(assistant_message)
            database.flush()
            message_id = assistant_message.id

            database.execute(
                update(BrowserRun)
                .where(
                    BrowserRun.conversation_id == conversation_id,
                    BrowserRun.message_id.is_(None),
                )
                .values(message_id=message_id)
            )

            if artifact.get("kind"):
                database.add(
                    MessageArtifact(
                        message_id=message_id,
                        kind=artifact["kind"],
                        data_json=json.dumps(artifact.get("data"), ensure_ascii=False, default=str),
                        status="pending",
                    )
                )

            conversation = database.get(Conversation, conversation_id)
            if conversation and resulting_agent:
                conversation.active_agent = resulting_agent[:30]
                conversation.updated_at = datetime.now(UTC)

            run = database.get(AgentRun, run_id)
            if run:
                run.status = "completed"
                run.result_message_id = message_id
                run.finished_at = datetime.now(UTC)
            database.commit()
            append_agent_run_event(
                database,
                run_id,
                "done",
                {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "output": reply_text,
                    "action": action_event,
                    "active_agent": resulting_agent,
                },
            )
        schedule_memory_extraction(
            user_id,
            history + [{"role": "assistant", "content": reply_text}],
        )
        schedule_conversation_compaction(conversation_id)
        return {"status": "completed", "message_id": message_id}
    except Exception:
        error_id = log_internal_error("Agent run failed", run_id=run_id, user_id=user_id)
        public_message = public_error("The AI service could not complete the request.", error_id)
        with SessionLocal() as database:
            run = database.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.error = public_message
                run.finished_at = datetime.now(UTC)
                database.commit()
                append_agent_run_event(
                    database,
                    run_id,
                    "error",
                    {"message": public_message, "error_id": error_id},
                )
        return {"status": "failed", "error_id": error_id}

def start_background_agent_run(run_id: str):
    if run_id not in agent_tasks:
        task = asyncio.create_task(execute_agent_run(run_id))
        agent_tasks[run_id] = task
        task.add_done_callback(lambda _done: agent_tasks.pop(run_id, None))


def durable_chat_stream(*, run_id: str, conversation_id: str, user_id: str):
    async def event_stream():
        with SessionLocal() as database:
            run_record = owned_agent_run(database, run_id, user_id)
            dispatch_mode = run_record.dispatch_mode

        if dispatch_mode == "direct":
            start_background_agent_run(run_id)

        next_sequence = 0
        started_waiting_at = time.monotonic()
        yield json.dumps({"type": "run", "run_id": run_id, "conversation_id": conversation_id}) + "\n"

        while True:
            with SessionLocal() as database:
                events = database.scalars(
                    select(AgentRunEvent)
                    .where(
                        AgentRunEvent.run_id == run_id,
                        AgentRunEvent.sequence > next_sequence,
                    )
                    .order_by(AgentRunEvent.sequence)
                ).all()
                run = owned_agent_run(database, run_id, user_id)

            # Fallback: if Inngest did not pick up the queued run within 1.5s
            # (e.g., running on localhost without an Inngest tunnel/dev server),
            # start it directly in the local background worker.
            if (
                run.status == "queued"
                and run_id not in agent_tasks
                and time.monotonic() - started_waiting_at >= 1.5
            ):
                start_background_agent_run(run_id)

            for ev in events:
                next_sequence = ev.sequence
                payload = json.loads(ev.payload_json or "{}")
                if ev.kind == "delta":
                    yield json.dumps({"type": "delta", "text": payload.get("text", "")}) + "\n"
                else:
                    yield json.dumps({"type": ev.kind, **payload, "run_id": run_id}) + "\n"

            if run.status in {"completed", "failed", "cancelled"} and not events:
                break

            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )