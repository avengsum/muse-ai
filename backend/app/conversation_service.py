import asyncio
import logging
import os
from datetime import UTC, datetime
from .tool_registry import TOOLS
from fastapi import HTTPException
from sqlalchemy import select

from .composio_service import (
    composio_is_configured,
    create_composio_session,
    restore_composio_session,
)
from .database import SessionLocal
from .model_config import create_llm_client, get_llm_model_name
from .models import (
    AgentProfile,
    BrowserRun,
    Conversation,
    Message,
    MessageArtifact,
    UserSettings,
)

logger = logging.getLogger("muse_ai")

COMPACTION_TRIGGER_TOKENS = int(os.getenv("COMPACTION_TRIGGER_TOKENS", "60000"))
RECENT_VERBATIM_TOKENS = int(os.getenv("RECENT_VERBATIM_TOKENS", "16000"))
HARD_CONTEXT_TOKEN_LIMIT = int(os.getenv("HARD_CONTEXT_TOKEN_LIMIT", "90000"))
MAX_SUMMARY_TOKENS = int(os.getenv("MAX_SUMMARY_TOKENS", "1200"))

_active_compactions: set[str] = set()

COMPACTION_SYSTEM_PROMPT = f"""
You are the Context Compaction Engine for Muse AI.
Update the running conversation summary by merging the EXISTING SUMMARY with the NEWLY EVICTED TURNS.

You MUST structure the output using these exact 4 concise sections:
1. **User Goal & Active Constraints**: Core objective, preferences, budgets, or locations mentioned.
2. **Completed Actions & Key Data**: Confirmed tool outputs, Swiggy order/address IDs, URLs, prices, or sandbox results.
3. **Open Decisions & Commitments**: Anything pending user approval, cancelled cards, or unfinished steps.
4. **Key Entities**: Names, contacts, files, or repositories referenced.

Strict Rules:
- Drop resolved chit-chat, greetings, and raw verbose logs.
- Never invent facts. Preserve exact IDs, numbers, and amounts.
- Keep the entire summary under {MAX_SUMMARY_TOKENS} tokens (~{MAX_SUMMARY_TOKENS * 4} characters).
""".strip()


