import logging

import httpx
from sqlalchemy import select

from .models import Notification, PushToken, UserSettings


logger = logging.getLogger("muse_ai")


def send_expo_push(tokens: list[str], title: str, body: str, data: dict):
    if not tokens:
        return
    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "data": data,
            "sound": "default",
            "channelId": "orders",
        }
        for token in tokens
    ]
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post("https://exp.host/--/api/v2/push/send", json=messages)
            response.raise_for_status()
    except Exception:
        logger.exception("Expo push delivery failed")


def add_notification(database, user_id: str, title: str, body: str, kind: str):
    settings = database.get(UserSettings, user_id)
    if settings and not settings.notifications_enabled:
        return
    database.add(
        Notification(
            user_id=user_id,
            title=title[:160],
            body=body[:1000],
            kind=kind,
        )
    )


def send_user_push(database, user_id: str, title: str, body: str, data: dict):
    settings = database.get(UserSettings, user_id)
    if settings and not settings.notifications_enabled:
        return
    tokens = database.scalars(select(PushToken.token).where(PushToken.user_id == user_id)).all()
    send_expo_push(list(tokens), title, body, data)
