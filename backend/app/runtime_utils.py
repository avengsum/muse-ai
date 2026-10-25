import json
import logging
from datetime import UTC, datetime
from uuid import uuid4


logger = logging.getLogger("muse_ai")


def log_internal_error(event: str, **context):
    error_id = uuid4().hex
    logger.exception(
        "%s error_id=%s context=%s",
        event,
        error_id,
        json.dumps(context, default=str),
    )
    return error_id


def public_error(message: str, error_id: str):
    return f"{message} Reference: {error_id}"


def as_utc(value: datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
