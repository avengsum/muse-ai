from urllib.parse import urlparse
import os
from fastapi import HTTPException


def validate_callback_url(callback_url: str | None):
    if callback_url is None:
        return None
    parsed = urlparse(callback_url)
    if parsed.scheme in {"museai", "exp"} and callback_url.startswith(("museai://", "exp://")):
        return callback_url
    allowed_hosts = {"localhost", "127.0.0.1"}
    prod_web_host = (os.getenv("FRONTEND_WEB_HOST") or "").strip().lower()
    if prod_web_host:
        allowed_hosts.add(prod_web_host)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in allowed_hosts:
        raise HTTPException(status_code=400, detail="Invalid callback URL")
    return callback_url
