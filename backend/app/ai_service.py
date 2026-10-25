import asyncio
import json
import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, Literal
from zoneinfo import ZoneInfo
from .sandbox_service import e2b_is_configured, execute_python_in_sandbox
from .firecrawl_service import (
    firecrawl_is_configured,
    firecrawl_scrape_url,
    firecrawl_search,
)

from agents import (
    Agent,
    FunctionToolResult,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunConfig,
    RunContextWrapper,
    Runner,
    ToolsToFinalOutputResult,
    function_tool,
)
from agents.mcp import MCPServerStreamableHttp
from agents.stream_events import AgentUpdatedStreamEvent, RunItemStreamEvent
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent
from .model_config import create_llm_client, get_llm_model_name
from .scratchpad import ScratchpadState, update_scratchpad
from .subagents import build_agent_system
from .swiggy_service import (
    SWIGGY_FOOD_URL,
    SwiggyAuthError,
    SwiggyError,
    enforce_cart_cap,
    structured_tool_result,
    swiggy_is_configured,
)
from .tool_registry import get_tool
from .composio_service import (
    authorize_tool,
    get_tool_states,
    restore_composio_session,
    wrap_composio_tools_with_approval,
)


load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
load_dotenv(override=True)


BASE_AGENT_INSTRUCTIONS = """
You are {agent_name}, the primary autonomous personal AI assistant and supervisor inside Muse AI.
You have direct access to scheduling, phone calls, integration tools, a planning scratchpad, and specialist sub-agents.

CORE AGENTIC PRINCIPLES:
1. RELENTLESS GOAL COMPLETION & PLANNING:
   - For multi-step, comparison, or complex tasks (e.g. comparing restaurants, research, multi-part requests), call update_scratchpad immediately to establish clear milestones and record working notes.
   - Always check whether the USER'S ORIGINAL GOAL is complete before returning your final answer.
   - Never stop just because a single tool call succeeded.
2. SPECIALIST DELEGATION:
   - You have dedicated domain specialist agents available via transfer tools.
   - For restaurant searches, food menus, dietary options, food comparisons, or Swiggy orders: transfer to the Food Specialist immediately.
   - For public web browsing, internet research, and live webpage interaction: transfer to the Browser Specialist immediately.
   - If a specialist is not enabled in the current session, use the directly provided fallback tools.
3. IMMEDIATE ACTION, NO FILLER:
   - When the user asks you to do something, TAKE ACTION immediately on Turn 1.
   - Do not ask the user for details you can discover through tools, specialists, or existing memory.
   - Never roleplay or output meta-commentary like "I am now going to search for..." or "Let me connect you". Execute the tool directly.
   - When presenting a confirmation card (food cart, schedule, or account connection), briefly summarize what you prepared so the user has full context.

CONNECTED SERVICES & AUTOMATION:
- When the user asks to run something later or on a recurring schedule, call schedule_task.
- When the user asks to call someone now or at a time, call call_contact.
- For connected integrations (Composio), execute tools directly for read-only actions and ask confirmation for destructive actions.
""".strip()


@dataclass
class AgentRuntimeContext:
    messages: list[dict[str, str]]
    timezone: str
    composio_session: Any = None
    tool_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    callback_url: str | None = None
    browser_handler: Callable[[str, Callable[[dict], None], Event], str] | None = None
    event_sink: Callable[[dict], None] | None = None
    cancel_event: Event | None = None
    action: dict | None = None
    swiggy_access_token: str | None = None
    swiggy_callback_url: str | None = None
    swiggy_mcp_server: MCPServerStreamableHttp | None = None
    active_agent: str = "cooper"
    agent_name: str = "Cooper"
    memory_context: str | None = None
    scratchpad: ScratchpadState = field(default_factory=ScratchpadState)
    specialists: dict[str, Any] = field(default_factory=dict)


