import html
import json
import re
import time
from contextlib import suppress
from datetime import UTC, datetime
from threading import Event
from typing import Callable
from uuid import uuid4
from urllib.parse import quote_plus
from .firecrawl_service import (
    firecrawl_is_configured,
    firecrawl_scrape_url,
    firecrawl_search,
    is_safe_public_url,
)
import httpx

from .browser_service import (
    BROWSERBASE_TERMINAL_STATUSES,
    BrowserbaseError,
    browserbase_is_configured,
    create_browser_run,
    get_browser_live_urls,
    get_browser_run,
    get_browser_run_messages,
    stop_browser_run,
)
from .database import SessionLocal
from .models import BrowserRun
from .schemas import BrowserRunResponse


def _extract_first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s\"'<>)+]+", text or "")
    if match:
        return match.group(0).rstrip(".,;)")
    domain_match = re.search(
        r"\b([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s\"'<>)+]*)?)",
        text or "",
    )
    if domain_match:
        candidate = domain_match.group(1).rstrip(".,;)")
        if "/" in candidate or candidate.endswith(
            (".com", ".org", ".io", ".dev", ".in", ".ai")
        ):
            return f"https://{candidate}"
    return None


def _clean_html_to_readable_text(raw_html: str) -> str:
    def _replace_code(match: re.Match) -> str:
        code_inner = re.sub(r"<[^>]+>", "", match.group(1))
        return f"\n`\n{html.unescape(code_inner).strip()}\n```\n"

    processed = re.sub(
        r"<pre[^>]*>(.*?)</pre>",
        _replace_code,
        raw_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    processed = re.sub(
        r"<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>",
        " ",
        processed,
        flags=re.DOTALL | re.IGNORECASE,
    )
    processed = re.sub(
        r"<(h[1-6]|p|li|div|br|tr)[^>]*>",
        "\n",
        processed,
        flags=re.IGNORECASE,
    )
    processed = re.sub(r"<[^>]+>", " ", processed)
    unescaped = html.unescape(processed)
    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in unescaped.splitlines()
    ]
    clean_lines = [line for line in lines if line]
    return "\n".join(clean_lines)


def _fallback_direct_web_fetch(
    task: str,
    on_step: Callable[[str], None] | None = None,
) -> tuple[str, str | None]:
    target_url = _extract_first_url(task)

    # 1. Primary Fast Engine: Firecrawl (if configured)
    if firecrawl_is_configured():
        try:
            if target_url:
                if on_step:
                    on_step(f"Firecrawl: Scraping clean Markdown from {target_url}...")
                return firecrawl_scrape_url(target_url)
            else:
                query = (task or "").strip()
                if on_step:
                    on_step(f"Firecrawl: Searching & scraping top pages for '{query[:55]}'...")
                return firecrawl_search(query, limit=5)
        except Exception as fc_err:
            if on_step:
                on_step(f"Firecrawl fallback ({fc_err}); trying direct reader...")

    # 2. Secondary Fallback: Safe Direct HTTP Fetch (with SSRF protection)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }

    if not target_url:
        query = (task or "").strip()
        if on_step:
            on_step(f"Searching web for: {query[:60]}...")
        encoded_q = quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = client.get(search_url)
            text = _clean_html_to_readable_text(resp.text)
            return (
                f"Search Results for '{query}':\n\n{text[:15000]}",
                f"https://duckduckgo.com/?q={encoded_q}",
            )

    if not is_safe_public_url(target_url):
        raise RuntimeError(f"Blocked access to private or unsafe URL: {target_url}")

    if on_step:
        on_step(f"Navigating to {target_url}...")

    with httpx.Client(timeout=25, follow_redirects=True, headers=headers) as client:
        response = client.get(target_url)
        response.raise_for_status()
        if on_step:
            on_step(f"Extracting content and code blocks from {target_url}...")
        readable = _clean_html_to_readable_text(response.text)
        return (
            f"Source URL: {str(response.url)}\n\nExtracted Page Content:\n{readable[:18000]}",
            str(response.url),
        )

def browser_result_text(run_data: dict) -> str:
    result = run_data.get("result")
    if isinstance(result, str):
        return result.strip()
    if result not in (None, {}, []):
        return json.dumps(result, ensure_ascii=False, indent=2)
    cause = run_data.get("cause")
    if isinstance(cause, dict) and cause.get("message"):
        return str(cause["message"])
    return "Browser task completed."

