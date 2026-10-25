import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException

from .models import UserSettings

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

# ==============================================================================
# INSTANT KILL SWITCH: Set to False (or MUSE_ENFORCE_QUESTION_LIMIT=false in .env)
# to disable the 3-question limit immediately.
# ==============================================================================
ENFORCE_QUESTION_LIMIT: bool = True
MAX_FREE_QUESTIONS: int = 3


def is_limit_enabled() -> bool:
    load_dotenv(BACKEND_DIR / ".env", override=True)
    load_dotenv(PROJECT_DIR / ".env", override=True)
    env_val = os.getenv("MUSE_ENFORCE_QUESTION_LIMIT")
    if env_val is not None and env_val.strip() != "":
        return env_val.strip().lower() in {"true", "1", "yes", "on"}
    return ENFORCE_QUESTION_LIMIT


def get_max_questions() -> int:
    env_max = os.getenv("MUSE_MAX_FREE_QUESTIONS")
    if env_max and env_max.strip().isdigit():
        return max(1, int(env_max.strip()))
    return MAX_FREE_QUESTIONS


def is_billable_user_question(message_text: str) -> bool:
    """
    Do not charge a question credit for internal UI approval/cancel reactions
    or browser resume events.
    """
    clean = (message_text or "").strip()
    if not clean:
        return False
    if clean.startswith("[UI Event:") or clean.startswith("[System:"):
        return False
    return True


def get_user_quota_status(database, user_id: str) -> dict:
    settings = database.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id, questions_used=0)
        database.add(settings)
        database.commit()
        database.refresh(settings)

    enabled = is_limit_enabled()
    limit = get_max_questions()
    used = max(0, int(getattr(settings, "questions_used", 0) or 0))

    if not enabled:
        return {
            "limit_enabled": False,
            "questions_used": used,
            "questions_limit": limit,
            "questions_remaining": 999,
            "percent_used": 0,
        }

    remaining = max(0, limit - used)
    percent = min(100, round((used / limit) * 100)) if limit > 0 else 100

    return {
        "limit_enabled": True,
        "questions_used": min(used, limit),
        "questions_limit": limit,
        "questions_remaining": remaining,
        "percent_used": percent,
    }


def check_and_consume_question_quota(
    database,
    user_id: str,
    message_text: str,
) -> bool:
    """
    Checks if the user has remaining questions and increments `questions_used`.
    Returns True if a question credit was consumed, False if exempt/disabled.
    Raises HTTP 429 if the 3-question limit is reached.
    """
    if not is_billable_user_question(message_text):
        return False

    if not is_limit_enabled():
        return False

    settings = database.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id, questions_used=0)
        database.add(settings)
        database.flush()

    limit = get_max_questions()
    used = max(0, int(getattr(settings, "questions_used", 0) or 0))

    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You have reached your Free Plan limit of {limit} questions "
                f"({limit}/{limit} used)."
            ),
        )

    settings.questions_used = used + 1
    database.commit()
    return True


def refund_question_quota(database, user_id: str):
    """Refunds 1 question if the AI run crashes with an internal error."""
    if not is_limit_enabled():
        return
    settings = database.get(UserSettings, user_id)
    if settings and (settings.questions_used or 0) > 0:
        settings.questions_used -= 1
        database.commit()