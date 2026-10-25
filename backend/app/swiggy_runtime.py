from datetime import UTC, datetime, timedelta

from .models import SwiggyConnection
from .runtime_utils import as_utc
from .swiggy_service import decrypt_secret


def swiggy_connection_token(database, user_id: str) -> str | None:
    connection = database.get(SwiggyConnection, user_id)
    if connection is None:
        return None
    expires_at = as_utc(connection.expires_at)
    if expires_at <= datetime.now(UTC) + timedelta(seconds=60):
        return None
    return decrypt_secret(connection.access_token_encrypted)


def swiggy_status(database, user_id: str) -> dict:
    connection = database.get(SwiggyConnection, user_id)
    if connection is None:
        return {"connected": False, "expires_at": None}
    expires_at = as_utc(connection.expires_at)
    return {
        "connected": expires_at > datetime.now(UTC) + timedelta(seconds=60),
        "expires_at": expires_at.isoformat(),
        "scope": connection.scope,
    }
