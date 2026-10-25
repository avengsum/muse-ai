"""Swiggy Food MCP integration.

The app talks to Swiggy from the backend only.  The mobile client receives an
opaque OAuth completion URL and structured, display-safe cart data; it never
receives a Swiggy access token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import httpx
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")

SWIGGY_BASE_URL = os.getenv("SWIGGY_BASE_URL", "https://mcp.swiggy.com").rstrip("/")
SWIGGY_FOOD_URL = f"{SWIGGY_BASE_URL}/food"
SWIGGY_OAUTH_REDIRECT_URI = os.getenv(
    "SWIGGY_OAUTH_REDIRECT_URI",
    "http://localhost:8000/api/swiggy/oauth/callback",
)
SWIGGY_CART_CAP = Decimal("1000")
SWIGGY_OAUTH_STATE_TTL = timedelta(minutes=15)


class SwiggyError(RuntimeError):
    """An error returned by the Swiggy OAuth or MCP endpoint."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SwiggyAuthError(SwiggyError):
    """The user must authorize Swiggy again."""


def swiggy_is_configured() -> bool:
    return bool(os.getenv("SWIGGY_TOKEN_ENCRYPTION_KEY"))


def _fernet() -> Fernet:
    key = os.getenv("SWIGGY_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise SwiggyError("SWIGGY_TOKEN_ENCRYPTION_KEY is missing", 503)

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise SwiggyError("SWIGGY_TOKEN_ENCRYPTION_KEY is invalid", 500) from error


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as error:
        raise SwiggyError("Stored Swiggy credentials could not be decrypted", 500) from error


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def append_query(url: str, **values: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(query)))


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _raise_for_response(response: httpx.Response, operation: str):
    if response.status_code == 401:
        raise SwiggyAuthError("Swiggy authorization expired", 401)
    if response.status_code >= 400:
        detail = _json_or_text(response)
        if isinstance(detail, dict):
            detail = detail.get("error_description") or detail.get("detail") or detail.get("error")
        raise SwiggyError(f"Swiggy {operation} failed: {detail}", response.status_code)


def register_dynamic_client() -> str:
    configured_client_id = os.getenv("SWIGGY_CLIENT_ID", "").strip()
    if configured_client_id:
        return configured_client_id

    payload = {
        "client_name": "Muse AI Food Specialist",
        "redirect_uris": [SWIGGY_OAUTH_REDIRECT_URI],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{SWIGGY_BASE_URL}/auth/register", json=payload)
    _raise_for_response(response, "client registration")
    data = _json_or_text(response)
    client_id = data.get("client_id") if isinstance(data, dict) else None

    if not client_id:
        raise SwiggyError("Swiggy did not return a client identifier")

    return str(client_id)


def build_authorization_url(state: str, code_challenge: str, client_id: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": SWIGGY_OAUTH_REDIRECT_URI,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp:tools",
        }
    )
    return f"{SWIGGY_BASE_URL}/auth/authorize?{query}"


def exchange_authorization_code(code: str, verifier: str, _client_id: str) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": SWIGGY_OAUTH_REDIRECT_URI,
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(f"{SWIGGY_BASE_URL}/auth/token", json=payload)
    _raise_for_response(response, "token exchange")
    data = _json_or_text(response)

    if not isinstance(data, dict) or not data.get("access_token"):
        raise SwiggyError("Swiggy did not return an access token")

    return data


class SwiggyFoodClient:
    """Small raw MCP client for the Food server's Streamable HTTP endpoint."""

    def __init__(self, access_token: str):
        if not access_token:
            raise SwiggyAuthError("Swiggy is not connected", 401)
        self.access_token = access_token
        self._request_id = 0
        self._session_id: str | None = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _parse_streamable_response(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            data = _json_or_text(response)
            if isinstance(data, dict):
                return data
            raise SwiggyError("Swiggy returned an invalid MCP response")

        latest: dict[str, Any] | None = None
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                candidate = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                latest = candidate

        if latest is None:
            raise SwiggyError("Swiggy returned an empty MCP response")
        return latest

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        with httpx.Client(timeout=45) as client:
            response = client.post(SWIGGY_FOOD_URL, json=body, headers=headers)

        _raise_for_response(response, "MCP request")
        self._session_id = response.headers.get("Mcp-Session-Id") or self._session_id
        data = self._parse_streamable_response(response)

        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise SwiggyError(f"Swiggy MCP error: {message}")

        return data

    def initialize(self):
        self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "muse-ai", "version": "1.0.0"},
            },
        })

        # MCP notifications do not require a response.  Some servers accept
        # the following request shape more consistently than an empty body.
        try:
            self._post({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            })
        except SwiggyError:
            pass

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.initialize()
        response = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        result = response.get("result", response)

        if isinstance(result, dict) and result.get("isError"):
            raise SwiggyError(_content_text(result.get("content")) or "Swiggy tool call failed")

        return structured_tool_result(result)