def refresh_browser_record(database, browser_run: BrowserRun, run_data: dict):
    browser_run.provider_run_id = run_data.get("runId") or browser_run.provider_run_id
    browser_run.session_id = run_data.get("sessionId") or browser_run.session_id
    browser_run.status = str(run_data.get("status") or browser_run.status).lower()
    if run_data.get("result"):
        browser_run.result = browser_result_text(run_data)
    cause = run_data.get("cause")
    if isinstance(cause, dict) and cause.get("message"):
        browser_run.error = str(cause["message"])
    if browser_run.session_id and not browser_run.preview_url:
        with suppress(Exception):
            live_urls = get_browser_live_urls(browser_run.session_id)
            browser_run.preview_url = live_urls.get("debuggerFullscreenUrl")
    browser_run.updated_at = datetime.now(UTC)
    database.commit()
    database.refresh(browser_run)
    return browser_run


def browser_response(browser_run: BrowserRun):
    return BrowserRunResponse(
        id=browser_run.id,
        status=browser_run.status,
        preview_url=browser_run.preview_url,
        result=browser_run.result,
        error=browser_run.error,
        created_at=browser_run.created_at,
        updated_at=browser_run.updated_at,
    )


def create_browser_record(
    database,
    user_id: str,
    task: str,
    conversation_id=None,
    task_id=None,
):
    initial_url = _extract_first_url(task)
    browser_run = BrowserRun(
        id=str(uuid4()),
        user_id=user_id,
        conversation_id=conversation_id,
        task_id=task_id,
        provider_run_id=None,
        status="running",
        preview_url=initial_url,
    )
    database.add(browser_run)
    database.commit()
    database.refresh(browser_run)

    if browserbase_is_configured():
        try:
            run_data = create_browser_run(task)
            provider_run_id = run_data.get("runId")
            if provider_run_id:
                return refresh_browser_record(database, browser_run, run_data)
        except Exception:
            pass

    return browser_run


def wait_for_browser_task(
    database,
    browser_run: BrowserRun,
    on_update: Callable[[BrowserRun], None] | None = None,
    cancel_event: Event | None = None,
):
    if not browser_run.provider_run_id:
        content, final_url = _fallback_direct_web_fetch(browser_run.preview_url or "")
        browser_run.status = "completed"
        browser_run.result = content
        if final_url:
            browser_run.preview_url = final_url
        browser_run.updated_at = datetime.now(UTC)
        database.commit()
        if on_update:
            on_update(browser_run)
        return content

    deadline = time.monotonic() + 300
    while True:
        if cancel_event and cancel_event.is_set():
            try:
                refresh_browser_record(
                    database,
                    browser_run,
                    stop_browser_run(browser_run.provider_run_id),
                )
            except Exception:
                browser_run.status = "stopped"
                database.commit()
            raise RuntimeError("Browser task cancelled")
        status = browser_run.status.upper()
        if status == "COMPLETED":
            return browser_run.result or "Browser task completed."
        if status == "PAUSED":
            return None
        if status in BROWSERBASE_TERMINAL_STATUSES:
            raise RuntimeError(browser_run.error or "Browser task failed")
        if time.monotonic() >= deadline:
            raise TimeoutError("Browser task timed out")
        time.sleep(2)
        refresh_browser_record(
            database,
            browser_run,
            get_browser_run(browser_run.provider_run_id),
        )
        if on_update:
            on_update(browser_run)


