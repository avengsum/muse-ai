"""Durable task execution through Inngest."""

import asyncio
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import inngest
from sqlalchemy import select

from .agent_run_service import execute_agent_run
from .ai_service import generate_reply
from .browser_runtime import create_browser_record, refresh_browser_record
from .conversation_service import get_agent_session
from .database import SessionLocal
from .food_order_runtime import record_food_order_status
from .models import (
    BrowserRun,
    FoodOrder,
    ScheduledTask,
    SwiggyConnection,
    TaskMetadata,
    TaskRun,
    TaskSchedule,
)
from .swiggy_service import (
    SwiggyAuthError,
    SwiggyFoodClient,
    decrypt_secret,
    get_food_delivery_status,
    order_status,
)
from .task_runtime import (
    complete_task_run,
    execute_task_run,
    fail_task_run,
    task_schedule_rule,
)


def inngest_is_configured() -> bool:
    signing_key = (os.getenv("INNGEST_SIGNING_KEY") or "").strip()
    event_key = (os.getenv("INNGEST_EVENT_KEY") or "").strip()

    if not event_key or event_key.lower().startswith("your_inngest") or "<" in event_key:
        return False
    if not signing_key or signing_key.lower().startswith("your_inngest") or "<" in signing_key:
        return False
    return True


inngest_client = inngest.Inngest(
    app_id="muse-ai",
    is_production=inngest_is_configured(),
    logger=logging.getLogger("uvicorn"),
)


def _timestamp(value: datetime | None) -> int:
    if value is None:
        return int(datetime.now(UTC).timestamp() * 1000)

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return int(value.timestamp() * 1000)


def _event_for_task(
    task_id: int,
    *,
    run_now: bool = False,
    task_run_id: int | None = None,
):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)
        schedule = database.get(TaskSchedule, task_id)

        if task is None or schedule is None:
            raise ValueError("Task configuration is missing")

        run_at = None if run_now else schedule.next_run_at
        ts_ms = _timestamp(run_at)
        event_id = (
            f"task-{task_id}-manual-{uuid4()}"
            if run_now
            else f"task-{task_id}-{ts_ms}"
        )
        return inngest.Event(
            name="muse/task.scheduled",
            id=event_id,
            ts=ts_ms,
            data={
                "task_id": task_id,
                "run_now": run_now,
                "task_run_id": task_run_id,
            },
        )


def _run_task_locally(task_id: int, run_now: bool, task_run_id: int | None):
    run_id = _create_task_run(task_id, run_now, task_run_id)
    if run_id is not None:
        threading.Thread(
            target=execute_task_run,
            args=(run_id,),
            daemon=True,
        ).start()


async def send_task_event(
    task_id: int,
    *,
    run_now: bool = False,
    task_run_id: int | None = None,
):
    # Always run manual "Run now" tasks immediately in a local background thread
    # so localhost development never hangs waiting for an Inngest webhook callback.
    if run_now or task_run_id is not None or not inngest_is_configured():
        if run_now or task_run_id is not None:
            _run_task_locally(task_id, run_now, task_run_id)
        if not inngest_is_configured():
            return None

    try:
        return await inngest_client.send(
            _event_for_task(
                task_id,
                run_now=run_now,
                task_run_id=task_run_id,
            )
        )
    except Exception as exc:
        logging.getLogger("uvicorn").warning(
            "Inngest send_task_event failed (falling back to local runner): %s",
            exc,
        )
        return None


def queue_task_event(
    task_id: int,
    *,
    run_now: bool = False,
    task_run_id: int | None = None,
):
    """Send an event from a normal FastAPI sync endpoint."""
    try:
        return asyncio.run(
            send_task_event(
                task_id,
                run_now=run_now,
                task_run_id=task_run_id,
            )
        )
    except Exception as exc:
        logging.getLogger("uvicorn").warning("queue_task_event fallback: %s", exc)
        if run_now or task_run_id is not None:
            _run_task_locally(task_id, run_now, task_run_id)
        return None


async def send_agent_run_event(run_id: str):
    if not inngest_is_configured():
        return None
    try:
        return await inngest_client.send(
            inngest.Event(
                name="muse/agent.run",
                id=f"agent-run-{run_id}",
                data={"run_id": run_id},
            )
        )
    except Exception:
        return None


def queue_agent_run_event(run_id: str):
    if not inngest_is_configured():
        return None
    try:
        return asyncio.run(send_agent_run_event(run_id))
    except Exception:
        return None


async def send_browser_resumed_event(browser_run_id: str):
    if not inngest_is_configured():
        return None
    try:
        return await inngest_client.send(
            inngest.Event(
                name="muse/browser.resumed",
                data={"browser_run_id": browser_run_id},
            )
        )
    except Exception:
        return None


def queue_browser_resumed_event(browser_run_id: str):
    if not inngest_is_configured():
        return None
    try:
        return asyncio.run(send_browser_resumed_event(browser_run_id))
    except Exception:
        return None


async def send_food_order_placed_event(order_id: str):
    if not inngest_is_configured():
        return None
    try:
        return await inngest_client.send(
            inngest.Event(
                name="swiggy/order.placed",
                id=f"swiggy-order-{order_id}",
                data={"orderId": order_id},
            )
        )
    except Exception:
        return None