def build_agent_instructions(
    timezone: str = "UTC",
    tool_states: dict | None = None,
    memory_context: str | None = None,
    swiggy_connected: bool = False,
    agent_name: str = "Cooper",
    scratchpad_summary: str | None = None,
) -> str:
    selected_timezone = timezone or "UTC"

    try:
        current_time = datetime.now(ZoneInfo(selected_timezone))
    except Exception:
        selected_timezone = "UTC"
        current_time = datetime.now(UTC)

    base_prompt = BASE_AGENT_INSTRUCTIONS.format(agent_name=agent_name or "Cooper")
    instructions = (
        f"{base_prompt}\n\n"
        f"The user's local timezone is {selected_timezone}. "
        f"The current local time is {current_time.isoformat()}."
    )

    if memory_context:
        instructions += (
            f"\n\n{memory_context}\n"
            "Proactively respect the user's known preferences and profile "
            "details above without asking them to repeat themselves."
        )

    if scratchpad_summary and scratchpad_summary != "Scratchpad is empty.":
        instructions += f"\n\n{scratchpad_summary}"

    if not swiggy_connected:
        instructions += (
            "\nSwiggy account connection: false. If the user asks to search, "
            "browse, or order food, call connect_swiggy_account immediately in this response. "
            "Do not ask the user for pincodes, addresses, or restaurant preferences in plain text."
        )
    else:
        instructions += (
            "\nSwiggy account connection: true. You have full access to Swiggy Food tools. "
            "Always call get_addresses first to get the user's saved delivery location."
        )

    if tool_states is not None:
        connection_states = {
            tool_id: bool(state.get("connected"))
            for tool_id, state in tool_states.items()
        }
        instructions += (
            "\nCurrent account connection states: "
            f"{json.dumps(connection_states)}. "
            "If the request needs an account marked false, call "
            "connect_account immediately in this response. Do not ask the "
            "user to confirm the connection and do not tell them to send "
            "another message first. Read-only actions do not require "
            "confirmation once the account is connected."
        )

    return instructions


def _supervisor_dynamic_instructions(
    run_ctx: RunContextWrapper[AgentRuntimeContext],
    _agent: Agent,
) -> str:
    ctx = run_ctx.context
    return build_agent_instructions(
        timezone=ctx.timezone,
        tool_states=ctx.tool_states or None,
        memory_context=ctx.memory_context,
        swiggy_connected=bool(ctx.swiggy_access_token),
        agent_name=ctx.agent_name,
        scratchpad_summary=ctx.scratchpad.summary() if ctx.scratchpad else None,
    )


def _food_tool_error(context: RunContextWrapper[AgentRuntimeContext], error: Exception):
    if isinstance(error, SwiggyAuthError) or getattr(error, "status_code", None) == 401:
        context.context.swiggy_access_token = None
        context.context.action = {
            "type": "swiggy_connect_required",
            "action": True,
            "message": "Your Swiggy session needs to be connected again.",
            "output": "Your Swiggy session needs to be connected again.",
            "artifact": {
                "kind": "swiggy_connect_cta",
                "data": {
                    "toolName": "Swiggy Food",
                    "callbackUrl": context.context.swiggy_callback_url,
                },
            },
            "connect_cta": {
                "toolName": "Swiggy Food",
                "callbackUrl": context.context.swiggy_callback_url,
            },
        }
        return "Swiggy authorization is required."
    raise error


def _swiggy_mcp_error(context: RunContextWrapper[AgentRuntimeContext], error: Exception) -> str:
    err_text = str(error or "")
    lower_err = err_text.lower()
    if (
        getattr(error, "status_code", None) == 401
        or "401" in lower_err
        or "unauthorized" in lower_err
        or "expired" in lower_err
        or "invalid token" in lower_err
        or "authentication" in lower_err
    ):
        return _food_tool_error(context, SwiggyAuthError("Swiggy authorization expired", 401))

    return (
        f"Swiggy MCP tool error: {err_text}. "
        "CRITICAL: Do NOT retry the same failing tool call more than once. "
        "If Swiggy is unreachable or authorization failed, call connect_swiggy_account "
        "or inform the user immediately."
    )