def wait_for_browser_agent_task(
    browser_run_id: str,
    task_text: str = "",
    on_update: Callable[[BrowserRun], None] | None = None,
    on_step_message: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
):
    with SessionLocal() as database:
        browser_run = database.get(BrowserRun, browser_run_id)
        if browser_run is None:
            raise RuntimeError("Browser task was not found")
        has_provider = bool(browser_run.provider_run_id)
        fallback_target = task_text or browser_run.preview_url or ""

    if not has_provider:
        content, final_url = _fallback_direct_web_fetch(
            fallback_target,
            on_step=on_step_message,
        )
        with SessionLocal() as database:
            browser_run = database.get(BrowserRun, browser_run_id)
            if browser_run:
                browser_run.status = "completed"
                browser_run.result = content
                if final_url:
                    browser_run.preview_url = final_url
                browser_run.updated_at = datetime.now(UTC)
                database.commit()
                database.refresh(browser_run)
                if on_update:
                    on_update(browser_run)
        return content

    deadline = time.monotonic() + 300
    seen_message_ids: set[str] = set()

    while True:
        with SessionLocal() as database:
            browser_run = database.get(BrowserRun, browser_run_id)
            if browser_run is None:
                raise RuntimeError("Browser task was not found")
            provider_run_id = browser_run.provider_run_id
            status = browser_run.status.upper()
            if status == "COMPLETED":
                return browser_run.result or "Browser task completed."
            if status == "PAUSED":
                return None
            if status in BROWSERBASE_TERMINAL_STATUSES:
                raise RuntimeError(browser_run.error or "Browser task failed")

        if cancel_event and cancel_event.is_set():
            try:
                run_data = stop_browser_run(provider_run_id)
                with SessionLocal() as database:
                    browser_run = database.get(BrowserRun, browser_run_id)
                    if browser_run:
                        refresh_browser_record(database, browser_run, run_data)
            except Exception:
                with SessionLocal() as database:
                    browser_run = database.get(BrowserRun, browser_run_id)
                    if browser_run:
                        browser_run.status = "stopped"
                        database.commit()
            raise RuntimeError("Browser task cancelled")

        if time.monotonic() >= deadline:
            raise TimeoutError("Browser task timed out")

        time.sleep(2)
        run_data = get_browser_run(provider_run_id)

        if on_step_message and provider_run_id:
            with suppress(Exception):
                msg_payload = get_browser_run_messages(provider_run_id, limit=10)
                items = msg_payload.get("messages") or msg_payload.get("data") or []
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        msg_id = str(
                            item.get("id")
                            or item.get("timestamp")
                            or item.get("text")
                            or ""
                        )
                        text = str(
                            item.get("text")
                            or item.get("message")
                            or item.get("action")
                            or ""
                        ).strip()
                        if msg_id and msg_id not in seen_message_ids and text:
                            seen_message_ids.add(msg_id)
                            on_step_message(text[:140])

        with SessionLocal() as database:
            browser_run = database.get(BrowserRun, browser_run_id)
            if browser_run is None:
                raise RuntimeError("Browser task was not found")
            refresh_browser_record(database, browser_run, run_data)
            if on_update:
                on_update(browser_run)


def run_browser_for_agent(
    user_id: str,
    conversation_id: str,
    task: str,
    emit_event: Callable[[dict], None],
    cancel_event: Event,
):
    with SessionLocal() as database:
        browser_run = create_browser_record(
            database,
            user_id,
            task,
            conversation_id=conversation_id,
        )
        browser_run_id = browser_run.id
    last_marker = None

    def emit_browser(run: BrowserRun):
        nonlocal last_marker
        marker = (run.status, run.preview_url, run.result, run.error)
        if marker == last_marker:
            return
        last_marker = marker
        emit_event(
            {
                "type": "browser",
                "browser": browser_response(run).model_dump(mode="json"),
            }
        )

    def emit_step(step_text: str):
        emit_event({"type": "status", "message": f"Browser: {step_text}"})

    emit_browser(browser_run)

    try:
        result = wait_for_browser_agent_task(
            browser_run_id,
            task_text=task,
            on_update=emit_browser,
            on_step_message=emit_step,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        emit_step(f"Switching to direct web reader ({exc})...")
        try:
            content, final_url = _fallback_direct_web_fetch(task, on_step=emit_step)
            final_status = "completed"
        except Exception as fetch_err:
            content = f"Could not access {task}: {fetch_err}. Try an alternative source."
            final_url = _extract_first_url(task)
            final_status = "completed"

        with SessionLocal() as database:
            browser_run = database.get(BrowserRun, browser_run_id)
            if browser_run:
                browser_run.status = final_status
                browser_run.result = content
                if final_url:
                    browser_run.preview_url = final_url
                browser_run.updated_at = datetime.now(UTC)
                database.commit()
                database.refresh(browser_run)
                emit_browser(browser_run)
        return content

    if result is None:
        emit_event(
            {
                "type": "approval_required",
                "run_id": browser_run_id,
                "message": "The browser needs your input. Open the live browser, finish the requested step, then tap Resume.",
            }
        )
        return (
            "The browser session is currently PAUSED waiting for the user to log in, "
            "verify, or approve inside the live browser view. Tell the user what step "
            "is needed in the live browser and that you will continue automatically once they tap Resume."
        )
    return result