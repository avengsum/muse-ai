import asyncio
import json
import os
from pathlib import Path
from typing import Any

from composio import Composio
from composio_openai_agents import OpenAIAgentsProvider
from dotenv import load_dotenv

from .tool_registry import TOOL_ID_BY_TOOLKIT, TOOLS, get_tool


load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


composio_client = None


def composio_is_configured() -> bool:
    return bool(os.getenv("COMPOSIO_API_KEY"))


def get_composio_client():
    global composio_client

    api_key = os.getenv("COMPOSIO_API_KEY")

    if not api_key:
        raise RuntimeError("COMPOSIO_API_KEY is missing")

    if composio_client is None:
        composio_client = Composio(
            api_key=api_key,
            provider=OpenAIAgentsProvider(),
        )

    return composio_client


def create_composio_session(user_id: str):
    client = get_composio_client()

    return client.create(
        user_id=user_id,
        toolkits=[tool.toolkit for tool in TOOLS],
        manage_connections=True,
        sandbox={
            "enable": False,
        },
    )


def restore_composio_session(session_id: str):
    client = get_composio_client()
    raw_session_id = (
        session_id.split(":", 1)[1]
        if isinstance(session_id, str)
        and ":" in session_id
        and session_id.startswith("v")
        else session_id
    )
    return client.use(raw_session_id)


def authorize_tool(
    session,
    tool_id: str,
    callback_url: str,
):
    toolkit_slug = get_tool(tool_id).toolkit

    request = session.authorize(
        toolkit_slug,
        callback_url=callback_url,
    )

    return {
        "request_id": request.id,
        "redirect_url": request.redirect_url,
    }


def get_account_label(account_id: str) -> str:
    client = get_composio_client()

    try:
        account = client.connected_accounts.get(account_id)
        account_data = account.model_dump()
        state = account_data.get("state") or {}
        values = state.get("val") or {}

        return (
            values.get("displayName")
            or values.get("display_name")
            or values.get("email")
            or account_id
        )
    except Exception:
        return account_id


def get_tool_states(session, include_account: bool = True):
    states = {
        tool_id: {
            "connected": False,
            "account": None,
            "account_id": None,
        }
        for tool_id in TOOL_ID_BY_TOOLKIT.values()
    }

    result = session.toolkits(
        toolkits=[tool.toolkit for tool in TOOLS],
        limit=20,
    )

    for toolkit in result.items:
        tool_id = TOOL_ID_BY_TOOLKIT.get(toolkit.slug.lower())

        if not tool_id:
            continue

        connection = toolkit.connection

        if not connection or not connection.is_active:
            continue

        connected_account = connection.connected_account

        if not connected_account:
            continue

        account_id = connected_account.id

        states[tool_id] = {
            "connected": True,
            "account": get_account_label(account_id) if include_account else None,
            "account_id": account_id,
        }

    return states


def disconnect_account(account_id: str):
    client = get_composio_client()

    try:
        client.connected_accounts.revoke(account_id)
    except Exception:
        client.connected_accounts.disable(account_id)


# ==============================================================================
# Universal Tool Approval Interceptor & Executor
# ==============================================================================

INTERNAL_DISCOVERY_TOOLS = frozenset(
    {
        "COMPOSIO_SEARCH_TOOLS",
        "COMPOSIO_LIST_TOOLKITS",
        "COMPOSIO_GET_TOOL_SCHEMAS",
        "COMPOSIO_WAIT_FOR_CONNECTION",
        "COMPOSIO_CHECK_ACTIVE_CONNECTION",
    }
)

BLOCKED_META_TOOLS = frozenset(
    {
        "COMPOSIO_REMOTE_WORKBENCH",
        "COMPOSIO_REMOTE_BASH_TOOL",
    }
)

READ_ONLY_VERBS = (
    "GET",
    "LIST",
    "FETCH",
    "SEARCH",
    "FIND",
    "READ",
    "CHECK",
    "VIEW",
    "INSPECT",
    "COUNT",
    "VERIFY",
    "DOWNLOAD",
    "EXPORT",
)

DESTRUCTIVE_VERBS = (
    "SEND",
    "CREATE",
    "DELETE",
    "REMOVE",
    "UPDATE",
    "EDIT",
    "MODIFY",
    "POST",
    "INSERT",
    "ADD",
    "ARCHIVE",
    "TRASH",
    "REPLY",
    "FORWARD",
    "PATCH",
    "WRITE",
    "MERGE",
    "CLOSE",
    "ASSIGN",
    "APPEND",
    "REPLACE",
    "UPLOAD",
    "SHARE",
)