def queue_food_order_placed_event(order_id: str):
    """Queue durable polling after Swiggy confirms an order placement."""
    if not inngest_is_configured():
        return None
    try:
        return asyncio.run(send_food_order_placed_event(order_id))
    except Exception:
        return None


def _track_food_order_once(order_id: str):
    with SessionLocal() as database:
        order = database.scalar(
            select(FoodOrder).where(FoodOrder.swiggy_order_id == order_id)
        )
        if order is None:
            return {"status": "MISSING"}

        connection = database.get(SwiggyConnection, order.user_id)
        if connection is None:
            return {"status": "AUTH_REQUIRED"}

        try:
            token = decrypt_secret(connection.access_token_encrypted)
            payload = get_food_delivery_status(
                SwiggyFoodClient(token),
                order_id,
            )
        except SwiggyAuthError:
            return {"status": "AUTH_REQUIRED"}

    status = record_food_order_status(order_id, payload)
    return {"status": status or order_status(payload)}


def _create_task_run(
    task_id: int,
    run_now: bool,
    existing_task_run_id: int | None = None,
):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or (not task.active and not run_now):
            return None

        if existing_task_run_id is not None:
            task_run = database.get(TaskRun, existing_task_run_id)
            if task_run and task_run.task_id == task_id and task_run.status == "pending":
                return task_run.id

        active_run = database.scalar(
            select(TaskRun)
            .where(
                TaskRun.task_id == task_id,
                TaskRun.status.in_(["pending", "running"]),
            )
            .limit(1)
        )
        if active_run:
            schedule = database.get(TaskSchedule, task_id)
            scheduled_for = schedule.next_run_at if schedule else None
            if scheduled_for and scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=UTC)
            if schedule and scheduled_for and scheduled_for <= datetime.now(UTC):
                from .schedule_service import calculate_next_run_at

                schedule.next_run_at = calculate_next_run_at(
                    task_schedule_rule(schedule),
                    schedule.timezone,
                    now=datetime.now(UTC),
                    previous_run_at=scheduled_for,
                )
                database.commit()
            return None

        task_run = TaskRun(
            task_id=task.id,
            user_id=task.user_id,
            status="pending",
        )
        database.add(task_run)
        database.commit()
        database.refresh(task_run)
        return task_run.id


def _task_mode(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)
        schedule = database.get(TaskSchedule, task_run.task_id) if task_run else None
        return schedule.execution_mode if schedule else None


def _start_browser_task(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)
        schedule = database.get(TaskSchedule, task_run.task_id) if task_run else None
        task = database.get(ScheduledTask, task_run.task_id) if task_run else None

        if task_run is None or schedule is None or task is None:
            raise RuntimeError("Task configuration is missing")

        task_run.status = "running"
        task_run.started_at = datetime.now(UTC)
        database.commit()
        browser_run = create_browser_record(
            database,
            task.user_id,
            schedule.prompt,
            task_id=task.id,
        )
        task_run.browser_run_id = browser_run.id
        database.commit()
        return browser_run.id


def _refresh_browser_task(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)
        browser_run = database.get(BrowserRun, task_run.browser_run_id) if task_run else None

        if task_run is None or browser_run is None:
            raise RuntimeError("Browser task is missing")

        if browser_run.provider_run_id and browser_run.status.upper() not in {
            "COMPLETED",
            "FAILED",
            "STOPPED",
            "TIMED_OUT",
        }:
            from .browser_service import get_browser_run

            refresh_browser_record(
                database,
                browser_run,
                get_browser_run(browser_run.provider_run_id),
            )

        return browser_run.status.lower()


def _finish_browser_task(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)
        if task_run is None:
            return "missing"

        browser_run = database.get(BrowserRun, task_run.browser_run_id)
        task = database.get(ScheduledTask, task_run.task_id)
        schedule = database.get(TaskSchedule, task_run.task_id)

        if browser_run is None or task is None or schedule is None:
            return "missing"

        if browser_run.status.upper() == "COMPLETED":
            result = browser_run.result or "Browser task completed."
            metadata = database.get(TaskMetadata, task.id)
            if metadata and metadata.delivery != "chat":
                session = get_agent_session(database, task.user_id)
                delivery_result = generate_reply(
                    [
                        {
                            "role": "user",
                            "content": (
                                "APPROVED SCHEDULED TASK:\n"
                                f"Deliver this completed result through {metadata.delivery}.\n\n"
                                f"Original task: {schedule.prompt}\n\nResult: {result}"
                            ),
                        }
                    ],
                    session.session_id if session else None,
                    schedule.timezone,
                )
                result = f"{result}\n\n{delivery_result}"

            complete_task_run(
                database,
                task_run,
                task,
                schedule,
                result,
            )
            return "completed"

        if browser_run.status.upper() == "PAUSED":
            task_run.status = "paused"
            task_run.result = "Browser task paused for your input."
            database.commit()
            return "paused"

        if browser_run.status.upper() in {"FAILED", "STOPPED", "TIMED_OUT"}:
            fail_task_run(
                database,
                task_run_id,
                RuntimeError(browser_run.error or "Browser task failed"),
            )
            return "failed"

        return "running"