def get_food_delivery_status(client: SwiggyFoodClient, provider_order_id: str) -> Any:
    """Use the current recipe name, with compatibility for the status alias."""
    try:
        return client.call_tool("track_food_order", {"orderId": provider_order_id})
    except SwiggyError as error:
        message = str(error).casefold()
        if not any(
            marker in message
            for marker in ("unknown tool", "method not found", "not found", "does not exist")
        ):
            raise
        return client.call_tool(
            "get_food_delivery_status",
            {"orderId": provider_order_id},
        )


def _content_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    texts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(str(item.get("text", "")))
        elif getattr(item, "type", None) == "text":
            texts.append(str(getattr(item, "text", "")))
    return "\n".join(texts).strip()


def structured_tool_result(result: Any) -> Any:
    structured = (
        result.get("structuredContent")
        if isinstance(result, dict)
        else getattr(result, "structured_content", None)
    )
    if structured is not None:
        return structured.get("data", structured) if isinstance(structured, dict) else structured

    content = result.get("content") if isinstance(result, dict) else getattr(result, "content", None)
    text = _content_text(content)
    if text:
        try:
            parsed = json.loads(text)
            return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
        except json.JSONDecodeError:
            return text

    return result.get("data", result) if isinstance(result, dict) else result


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def _first_value(data: Any, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def cart_total(cart: Any) -> Decimal | None:
    candidates = []
    if isinstance(cart, dict):
        candidates.extend([
            cart.get("total"),
            cart.get("grandTotal"),
            cart.get("totalAmount"),
            cart.get("payableAmount"),
            cart.get("toPay"),
            cart.get("to_pay"),
            cart.get("billTotal"),
            cart.get("orderTotal"),
            cart.get("netTotal"),
            cart.get("itemTotal"),
        ])
        for nested_key in ("cart", "bill", "pricing", "payment", "charges"):
            nested = cart.get(nested_key)
            if isinstance(nested, dict):
                candidates.extend([
                    nested.get("total"),
                    nested.get("grandTotal"),
                    nested.get("toPay"),
                    nested.get("payableAmount"),
                    nested.get("billTotal"),
                    nested.get("orderTotal"),
                ])

    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return Decimal(str(candidate).replace(",", "").replace("₹", "").strip())
        except (InvalidOperation, ValueError):
            continue
    return None

def normalize_cart(cart: Any) -> dict[str, Any]:
    source = unwrap_data(cart)
    if not isinstance(source, dict):
        return {"items": [], "total": None, "raw": source}

    nested = source.get("cart") if isinstance(source.get("cart"), dict) else source
    items = nested.get("items") or nested.get("cartItems") or []
    safe_items = []
    for item in items[:50] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        safe_items.append({
            "name": str(_first_value(item, "name", "itemName", "title") or "Item")[:120],
            "quantity": int(_first_value(item, "quantity", "qty") or 1),
            "price": _first_value(item, "price", "itemPrice", "unitPrice"),
            "variant": str(_first_value(item, "variant", "variantName") or "")[:120],
        })

    total = cart_total(source)
    return {
        "restaurant_name": str(_first_value(
            source, "restaurantName", "restaurant", "merchantName"
        ) or "Swiggy restaurant")[:120],
        "items": safe_items,
        "total": float(total) if total is not None else None,
        "currency": "INR",
        "address": str(_first_value(source, "address", "deliveryAddress") or "")[:300],
    }


def enforce_cart_cap(cart: Any) -> dict[str, Any]:
    normalized = normalize_cart(cart)
    total = cart_total(cart)
    if total is not None and total > SWIGGY_CART_CAP:
        raise SwiggyError("This Swiggy order exceeds the ₹1,000 cart cap", 422)
    if total is None:
        raise SwiggyError("Swiggy did not return a final cart total", 502)
    return normalized


def order_status(order: Any) -> str:
    source = unwrap_data(order)
    if isinstance(source, dict):
        for key in ("status", "orderStatus", "deliveryStatus", "state"):
            value = source.get(key)
            if value:
                return str(value).upper().replace(" ", "_")
        nested = source.get("order")
        if isinstance(nested, dict):
            return order_status(nested)
    return "UNKNOWN"


def order_eta_minutes(order: Any) -> int | None:
    source = unwrap_data(order)
    if not isinstance(source, dict):
        return None
    for key in ("etaMinutes", "eta_minutes", "remainingMinutes"):
        value = source.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    eta = source.get("eta")
    if isinstance(eta, dict):
        return order_eta_minutes(eta)
    nested = source.get("order")
    if isinstance(nested, dict):
        return order_eta_minutes(nested)
    return None


def order_id(order: Any) -> str | None:
    source = unwrap_data(order)
    if isinstance(source, dict):
        for key in ("orderId", "order_id", "id"):
            if source.get(key):
                return str(source[key])
        nested = source.get("order")
        if isinstance(nested, dict):
            return order_id(nested)
    return None