def is_destructive_composio_tool(tool_name: str) -> bool:
    upper = (tool_name or "").upper()
    if upper in INTERNAL_DISCOVERY_TOOLS:
        return False

    parts = [p for p in upper.split("_") if p]
    if not parts:
        return False

    action_tokens = parts[1:] if len(parts) > 1 else parts
    if any(tok in DESTRUCTIVE_VERBS for tok in action_tokens):
        return True
    if any(tok in READ_ONLY_VERBS for tok in action_tokens):
        return False
    return True


def _humanize_tool_name(tool_name: str) -> tuple[str, str, str, str]:
    raw = (tool_name or "tool").strip()
    parts = raw.split("_")
    toolkit_slug = parts[0].lower() if parts else ""
    tool_id = TOOL_ID_BY_TOOLKIT.get(toolkit_slug)
    tool_def = get_tool(tool_id) if tool_id else None

    app_name = (
        tool_def.name
        if tool_def
        else (parts[0].title() if parts else "Workspace")
    )
    icon = tool_def.icon if tool_def else "construct-outline"
    color = tool_def.color if tool_def else "#2563EB"
    action_label = (
        " ".join(parts[1:]).title()
        if len(parts) > 1
        else raw.replace("_", " ").title()
    )
    return app_name, action_label, icon, color