def _next_task_event(task_id: int):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)
        schedule = database.get(TaskSchedule, task_id)

        if (
            task is None
            or schedule is None
            or not task.active
            or schedule.schedule_kind == "once"
            or schedule.next_run_at is None
        ):
            return None

        run_at = schedule.next_run_at
        ts_ms = _timestamp(run_at)
        return inngest.Event(
            name="muse/task.scheduled",
            id=f"task-{task_id}-{ts_ms}",
            ts=ts_ms,
            data={"task_id": task_id, "run_now": False},
        )


@inngest_client.create_function(
    fn_id="execute-scheduled-task",
    trigger=inngest.TriggerEvent(event="muse/task.scheduled"),
    retries=3,
)
async def execute_scheduled_task(ctx: inngest.Context):
    task_id = int(ctx.event.data["task_id"])
    run_now = bool(ctx.event.data.get("run_now"))
    existing_task_run_id = ctx.event.data.get("task_run_id")
    task_run_id = await ctx.step.run(
        "create-task-run",
        lambda: _create_task_run(task_id, run_now, existing_task_run_id),
    )

    if task_run_id is None:
        return {"status": "skipped"}

    if await ctx.step.run("read-task-mode", lambda: _task_mode(task_run_id)) == "browser":
        browser_run_id = await ctx.step.run(
            "start-browser-task",
            lambda: _start_browser_task(task_run_id),
        )
        await ctx.step.send_event(
            "poll-browser-task",
            inngest.Event(
                name="muse/browser.poll",
                data={
                    "task_run_id": task_run_id,
                    "browser_run_id": browser_run_id,
                },
            ),
        )
        return {"status": "browser_started", "task_run_id": task_run_id}

    await ctx.step.run(
        "execute-agent-task",
        lambda: execute_task_run(task_run_id),
    )

    if not run_now:
        next_event = _next_task_event(task_id)
        if next_event:
            await ctx.step.send_event("schedule-next-run", next_event)

    return {"status": "completed", "task_run_id": task_run_id}


@inngest_client.create_function(
    fn_id="execute-agent-run",
    trigger=inngest.TriggerEvent(event="muse/agent.run"),
    retries=2,
)
async def execute_agent_run_function(ctx: inngest.Context):
    run_id = str(ctx.event.data["run_id"])
    return await ctx.step.run("execute-agent-run", lambda: execute_agent_run(run_id))


@inngest_client.create_function(
    fn_id="poll-browser-run",
    trigger=inngest.TriggerEvent(event="muse/browser.poll"),
    retries=3,
)
async def poll_browser_run(ctx: inngest.Context):
    task_run_id = int(ctx.event.data["task_run_id"])
    browser_run_id = str(ctx.event.data["browser_run_id"])

    for attempt in range(150):
        status = await ctx.step.run(
            f"refresh-browser-{attempt}",
            lambda: _refresh_browser_task(task_run_id),
        )

        if status in {"completed", "failed", "stopped", "timed_out"}:
            result = await ctx.step.run(
                "finish-browser-task",
                lambda: _finish_browser_task(task_run_id),
            )
            if result == "completed":
                task_id = await ctx.step.run(
                    "read-browser-task-id",
                    lambda: _task_id_for_run(task_run_id),
                )
                next_event = _next_task_event(task_id)
                if next_event:
                    await ctx.step.send_event("schedule-next-browser-run", next_event)
            return {"status": result}

        if status == "paused":
            approval = await ctx.step.wait_for_event(
                "wait-for-browser-resume",
                event="muse/browser.resumed",
                if_exp=(
                    f'event.data.browser_run_id == "{browser_run_id}"'
                ),
                timeout=timedelta(days=7),
            )
            if approval is None:
                return {"status": "approval_timeout"}

        await ctx.step.sleep(f"wait-browser-{attempt}", timedelta(seconds=2))

    return {"status": "timed_out"}


@inngest_client.create_function(
    fn_id="poll-swiggy-food-order",
    trigger=inngest.TriggerEvent(event="swiggy/order.placed"),
    retries=3,
)
async def poll_swiggy_food_order(ctx: inngest.Context):
    order_id_value = str(ctx.event.data["orderId"])

    for attempt in range(2880):
        result = await ctx.step.run(
            f"track-food-order-{attempt}",
            lambda: _track_food_order_once(order_id_value),
        )
        status = str(result.get("status") or "UNKNOWN").upper()

        if status in {"DELIVERED", "CANCELLED", "FAILED", "AUTH_REQUIRED", "MISSING"}:
            return {"status": status, "order_id": order_id_value}

        await ctx.step.sleep(
            f"wait-food-order-{attempt}",
            timedelta(seconds=30),
        )

    return {"status": "TIMED_OUT", "order_id": order_id_value}


def _task_id_for_run(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)
        return task_run.task_id if task_run else None


inngest_functions = [
    execute_scheduled_task,
    execute_agent_run_function,
    poll_browser_run,
    poll_swiggy_food_order,
]