import json
import logging
from collections.abc import Iterable

from sqlalchemy import func, select, update

from .database import SessionLocal
from .model_config import create_llm_client, get_llm_model_name, get_llm_provider
from .models import UserMemory


logger = logging.getLogger("muse_ai")


MEMORY_EXTRACTOR_PROMPT = """
You are the long-term memory extractor for personal assistant Cooper.
Examine the recent conversation and extract only durable facts, preferences,
or instructions explicitly stated by the USER.

Rules:
1. Ignore greetings, questions, casual chat, one-off actions, and facts only
   stated by the assistant.
2. Extract lasting attributes such as dietary preferences, location, favorite
   cuisines, family or pet names, work details, and recurring instructions.
3. If the user changes an existing fact, use action "update" and provide a
   short keyword from the old fact in "supersedes".
4. Never infer sensitive facts or preferences that the user did not state.
5. If no durable fact was mentioned, return has_memories=false and memories=[].

Return only valid JSON matching this shape:
{"has_memories": false, "memories": []}
""".strip()


MEMORY_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "user_memory_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "has_memories": {"type": "boolean"},
                "memories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": [
                                    "dietary",
                                    "location",
                                    "preference",
                                    "work",
                                    "personal",
                                ],
                            },
                            "fact": {"type": "string"},
                            "action": {"type": "string", "enum": ["add", "update"]},
                            "supersedes": {
                                "anyOf": [{"type": "string"}, {"type": "null"}]
                            },
                            "importance": {
                                "type": "integer",
                            },
                        },
                        "required": [
                            "category",
                            "fact",
                            "action",
                            "supersedes",
                            "importance",
                        ],
                    },
                },
            },
            "required": ["has_memories", "memories"],
        },
    },
}


def get_user_memory_context(database, user_id: str, limit: int = 25) -> str:
    memories = database.scalars(
        select(UserMemory)
        .where(UserMemory.user_id == user_id, UserMemory.is_active.is_(True))
        .order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
        .limit(limit)
    ).all()

    if not memories:
        return ""

    return "\n".join(
        ["# User Profile & Known Preferences:"]
        + [f"- [{memory.category.upper()}] {memory.fact}" for memory in memories]
    )


def _parse_extractor_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _memory_items(data: dict) -> Iterable[dict]:
    memories = data.get("memories")
    if not data.get("has_memories") or not isinstance(memories, list):
        return []
    return (item for item in memories if isinstance(item, dict))


def _memory_response_format() -> dict:
    if get_llm_provider() in {"deepseek", "groq"}:
        return {"type": "json_object"}
    return MEMORY_RESPONSE_FORMAT


async def extract_and_persist_memories(
    user_id: str,
    messages: list[dict[str, str]],
):
    conversation_snippet = "\n".join(
        f"{message.get('role', 'user').upper()}: {message.get('content', '')}"
        for message in messages[-4:]
        if message.get("content")
    )
    if not conversation_snippet.strip():
        return

    client = None
    try:
        client = create_llm_client()
        response = await client.chat.completions.create(
            model=get_llm_model_name(memory=True),
            messages=[
                {"role": "system", "content": MEMORY_EXTRACTOR_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract memories from:\n{conversation_snippet}",
                },
            ],
            response_format=_memory_response_format(),
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        items = _memory_items(_parse_extractor_response(content))

        with SessionLocal() as database:
            saved_count = 0
            for item in items:
                fact = str(item.get("fact") or "").strip()
                if not fact:
                    continue

                supersedes = str(item.get("supersedes") or "").strip()
                if item.get("action") == "update" and supersedes:
                    database.execute(
                        update(UserMemory)
                        .where(
                            UserMemory.user_id == user_id,
                            UserMemory.is_active.is_(True),
                            UserMemory.fact.ilike(f"%{supersedes}%"),
                        )
                        .values(is_active=False)
                    )

                duplicate = database.scalar(
                    select(UserMemory.id).where(
                        UserMemory.user_id == user_id,
                        UserMemory.is_active.is_(True),
                        func.lower(UserMemory.fact) == fact.lower(),
                    )
                )
                if duplicate is not None:
                    continue

                try:
                    importance = max(1, min(5, int(item.get("importance", 3))))
                except (TypeError, ValueError):
                    importance = 3

                database.add(
                    UserMemory(
                        user_id=user_id,
                        category=str(item.get("category") or "preference")[:50],
                        fact=fact,
                        importance=importance,
                        is_active=True,
                    )
                )
                saved_count += 1

            database.commit()
            if saved_count:
                logger.info("Saved %d memory facts for user %s", saved_count, user_id)
    except Exception as error:
        logger.warning("Background memory extraction failed: %s", error)
    finally:
        if client is not None:
            await client.close()