def _extract_multi_execute_calls(parsed_args: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("tools", "tool_calls", "executions"):
        candidate = parsed_args.get(key)
        if isinstance(candidate, list) and candidate:
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _handle_manage_connections_intercept(ctx, parsed_args: dict[str, Any]) -> str | None:
    runtime_ctx = getattr(ctx, "context", None)
    if runtime_ctx is None or not getattr(runtime_ctx, "composio_session", None):
        return None

    toolkits = parsed_args.get("toolkits") or parsed_args.get("toolkit") or []
    if isinstance(toolkits, str):
        toolkits = [toolkits]
    if not isinstance(toolkits, list) or not toolkits:
        return None

    first_slug = str(toolkits[0]).strip().lower()
    tool_id = TOOL_ID_BY_TOOLKIT.get(first_slug)
    if not tool_id:
        return None

    if runtime_ctx.tool_states.get(tool_id, {}).get("connected"):
        return f"{first_slug} is already connected. Call the {first_slug} action tool directly now."

    callback_url = getattr(runtime_ctx, "callback_url", None)
    if not callback_url:
        return None

    tool_def = get_tool(tool_id)
    connection = authorize_tool(
        runtime_ctx.composio_session,
        tool_id,
        callback_url,
    )
    runtime_ctx.action = {
        "type": "connect_required",
        "action": True,
        "message": f"Connect {tool_def.name} so I can complete this for you.",
        "output": f"Connect {tool_def.name} so I can complete this for you.",
        "connect_cta": {
            "toolName": tool_def.name,
            "connectUrl": connection["redirect_url"],
            "requestId": connection["request_id"],
            "callbackUrl": callback_url,
        },
        "artifact": {
            "kind": "connect_cta",
            "data": {
                "toolName": tool_def.name,
                "connectUrl": connection["redirect_url"],
                "requestId": connection["request_id"],
                "callbackUrl": callback_url,
            },
        },
    }
    return f"The {tool_def.name} connection button is ready."


def wrap_composio_tools_with_approval(raw_tools: list[Any]) -> list[Any]:
    wrapped_tools = []
    for tool in raw_tools:
        tool_name = (getattr(tool, "name", "") or "").strip()
        upper_name = tool_name.upper()
        orig_invoke = getattr(tool, "on_invoke_tool", None)

        if upper_name in BLOCKED_META_TOOLS:
            continue

        if (
            not tool_name
            or not callable(orig_invoke)
            or upper_name in INTERNAL_DISCOVERY_TOOLS
        ):
            wrapped_tools.append(tool)
            continue

        def _make_interceptor(t_name: str, orig_fn):
            async def _intercepted_invoke(ctx, args_json: str) -> str:
                try:
                    parsed_args = json.loads(args_json) if args_json else {}
                except Exception:
                    parsed_args = {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {"value": parsed_args}

                upper_t = t_name.upper()

                if upper_t == "COMPOSIO_MANAGE_CONNECTIONS":
                    cta_msg = _handle_manage_connections_intercept(ctx, parsed_args)
                    if cta_msg is not None:
                        return cta_msg
                    return await orig_fn(ctx, args_json)

                if upper_t == "COMPOSIO_MULTI_EXECUTE_TOOL":
                    inner_calls = _extract_multi_execute_calls(parsed_args)
                    if not inner_calls:
                        return await orig_fn(ctx, args_json)

                    destructive_calls = [
                        call
                        for call in inner_calls
                        if is_destructive_composio_tool(
                            str(call.get("tool_slug") or call.get("name") or "")
                        )
                    ]
                    if not destructive_calls:
                        return await orig_fn(ctx, args_json)

                    primary_call = destructive_calls[0]
                    real_slug = str(
                        primary_call.get("tool_slug")
                        or primary_call.get("name")
                        or t_name
                    )
                    inner_args = primary_call.get("arguments")
                    if not isinstance(inner_args, dict):
                        inner_args = {}

                    app_name, action_label, icon, color = _humanize_tool_name(real_slug)
                    if len(destructive_calls) > 1:
                        action_label = f"{action_label} (+{len(destructive_calls) - 1} more)"

                    summary_msg = f"Review and approve **{app_name}: {action_label}** below."
                    runtime_ctx = getattr(ctx, "context", None)
                    if runtime_ctx is not None:
                        approval_payload = {
                            "tool_name": t_name,
                            "display_tool_name": real_slug,
                            "app_name": app_name,
                            "action_label": action_label,
                            "icon": icon,
                            "color": color,
                            "arguments": inner_args,
                            "_multi_wrapper": parsed_args,
                        }
                        runtime_ctx.action = {
                            "type": "tool_approval_request",
                            "action": True,
                            "message": summary_msg,
                            "output": summary_msg,
                            "tool_approval": approval_payload,
                            "artifact": {
                                "kind": "tool_approval_request",
                                "data": approval_payload,
                            },
                        }
                    return f"Paused for user approval before running {real_slug}."

                if not is_destructive_composio_tool(t_name):
                    return await orig_fn(ctx, args_json)

                clean_display_args = {
                    k: v
                    for k, v in parsed_args.items()
                    if k not in {"session_id", "sessionId"}
                }
                app_name, action_label, icon, color = _humanize_tool_name(t_name)
                summary_msg = f"Review and approve **{app_name}: {action_label}** below."

                runtime_ctx = getattr(ctx, "context", None)
                if runtime_ctx is not None:
                    approval_payload = {
                        "tool_name": t_name,
                        "display_tool_name": t_name,
                        "app_name": app_name,
                        "action_label": action_label,
                        "icon": icon,
                        "color": color,
                        "arguments": clean_display_args,
                    }
                    runtime_ctx.action = {
                        "type": "tool_approval_request",
                        "action": True,
                        "message": summary_msg,
                        "output": summary_msg,
                        "tool_approval": approval_payload,
                        "artifact": {
                            "kind": "tool_approval_request",
                            "data": approval_payload,
                        },
                    }
                return f"Paused for user approval before running {t_name}."

            return _intercepted_invoke

        tool.on_invoke_tool = _make_interceptor(tool_name, orig_invoke)
        wrapped_tools.append(tool)

    return wrapped_tools


async def execute_composio_tool_action(
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    multi_wrapper: dict[str, Any] | None = None,
    **_extra_kwargs: Any,
) -> Any:
    from agents.tool_context import ToolContext

    session = await asyncio.to_thread(restore_composio_session, session_id)
    raw_tools = await asyncio.to_thread(session.tools)

    target_tool = next(
        (t for t in raw_tools if getattr(t, "name", "") == tool_name),
        None,
    )
    if target_tool is None:
        raise RuntimeError(f"Tool '{tool_name}' is not available in this session")

    if multi_wrapper and isinstance(multi_wrapper, dict):
        execution_payload = json.loads(json.dumps(multi_wrapper))
        inner_list = _extract_multi_execute_calls(execution_payload)
        if inner_list and isinstance(arguments, dict):
            inner_list[0]["arguments"] = arguments
        args_str = json.dumps(execution_payload, ensure_ascii=False)
    else:
        args_str = json.dumps(arguments or {}, ensure_ascii=False)

    dummy_ctx = ToolContext(
        context=None,
        usage=None,
        tool_name=tool_name,
        tool_call_id=f"approved_{tool_name}",
        tool_arguments=args_str,
    )
    return await target_tool.on_invoke_tool(dummy_ctx, args_str)