@function_tool(
    description_override=(
        "Connect the user's Swiggy account before food ordering. Call this "
        "when there is no active Swiggy session; the app will show an "
        "authorization button."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
def connect_swiggy_account(context: RunContextWrapper[AgentRuntimeContext]) -> str:
    if context.context.swiggy_access_token:
        return "Swiggy is already connected. Continue with the food request."
    if not swiggy_is_configured():
        context.context.action = {
            "type": "swiggy_not_configured",
            "action": True,
            "message": "Swiggy ordering is not configured on this backend yet.",
            "output": "Swiggy ordering is not configured on this backend yet.",
        }
        return "Swiggy is not configured."
    context.context.action = {
        "type": "swiggy_connect_required",
        "action": True,
        "message": "Connect Swiggy to search restaurants and order food.",
        "output": "Connect Swiggy to search restaurants and order food.",
        "artifact": {
            "kind": "swiggy_connect_cta",
            "data": {
                "toolName": "Swiggy Food",
                "callbackUrl": context.context.swiggy_callback_url,
            },
        },
        "connect_cta": {
            "toolName": "Swiggy Food",
            "callbackUrl": context.context.swiggy_callback_url,
        },
    }
    return "The Swiggy authorization button is ready."


@function_tool(
    description_override=(
        "Prepare the Swiggy order confirmation card in the app. "
        "Pass the address_id (REQUIRED for checkout), restaurant_name, total amount, "
        "delivery address text, and items_summary from the current Swiggy cart."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
async def prepare_food_order(
    context: RunContextWrapper[AgentRuntimeContext],
    address_id: str | None = None,
    restaurant_name: str | None = None,
    total: float | None = None,
    address: str | None = None,
    items_summary: str | None = None,
) -> str:
    import re

    server = context.context.swiggy_mcp_server
    if server is None and not context.context.swiggy_access_token:
        return _food_tool_error(context, SwiggyAuthError("Swiggy is not connected", 401))

    normalized: dict[str, Any] | None = None
    payment_options: dict[str, Any] = {}

    if server is not None:
        for cart_args in (
            {"addressId": address_id} if address_id else {},
            {},
        ):
            try:
                result = await server.call_tool("get_food_cart", cart_args)
                if not getattr(result, "is_error", False):
                    raw_cart = structured_tool_result(result)
                    if isinstance(raw_cart, dict) and not address_id:
                        address_id = str(raw_cart.get("addressId") or "") or None
                    normalized = enforce_cart_cap(raw_cart)
                    break
            except SwiggyAuthError as auth_err:
                return _food_tool_error(context, auth_err)
            except Exception:
                continue

        # Fetch live UPI & COD payment options from Swiggy MCP
        try:
            pay_res = await server.call_tool(
                "get_payment_options",
                {"addressId": address_id} if address_id else {},
            )
            if not getattr(pay_res, "is_error", False):
                pay_data = structured_tool_result(pay_res)
                if isinstance(pay_data, dict):
                    payment_options = pay_data
                    if not address_id and pay_data.get("addressId"):
                        address_id = str(pay_data["addressId"])
        except Exception:
            pass

    # Fallback if get_food_cart schema lacked a top-level total or required arguments
    if normalized is None:
        fallback_total = float(total) if total is not None else 0.0
        if fallback_total > 1000:
            return "Order total exceeds the ₹1,000 cart cap. Please remove an item first."
        parsed_items = []
        if items_summary:
            for part in str(items_summary).split(","):
                clean_part = part.strip()
                if not clean_part:
                    continue
                qty = 1
                qty_match = re.match(r"^(\d+)\s*[xX×]\s+(.*)$", clean_part)
                if qty_match:
                    qty = int(qty_match.group(1))
                    clean_part = qty_match.group(2).strip()
                price_val = None
                price_match = re.search(r"[-—–:]?\s*₹\s*(\d+(?:\.\d+)?)\s*$", clean_part)
                if price_match:
                    price_val = float(price_match.group(1))
                    clean_part = clean_part[:price_match.start()].strip()
                parsed_items.append(
                    {
                        "name": clean_part or "Item",
                        "quantity": qty,
                        "price": price_val,
                        "variant": "",
                    }
                )
        normalized = {
            "restaurant_name": str(restaurant_name or "Swiggy Restaurant")[:120],
            "items": parsed_items
            or [
                {
                    "name": "Selected Cart Items",
                    "quantity": 1,
                    "price": fallback_total,
                    "variant": "",
                }
            ],
            "total": fallback_total,
            "currency": "INR",
            "address": str(address or "Saved Swiggy Address")[:300],
        }

    final_restaurant = normalized.get("restaurant_name") or restaurant_name or "Swiggy"
    final_total = normalized.get("total") or total or 0
    summary_msg = (
        f"Prepared your Swiggy cart from {final_restaurant} (Total: ₹{final_total}). "
        "Review and confirm below."
    )

    upi_methods = []
    platforms = (
        payment_options.get("platforms") if isinstance(payment_options, dict) else {}
    )
    if isinstance(platforms, dict):
        mobile_group = platforms.get("mobile") or {}
        if isinstance(mobile_group, dict) and isinstance(
            mobile_group.get("methods"), list
        ):
            upi_methods = mobile_group["methods"]
    if not upi_methods and isinstance(payment_options.get("allMethods"), list):
        upi_methods = payment_options["allMethods"]

    context.context.action = {
        "type": "food_order_confirmation",
        "action": True,
        "message": summary_msg,
        "output": summary_msg,
        "food_confirmation": {
            "cart": normalized,
            "address_id": address_id,
            "payment_method": "COD",
            "upi_methods": upi_methods[:6],
            "total": final_total,
            "currency": normalized.get("currency", "INR"),
            "cart_cap": 1000,
            "summary": (
                "Review the restaurant, items, delivery address, and total. "
                "You can place this order via UPI or Cash on Delivery."
            ),
        },
    }
    context.context.action["artifact"] = {
        "kind": "food_order_confirmation",
        "data": context.context.action["food_confirmation"],
    }
    return "The Swiggy order confirmation card is ready."

def get_model_name():
    return get_llm_model_name()


def create_agent_model():
    client = create_llm_client()
    model = OpenAIChatCompletionsModel(
        model=get_model_name(),
        openai_client=client,
    )
    return model, client


@function_tool(
    description_override=(
        "Propose a recurring or one-time automated task. The app will show "
        "a confirmation card before creating it."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
def schedule_task(
    context: RunContextWrapper[AgentRuntimeContext],
    title: str,
    prompt: str,
    frequency: Literal["daily", "weekly", "interval", "once"],
    time: str | None = None,
    weekday: str | None = None,
    interval_minutes: int | None = None,
    delivery: Literal["chat", "email", "slack", "notion"] = "chat",
) -> str:
    original_prompt = next(
        (
            message["content"]
            for message in reversed(context.context.messages)
            if message.get("role") == "user"
        ),
        prompt,
    )
    schedule_rule = {"frequency": frequency}

    if time:
        schedule_rule["time"] = time
    if weekday:
        schedule_rule["weekday"] = weekday
    if interval_minutes is not None:
        schedule_rule["interval_minutes"] = interval_minutes

    clean_title = str(title or "Scheduled Muse AI task")[:80]
    context.context.action = {
        "type": "schedule_confirmation",
        "action": True,
        "message": f"Ready to schedule '{clean_title}'. Confirm below to activate.",
        "confirmation": {
            "title": clean_title,
            "originalPrompt": original_prompt,
            "taskType": "generic_prompt",
            "taskPayload": {
                "prompt": prompt,
                "task": prompt,
                "useOpenAi": True,
            },
            "scheduleRule": schedule_rule,
            "timezone": context.context.timezone or "UTC",
            "delivery": delivery,
            "summary": (
                f"{context.context.agent_name} will run '{clean_title}' on schedule "
                f"and deliver results in {delivery}."
            ),
        },
    }
    context.context.action["artifact"] = {
        "kind": "schedule_confirmation",
        "data": context.context.action["confirmation"],
    }
    return "The schedule confirmation card is ready."


@function_tool(
    description_override="Call a contact now or schedule a local call reminder.",
    use_docstring_info=False,
    strict_mode=False,
)
def call_contact(
    context: RunContextWrapper[AgentRuntimeContext],
    contact_name: str,
    call_time: str = "now",
) -> str:
    selected_contact = str(contact_name or "").strip()

    if not selected_contact:
        raise RuntimeError("The calling tool did not return a contact name")

    context.context.action = {
        "type": "call_action",
        "action": True,
        "message": f"Preparing your call with {selected_contact}...",
        "contact_name": selected_contact,
        "call_time": str(call_time or "now").strip().lower(),
    }
    return "The call action is ready."


@function_tool(
    description_override=(
        "Show an authorization button when the user's request needs a "
        "currently disconnected account. Call this immediately instead of "
        "asking permission."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
def connect_account(
    context: RunContextWrapper[AgentRuntimeContext],
    tool_id: str,
) -> str:
    tool = get_tool(tool_id)

    if context.context.tool_states.get(tool_id, {}).get("connected"):
        return "The account is already connected. Continue the request."

    if context.context.composio_session is None:
        raise RuntimeError("The integration session is unavailable")

    if not context.context.callback_url:
        raise RuntimeError("A connection callback URL is required")

    connection = authorize_tool(
        context.context.composio_session,
        tool_id,
        context.context.callback_url,
    )
    tool_name = tool.name
    context.context.action = {
        "type": "connect_required",
        "action": True,
        "message": f"Connect {tool_name} so I can complete this for you.",
        "output": f"Connect {tool_name} so I can complete this for you.",
        "connect_cta": {
            "toolName": tool_name,
            "connectUrl": connection["redirect_url"],
            "requestId": connection["request_id"],
            "callbackUrl": context.context.callback_url,
        },
    }
    context.context.action["artifact"] = {
        "kind": "connect_cta",
        "data": context.context.action["connect_cta"],
    }
    return "The connection button is ready."



@function_tool(
    description_override=(
        "Fast web search and Markdown page scraper powered by Firecrawl. "
        "Pass EITHER a `url` to scrape clean Markdown from a webpage/article/docs, "
        "OR a `query` to search the live web and extract full Markdown from top results. "
        "Use this first for all research, news, pricing, and reading tasks."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
async def web_search_and_scrape(
    context: RunContextWrapper[AgentRuntimeContext],
    query: str | None = None,
    url: str | None = None,
    limit: int = 5,
) -> str:
    clean_url = (url or "").strip()
    clean_query = (query or "").strip()

    if not clean_url and not clean_query:
        raise RuntimeError("Provide either a 'url' to scrape or a 'query' to search.")

    event_sink = context.context.event_sink or (lambda _event: None)

    if clean_url:
        event_sink({"type": "status", "message": f"Firecrawl: Reading {clean_url[:60]}..."})
        content, _ = await asyncio.to_thread(firecrawl_scrape_url, clean_url)
        return content

    event_sink({"type": "status", "message": f"Firecrawl: Searching '{clean_query[:60]}'..."})
    content, _ = await asyncio.to_thread(firecrawl_search, clean_query, limit=limit)
    return content

@function_tool(
    description_override=(
        "Use a secure browser for current public web information or website "
        "interaction. Give it one complete, precise task. It returns evidence "
        "for you to summarize or pass to another tool."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
async def browse_web(
    context: RunContextWrapper[AgentRuntimeContext],
    task: str,
) -> str:
    selected_task = str(task or "").strip()

    if not selected_task:
        raise RuntimeError("The browser task cannot be empty")

    if context.context.browser_handler is None:
        raise RuntimeError("Browser access is unavailable")

    event_sink = context.context.event_sink or (lambda _event: None)
    cancel_event = context.context.cancel_event or Event()
    result = await asyncio.to_thread(
        context.context.browser_handler,
        selected_task,
        event_sink,
        cancel_event,
    )
    return str(result)[:20000]

@function_tool(
    description_override=(
        "Execute Python code in a secure cloud E2B sandbox for data analysis, "
        "math, file parsing, or chart generation (matplotlib/seaborn). "
        "Charts are automatically captured and shown in the user's chat card."
    ),
    use_docstring_info=False,
    strict_mode=False,
)
async def run_python_sandbox(
    context: RunContextWrapper[AgentRuntimeContext],
    code: str,
    title: str = "Python Execution",
    expose_port: int | None = None,
) -> str:
    event_sink = context.context.event_sink or (lambda _event: None)
    payload = await asyncio.to_thread(
        execute_python_in_sandbox,
        code,
        title,
        expose_port,
        event_sink,
    )
    summary = [f"Status: {payload['status']}"]
    if payload.get("stdout"):
        summary.append(f"STDOUT:\n{payload['stdout']}")
    if payload.get("stderr"):
        summary.append(f"STDERR:\n{payload['stderr']}")
    if payload.get("error"):
        summary.append(f"ERROR:\n{payload['error']}")
    if payload.get("charts"):
        summary.append(
            f"Generated {len(payload['charts'])} chart(s) — already displayed to the user in the Sandbox Preview Card."
        )
    if payload.get("preview_url"):
        summary.append(f"Live Preview URL: {payload['preview_url']}")
    return "\n\n".join(summary)

def stop_on_app_action(
    context: RunContextWrapper[AgentRuntimeContext],
    _tool_results: list[FunctionToolResult],
) -> ToolsToFinalOutputResult:
    if context.context.action is None:
        return ToolsToFinalOutputResult(is_final_output=False)

    return ToolsToFinalOutputResult(
        is_final_output=True,
        final_output=context.context.action.get("message") or json.dumps(context.context.action),
    )


def agent_state_name(agent) -> str:
    if agent is None:
        return "cooper"
    name = getattr(agent, "name", "cooper").lower().replace(" ", "_")
    if "food" in name:
        return "food"
    if "browser" in name:
        return "browser"
    if "code" in name or "sandbox" in name:
        return "code"
    return "cooper"


def update_active_agent_from_result(context: AgentRuntimeContext, result):
    last_agent = getattr(result, "last_agent", None)
    if last_agent is None:
        return False
    context.active_agent = agent_state_name(last_agent)
    return True


def _extract_tool_call_info(item: Any) -> tuple[str, dict[str, Any]]:
    raw_item = getattr(item, "raw_item", None)
    tool_name = (
        getattr(item, "tool_name", None)
        or getattr(raw_item, "name", None)
        or (raw_item.get("name") if isinstance(raw_item, dict) else None)
        or "tool"
    )
    raw_args = (
        getattr(raw_item, "arguments", None)
        or (raw_item.get("arguments") if isinstance(raw_item, dict) else None)
        or "{}"
    )
    parsed_args: dict[str, Any] = {}
    if isinstance(raw_args, str):
        with suppress(Exception):
            data = json.loads(raw_args)
            if isinstance(data, dict):
                parsed_args = data
    elif isinstance(raw_args, dict):
        parsed_args = raw_args
    return str(tool_name), parsed_args


def _format_tool_status_message(raw_tool: str, args: dict[str, Any], finished: bool = False) -> str:
    if raw_tool.startswith("transfer_to_"):
        target = raw_tool.replace("transfer_to_", "").replace("_", " ").title()
        return f"Transferred to {target}" if finished else f"Transferring to {target}..."
    if raw_tool == "update_scratchpad":
        plan = args.get("plan") or []
        idx = int(args.get("current_step_index") or 0)
        if plan and 0 <= idx < len(plan):
            return f"Plan Step {idx + 1}/{len(plan)}: {plan[idx]}"
        return "Execution plan updated" if finished else "Updating execution plan..."
    if raw_tool == "web_search_and_scrape":
        target = str(args.get("url") or args.get("query") or "")[:65]
        return (
            f"Finished Firecrawl ({target})"
            if finished
            else f"Firecrawl: {target}..."
        )
    if raw_tool == "browse_web":
        task_preview = str(args.get("task") or "")[:70]
        if task_preview:
            return f"Finished browsing: {task_preview}" if finished else f"Browsing web: {task_preview}..."
    label = raw_tool.replace("_", " ")
    detail = (
        args.get("query")
        or args.get("search_query")
        or args.get("restaurant_name")
        or args.get("title")
        or args.get("contact_name")
    )
    if detail:
        return f"Finished {label} ({str(detail)[:50]})" if finished else f"Running {label}: {str(detail)[:50]}..."
    return f"Finished {label}" if finished else f"Using {label}..."


def create_agent_runtime(
    messages: list[dict[str, str]],
    composio_session_id: str | None = None,
    timezone: str = "UTC",
    callback_url: str | None = None,
    browser_handler: Callable[[str, Callable[[dict], None], Event], str] | None = None,
    event_sink: Callable[[dict], None] | None = None,
    cancel_event: Event | None = None,
    swiggy_access_token: str | None = None,
    swiggy_callback_url: str | None = None,
    preferred_agent: str = "cooper",
    memory_context: str | None = None,
    agent_name: str = "Cooper",
):
    composio_session = None
    tool_states = None
    tools = [
        schedule_task,
        call_contact,
        update_scratchpad,
        connect_swiggy_account,
        prepare_food_order,
    ]
    
    if firecrawl_is_configured():
        tools.append(web_search_and_scrape)

    if browser_handler:
        tools.append(browse_web)
    
    if e2b_is_configured():
        tools.append(run_python_sandbox)

    if composio_session_id:
        composio_session = restore_composio_session(composio_session_id)
        tools = wrap_composio_tools_with_approval(
            list(composio_session.tools())) + tools

        if callback_url:
            tool_states = get_tool_states(
                composio_session,
                include_account=False,
            )
            tools.append(connect_account)

    swiggy_mcp_server = None
    if swiggy_access_token:
        swiggy_mcp_server = MCPServerStreamableHttp(
            params={
                "url": SWIGGY_FOOD_URL,
                "headers": {"Authorization": f"Bearer {swiggy_access_token}"},
                "timeout": 30.0,
                "sse_read_timeout": 60.0,
            },
            cache_tools_list=True,
            name="Swiggy Food",
            client_session_timeout_seconds=30.0,
            tool_filter={
                "blocked_tool_names": [
                    "place_food_order",
                    "get_payment_options",
                    "check_payment_status",
                    "confirm_order",
                ]
            },
            failure_error_function=_swiggy_mcp_error,
        )

    model, client = create_agent_model()
    context = AgentRuntimeContext(
        messages=messages,
        timezone=timezone,
        composio_session=composio_session,
        tool_states=tool_states or {},
        callback_url=callback_url,
        browser_handler=browser_handler,
        event_sink=event_sink,
        cancel_event=cancel_event,
        swiggy_access_token=swiggy_access_token,
        swiggy_callback_url=swiggy_callback_url,
        swiggy_mcp_server=swiggy_mcp_server,
        active_agent=preferred_agent or "cooper",
        agent_name=agent_name or "Cooper",
        memory_context=memory_context,
    )
    supervisor = Agent(
        name=agent_name or "Cooper",
        instructions=_supervisor_dynamic_instructions,
        model=model,
        model_settings=ModelSettings(parallel_tool_calls=True),
        tools=tools,
        mcp_servers=[swiggy_mcp_server] if swiggy_mcp_server else [],
        tool_use_behavior=stop_on_app_action,
    )

    supervisor, specialists = build_agent_system(
        supervisor_agent=supervisor,
        context=context,
        model=model,
        tool_use_behavior=stop_on_app_action,
    )
    context.specialists = specialists

    entry_agent = supervisor
    if preferred_agent in specialists:
        entry_agent = specialists[preferred_agent]

    return entry_agent, context, client


def get_run_config():
    enable_tracing = os.getenv("MUSE_ENABLE_AGENT_TRACING", "false").lower() == "true"
    return RunConfig(
        tracing_disabled=not enable_tracing,
        workflow_name="Muse AI assistant",
    )


async def generate_reply_async(
    messages: list[dict[str, str]],
    composio_session_id: str | None = None,
    timezone: str = "UTC",
    callback_url: str | None = None,
    browser_handler: Callable[[str, Callable[[dict], None], Event], str] | None = None,
    event_sink: Callable[[dict], None] | None = None,
    swiggy_access_token: str | None = None,
    swiggy_callback_url: str | None = None,
    preferred_agent: str = "cooper",
    include_metadata: bool = False,
    memory_context: str | None = None,
    agent_name: str = "Cooper",
) -> str | dict:
    agent, context, client = await asyncio.to_thread(
        create_agent_runtime,
        messages,
        composio_session_id,
        timezone,
        callback_url,
        browser_handler,
        event_sink,
        None,
        swiggy_access_token,
        swiggy_callback_url,
        preferred_agent,
        memory_context,
        agent_name,
    )

    mcp_connected = False
    try:
        if context.swiggy_mcp_server:
            await context.swiggy_mcp_server.connect()
            mcp_connected = True
        result = await Runner.run(
            agent,
            messages,
            context=context,
            max_turns=25,
            run_config=get_run_config(),
        )
    finally:
        if mcp_connected:
            await context.swiggy_mcp_server.cleanup()
        await client.close()

    update_active_agent_from_result(context, result)

    if context.action is not None:
        if not include_metadata:
            return context.action
        return {
            **context.action,
            "_active_agent": context.active_agent,
        }

    if result.final_output is None:
        raise RuntimeError("The agent returned no response")

    output = str(result.final_output).strip()
    if include_metadata:
        return {
            "type": "agent_reply",
            "output": output,
            "_active_agent": context.active_agent,
        }
    return output


def generate_reply(
    messages: list[dict[str, str]],
    composio_session_id: str | None = None,
    timezone: str = "UTC",
    callback_url: str | None = None,
    browser_handler: Callable[[str, Callable[[dict], None], Event], str] | None = None,
    event_sink: Callable[[dict], None] | None = None,
    swiggy_access_token: str | None = None,
    swiggy_callback_url: str | None = None,
    preferred_agent: str = "cooper",
    include_metadata: bool = False,
    memory_context: str | None = None,
    agent_name: str = "Cooper",
) -> str | dict:
    return asyncio.run(
        generate_reply_async(
            messages,
            composio_session_id,
            timezone,
            callback_url,
            browser_handler,
            event_sink,
            swiggy_access_token,
            swiggy_callback_url,
            preferred_agent,
            include_metadata,
            memory_context,
            agent_name,
        )
    )


async def stream_reply(
    messages: list[dict[str, str]],
    composio_session_id: str | None,
    timezone: str,
    callback_url: str | None,
    browser_handler: Callable[[str, Callable[[dict], None], Event], str] | None,
    swiggy_access_token: str | None = None,
    swiggy_callback_url: str | None = None,
    preferred_agent: str = "cooper",
    memory_context: str | None = None,
    agent_name: str = "Cooper",
):
    events: asyncio.Queue[Any] = asyncio.Queue()
    cancel_event = Event()
    loop = asyncio.get_running_loop()
    result = None
    producer_error: list[Exception] = []
    mcp_connected = False

    def emit_event(event: dict):
        if cancel_event.is_set():
            return
        try:
            loop.call_soon_threadsafe(events.put_nowait, event)
        except RuntimeError:
            return

    agent, context, client = await asyncio.to_thread(
        create_agent_runtime,
        messages,
        composio_session_id,
        timezone,
        callback_url,
        browser_handler,
        emit_event,
        cancel_event,
        swiggy_access_token,
        swiggy_callback_url,
        preferred_agent,
        memory_context,
        agent_name,
    )

    async def produce():
        nonlocal result, mcp_connected

        try:
            if context.swiggy_mcp_server:
                for attempt in range(2):
                    try:
                        await asyncio.wait_for(
                            context.swiggy_mcp_server.connect(),
                            timeout=15.0,
                        )
                        mcp_connected = True
                        break
                    except Exception as mcp_err:
                        if attempt == 0:
                            await asyncio.sleep(1.0)
                            continue
                        context.swiggy_mcp_server = None
                        for ag in [agent, *context.specialists.values()]:
                            if ag and getattr(ag, "mcp_servers", None):
                                ag.mcp_servers = []
                        await events.put(
                            {
                                "type": "status",
                                "message": f"Swiggy server timed out ({mcp_err}); continuing without live MCP...",
                            }
                        )
            result = Runner.run_streamed(
                agent,
                messages,
                context=context,
                max_turns=25,
                run_config=get_run_config(),
            )

            async for event in result.stream_events():
                if (
                    event.type == "raw_response_event"
                    and isinstance(event.data, ResponseTextDeltaEvent)
                    and event.data.delta
                ):
                    await events.put(event.data.delta)
                    continue

                if isinstance(event, AgentUpdatedStreamEvent):
                    new_agent = getattr(event, "new_agent", None)
                    new_name = getattr(new_agent, "name", "Specialist")
                    context.active_agent = agent_state_name(new_agent)
                    await events.put(
                        {
                            "type": "status",
                            "message": f"Handed off to {new_name}...",
                        }
                    )
                    await events.put(
                        {
                            "type": "agent_switched",
                            "agent": context.active_agent,
                            "name": new_name,
                        }
                    )
                    continue

                if isinstance(event, RunItemStreamEvent):
                    raw_tool, parsed_args = _extract_tool_call_info(event.item)
                    if event.name == "tool_called":
                        msg = _format_tool_status_message(raw_tool, parsed_args, finished=False)
                        await events.put(
                            {
                                "type": "tool_started",
                                "tool": raw_tool,
                                "arguments": parsed_args,
                                "message": msg,
                            }
                        )
                    elif event.name == "tool_output":
                        msg = _format_tool_status_message(raw_tool, parsed_args, finished=True)
                        await events.put(
                            {
                                "type": "tool_finished",
                                "tool": raw_tool,
                                "message": msg,
                            }
                        )

            if cancel_event.is_set():
                return

            has_runtime_agent = update_active_agent_from_result(context, result)

            if context.action is not None:
                action = {
                    **context.action,
                    "_active_agent": context.active_agent,
                }
                await events.put(action)
                return

            if result.final_output is None:
                raise RuntimeError("The agent returned no response")

            final_event = {
                "type": "agent_final",
                "output": str(result.final_output).strip(),
                "active_agent": context.active_agent if has_runtime_agent else preferred_agent,
            }
            await events.put(final_event)
        except Exception as error:
            producer_error.append(error)

    producer = asyncio.create_task(produce())
    last_event_at = time.monotonic()

    try:
        while True:
            if producer.done() and events.empty():
                break

            try:
                event = await asyncio.wait_for(events.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if time.monotonic() - last_event_at >= 15:
                    last_event_at = time.monotonic()
                    yield {"type": "heartbeat"}
                continue

            last_event_at = time.monotonic()
            yield event

        await producer

        if producer_error:
            raise producer_error[0]
    finally:
        cancel_event.set()

        if result is not None and not result.is_complete:
            result.cancel()

        if not producer.done():
            producer.cancel()

        with suppress(asyncio.CancelledError):
            await producer

        if mcp_connected:
            with suppress(Exception):
                await asyncio.wait_for(context.swiggy_mcp_server.cleanup(), timeout=2.0)

        with suppress(Exception):
            await asyncio.wait_for(client.close(), timeout=2.0)