def estimate_tokens(text: str | None) -> int:
    """Fast production heuristic: 4 characters ≈ 1 token (+4 tokens framing overhead)."""
    if not text:
        return 0
    return max(1, len(text) // 4) + 4


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


def ensure_conversation_access(database, conversation_id: str, user_id: str):
    conversation = database.get(Conversation, conversation_id)
    if conversation and conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def update_conversation(
    database,
    conversation_id: str,
    user_id: str,
    first_message: str,
    active_agent: str | None = None,
):
    conversation = ensure_conversation_access(database, conversation_id, user_id)
    title = first_message.strip()[:60] or "New chat"
    if conversation is None:
        conversation = Conversation(id=conversation_id, user_id=user_id, title=title)
        database.add(conversation)
    elif conversation.title == "New chat":
        conversation.title = title
    if active_agent:
        conversation.active_agent = active_agent
    conversation.updated_at = datetime.now(UTC)
    return conversation


def get_agent_session(database, user_id: str):
    if not composio_is_configured():
        return None

    version_prefix = f"v{len(TOOLS)}:"
    profile = database.get(AgentProfile, user_id)

    if profile and profile.composio_session_id:
        stored_value = profile.composio_session_id
        if stored_value.startswith(version_prefix):
            raw_session_id = stored_value[len(version_prefix) :]
            try:
                return restore_composio_session(raw_session_id)
            except Exception:
                profile.composio_session_id = None
        else:
            # Toolkit list changed; upgrade session (user_id connections stay intact)
            profile.composio_session_id = None

    session = create_composio_session(user_id)
    versioned_id = f"{version_prefix}{session.session_id}"

    if profile is None:
        database.add(
            AgentProfile(user_id=user_id, composio_session_id=versioned_id)
        )
    else:
        profile.composio_session_id = versioned_id
    database.commit()
    return session

def _enrich_messages(
    database, messages: list[Message]
) -> list[tuple[int, dict[str, str], int]]:
    """
    Returns a list of (message_id, {"role": ..., "content": ...}, token_count)
    including attached BrowserRun and MessageArtifact payloads.
    """
    if not messages:
        return []

    message_ids = [m.id for m in messages]
    artifacts = database.scalars(
        select(MessageArtifact).where(MessageArtifact.message_id.in_(message_ids))
    ).all()
    artifact_by_msg = {a.message_id: a for a in artifacts}

    browser_runs = database.scalars(
        select(BrowserRun).where(BrowserRun.message_id.in_(message_ids))
    ).all()
    browser_by_msg = {b.message_id: b for b in browser_runs if b.message_id}

    enriched: list[tuple[int, dict[str, str], int]] = []
    for message in messages:
        role = "assistant" if message.sender == "agent" else "user"
        content = message.text or ""

        if role == "assistant":
            extra_context = []
            if message.id in browser_by_msg:
                b_run = browser_by_msg[message.id]
                if b_run.result:
                    extra_context.append(
                        f"[Browser Run ({b_run.status}) Result: {b_run.result[:1500]}]"
                    )
            if message.id in artifact_by_msg:
                art = artifact_by_msg[message.id]
                extra_context.append(
                    f"[Attached Artifact ({art.kind}, status={art.status}): {art.data_json[:1200]}]"
                )
            if extra_context:
                content = f"{content}\n\n" + "\n".join(extra_context)

        clean_content = content.strip()
        msg_dict = {"role": role, "content": clean_content}
        enriched.append((message.id, msg_dict, estimate_tokens(clean_content)))

    return enriched


def _select_tail_within_token_budget(
    enriched_items: list[tuple[int, dict[str, str], int]],
    token_budget: int,
    min_messages: int = 2,
) -> tuple[list[tuple[int, dict[str, str], int]], list[tuple[int, dict[str, str], int]]]:
    """
    Splits `enriched_items` into (head_to_evict, tail_to_keep_verbatim) based on `token_budget`.
    Guarantees:
    - At least `min_messages` most recent messages are kept.
    - The verbatim tail starts cleanly on a 'user' message so User/Assistant pairs are never orphaned.
    """
    if len(enriched_items) <= min_messages:
        return [], enriched_items

    accumulated_tokens = 0
    split_index = len(enriched_items)

    for idx in range(len(enriched_items) - 1, -1, -1):
        msg_tokens = enriched_items[idx][2]
        messages_kept = len(enriched_items) - idx
        if accumulated_tokens + msg_tokens > token_budget and messages_kept >= min_messages:
            break
        accumulated_tokens += msg_tokens
        split_index = idx

    # Snap split_index forward to a 'user' turn so the verbatim window doesn't start with an orphaned 'assistant' turn
    while (
        split_index < len(enriched_items) - min_messages
        and enriched_items[split_index][1]["role"] != "user"
    ):
        split_index += 1

    return enriched_items[:split_index], enriched_items[split_index:]


def build_history(database, conversation_id: str) -> list[dict[str, str]]:
    conversation = database.get(Conversation, conversation_id)
    watermark_id = (
        conversation.summarized_until_message_id if conversation else None
    )
    existing_summary = (
        (conversation.summary or "").strip() if conversation else ""
    )

    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if watermark_id is not None:
        stmt = stmt.where(Message.id > watermark_id)
    stmt = stmt.order_by(Message.created_at, Message.id)

    unsummarized_rows = list(database.scalars(stmt).all())
    enriched = _enrich_messages(database, unsummarized_rows)

    history: list[dict[str, str]] = []
    summary_tokens = 0

    if existing_summary:
        summary_block = (
            "[CONVERSATION SUMMARY OF EARLIER TURNS]\n"
            f"{existing_summary}"
        )
        ack_block = "Understood. I have the earlier context and constraints from this conversation."
        summary_tokens = estimate_tokens(summary_block) + estimate_tokens(ack_block)
        history.append({"role": "user", "content": summary_block})
        history.append({"role": "assistant", "content": ack_block})

    # Enforce hard token ceiling on verbatim messages even if background compaction hasn't run yet
    remaining_budget = max(1200, HARD_CONTEXT_TOKEN_LIMIT - summary_tokens)
    _, verbatim_tail = _select_tail_within_token_budget(
        enriched,
        token_budget=remaining_budget,
        min_messages=2,
    )

    history.extend(item[1] for item in verbatim_tail)
    return history


def _prepare_token_compaction_batch(conversation_id: str) -> dict | None:
    with SessionLocal() as database:
        conversation = database.get(Conversation, conversation_id)
        if conversation is None:
            return None

        watermark_id = conversation.summarized_until_message_id
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if watermark_id is not None:
            stmt = stmt.where(Message.id > watermark_id)
        stmt = stmt.order_by(Message.created_at, Message.id)

        unsummarized_rows = list(database.scalars(stmt).all())
        if len(unsummarized_rows) <= 2:
            return None

        enriched = _enrich_messages(database, unsummarized_rows)
        total_unsummarized_tokens = sum(item[2] for item in enriched)

        # Only compact when unsummarized tokens exceed COMPACTION_TRIGGER_TOKENS
        if total_unsummarized_tokens < COMPACTION_TRIGGER_TOKENS:
            return None

        to_compact, _ = _select_tail_within_token_budget(
            enriched,
            token_budget=RECENT_VERBATIM_TOKENS,
            min_messages=2,
        )
        if not to_compact:
            return None

        new_watermark_id = to_compact[-1][0]
        compacted_tokens = sum(item[2] for item in to_compact)

        return {
            "existing_summary": (conversation.summary or "").strip(),
            "turns": [item[1] for item in to_compact],
            "new_watermark_id": new_watermark_id,
            "compacted_tokens": compacted_tokens,
            "total_unsummarized_tokens": total_unsummarized_tokens,
        }


def _persist_compacted_summary(
    conversation_id: str,
    new_summary: str,
    new_watermark_id: int,
):
    with SessionLocal() as database:
        conversation = database.get(Conversation, conversation_id)
        if conversation is None:
            return
        current_wm = conversation.summarized_until_message_id or 0
        if new_watermark_id > current_wm:
            # Enforce hard character cap matching MAX_SUMMARY_TOKENS (4 chars = 1 token)
            max_chars = MAX_SUMMARY_TOKENS * 4
            conversation.summary = new_summary.strip()[:max_chars]
            conversation.summarized_until_message_id = new_watermark_id
            database.commit()


async def compact_conversation_if_needed(conversation_id: str):
    if not conversation_id or conversation_id in _active_compactions:
        return

    _active_compactions.add(conversation_id)
    client = None
    try:
        batch = await asyncio.to_thread(
            _prepare_token_compaction_batch, conversation_id
        )
        if batch is None:
            return

        formatted_turns = []
        for turn in batch["turns"]:
            role = turn.get("role", "user").upper()
            # Cap single gigantic tool dumps inside the compactor input to 600 tokens (2400 chars)
            text = (turn.get("content") or "").strip()[:2400]
            if text:
                formatted_turns.append(f"{role}: {text}")

        if not formatted_turns:
            return

        transcript_text = "\n\n".join(formatted_turns)
        user_prompt = (
            f"EXISTING SUMMARY:\n{batch['existing_summary'] or 'None'}\n\n"
            f"NEWLY EVICTED TURNS ({batch['compacted_tokens']} estimated tokens):\n"
            f"{transcript_text}"
        )

        client = create_llm_client()
        response = await client.chat.completions.create(
            model=get_llm_model_name(memory=True),
            messages=[
                {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=MAX_SUMMARY_TOKENS,
        )
        new_summary = (response.choices[0].message.content or "").strip()
        if not new_summary:
            return

        await asyncio.to_thread(
            _persist_compacted_summary,
            conversation_id,
            new_summary,
            batch["new_watermark_id"],
        )
        logger.info(
            "Token compaction complete for %s: compressed %d/%d tokens into %d tokens (watermark=%s)",
            conversation_id,
            batch["compacted_tokens"],
            batch["total_unsummarized_tokens"],
            estimate_tokens(new_summary),
            batch["new_watermark_id"],
        )
    except Exception as error:
        logger.warning(
            "Token compaction failed for %s: %s", conversation_id, error
        )
    finally:
        _active_compactions.discard(conversation_id)
        if client is not None:
            await client.close()


def prepare_chat_context(conversation_id: str, user_id: str):
    with SessionLocal() as database:
        history = build_history(database, conversation_id)
        session = get_agent_session(database, user_id)
        conversation = database.get(Conversation, conversation_id)
        settings = database.get(UserSettings, user_id)
        active_agent = (
            (conversation.active_agent if conversation else None) or "cooper"
        )
        agent_name = (
            settings.agent_name if settings and settings.agent_name else "Cooper"
        ).strip()
        return (
            history,
            session.session_id if session else None,
            active_agent,
            agent_name,
        )