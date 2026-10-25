import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ..auth import CurrentUser, get_current_user
from ..browser_runtime import browser_response, create_browser_record, refresh_browser_record
from ..browser_service import BROWSERBASE_TERMINAL_STATUSES, BrowserbaseError, get_browser_run, resume_browser_run, stop_browser_run
from ..callback_urls import validate_callback_url
from ..composio_service import authorize_tool, composio_is_configured, disconnect_account, get_tool_states
from ..conversation_service import ensure_conversation_access, get_agent_session
from ..database import SessionLocal
from ..inngest_service import queue_browser_resumed_event
from ..models import BrowserRun, PushToken, SwiggyConnection, SwiggyOAuthState, TaskRun, Tool
from ..runtime_utils import as_utc, log_internal_error, public_error
from ..schemas import BrowserRunCreate, BrowserRunResponse, BrowserRunResume, PushTokenCreate, SwiggyOAuthStartResponse, ToolConnectRequest, ToolConnectResponse, ToolResponse
from ..swiggy_runtime import swiggy_status
from ..swiggy_service import SwiggyError, append_query, build_authorization_url, create_pkce_pair, decrypt_secret, encrypt_secret, exchange_authorization_code, register_dynamic_client, swiggy_is_configured


logger = logging.getLogger("muse_ai")
router = APIRouter()


def make_tool_response(tool: Tool, state: dict):
    return ToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        icon=tool.icon,
        color=tool.color,
        connected=state["connected"],
        account=state["account"],
    )


@router.get("/api/swiggy/oauth/start", response_model=SwiggyOAuthStartResponse)
def start_swiggy_oauth(
    callback_url: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    app_callback_url = validate_callback_url(callback_url)
    if not app_callback_url:
        raise HTTPException(status_code=400, detail="A callback URL is required")
    if not swiggy_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Swiggy ordering is not configured on this backend",
        )

    try:
        verifier, challenge = create_pkce_pair()
        client_id = register_dynamic_client()
    except SwiggyError as error:
        raise HTTPException(
            status_code=error.status_code or 502,
            detail=str(error),
        ) from error

    state_value = secrets.token_urlsafe(32)
    with SessionLocal() as database:
        database.add(
            SwiggyOAuthState(
                state=state_value,
                user_id=current_user.id,
                code_verifier_encrypted=encrypt_secret(verifier),
                client_id=client_id,
                app_callback_url=app_callback_url,
            )
        )
        database.commit()

    return SwiggyOAuthStartResponse(
        authorization_url=build_authorization_url(
            state_value,
            challenge,
            client_id,
        ),
        callback_url=app_callback_url,
    )


@router.get("/api/swiggy/oauth/callback")
def finish_swiggy_oauth(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if not state:
        raise HTTPException(status_code=400, detail="Swiggy OAuth state is missing")

    with SessionLocal() as database:
        oauth_state = database.get(SwiggyOAuthState, state)
        if oauth_state is None or oauth_state.used:
            raise HTTPException(status_code=400, detail="Swiggy OAuth state is invalid")

        app_callback_url = oauth_state.app_callback_url
        if datetime.now(UTC) - as_utc(oauth_state.created_at) > timedelta(minutes=15):
            oauth_state.used = True
            database.commit()
            return RedirectResponse(append_query(app_callback_url, status="expired"))

        oauth_state.used = True
        database.commit()
        verifier = decrypt_secret(oauth_state.code_verifier_encrypted)

        if error or not code:
            return RedirectResponse(
                append_query(app_callback_url, status="cancelled")
            )

        try:
            token_data = exchange_authorization_code(
                code,
                verifier,
                oauth_state.client_id,
            )
        except SwiggyError:
            logger.exception("Swiggy OAuth token exchange failed")
            return RedirectResponse(append_query(app_callback_url, status="error"))

        expires_in = int(token_data.get("expires_in") or 432000)
        connection = database.get(SwiggyConnection, oauth_state.user_id)
        if connection is None:
            connection = SwiggyConnection(
                user_id=oauth_state.user_id,
                access_token_encrypted=encrypt_secret(str(token_data["access_token"])),
                expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
                scope=str(token_data.get("scope") or "mcp:tools"),
            )
            database.add(connection)
        else:
            connection.access_token_encrypted = encrypt_secret(
                str(token_data["access_token"])
            )
            connection.expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            connection.scope = str(token_data.get("scope") or "mcp:tools")
            connection.updated_at = datetime.now(UTC)
        database.commit()

    return RedirectResponse(append_query(app_callback_url, status="success"))


@router.get("/api/swiggy/status")
def get_swiggy_status(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        return swiggy_status(database, current_user.id)


@router.post("/api/swiggy/disconnect")
def disconnect_swiggy(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        connection = database.get(SwiggyConnection, current_user.id)
        if connection:
            database.delete(connection)
            database.commit()
    return {"success": True}


@router.post("/api/push-tokens")
def register_push_token(
    payload: PushTokenCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    token = payload.token.strip()
    if not token or len(token) > 255:
        raise HTTPException(status_code=422, detail="Push token is invalid")

    with SessionLocal() as database:
        device = database.scalar(select(PushToken).where(PushToken.token == token))
        if device is None:
            database.add(
                PushToken(
                    user_id=current_user.id,
                    token=token,
                    platform=payload.platform[:20],
                )
            )
        else:
            device.user_id = current_user.id
            device.platform = payload.platform[:20]
            device.updated_at = datetime.now(UTC)
        database.commit()
    return {"success": True}


@router.get("/api/tools", response_model=list[ToolResponse])
def get_tools(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        tools = database.scalars(select(Tool).order_by(Tool.name)).all()

        if not composio_is_configured():
            states = {
                tool.id: {"connected": False, "account": None, "account_id": None}
                for tool in tools
            }
        else:
            try:
                states = get_tool_states(get_agent_session(database, current_user.id))
            except Exception as error:
                error_id = log_internal_error(
                    "Tool connection lookup failed",
                    user_id=current_user.id,
                )
                raise HTTPException(
                    status_code=502,
                    detail=public_error(
                        "Could not load tool connections.",
                        error_id,
                    ),
                ) from error

        return [make_tool_response(tool, states[tool.id]) for tool in tools]


@router.post("/api/tools/{tool_id}/connect", response_model=ToolConnectResponse)
def connect_tool(tool_id: str, payload: ToolConnectRequest, current_user: CurrentUser = Depends(get_current_user)):
    callback_url = validate_callback_url(payload.callback_url)

    with SessionLocal() as database:
        tool = database.get(Tool, tool_id)

        if tool is None:
            raise HTTPException(status_code=404, detail="Tool not found")

        try:
            session = get_agent_session(database, current_user.id)

            if session is None:
                raise RuntimeError("COMPOSIO_API_KEY is missing")

            connection = authorize_tool(session, tool_id, callback_url)
        except ValueError as error:
            error_id = log_internal_error(
                "Tool connection request was rejected",
                tool_id=tool_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=400,
                detail=public_error(
                    "Could not start the tool connection.",
                    error_id,
                ),
            ) from error
        except Exception as error:
            error_id = log_internal_error(
                "Tool connection failed",
                tool_id=tool_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=502,
                detail=public_error(
                    "Could not start the tool connection.",
                    error_id,
                ),
            ) from error

        return ToolConnectResponse(**connection)


@router.post("/api/tools/{tool_id}/disconnect", response_model=ToolResponse)
def disconnect_tool(tool_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        tool = database.get(Tool, tool_id)

        if tool is None:
            raise HTTPException(status_code=404, detail="Tool not found")

        try:
            session = get_agent_session(database, current_user.id)
            states = get_tool_states(session)
            account_id = states[tool_id]["account_id"]

            if account_id:
                disconnect_account(account_id)
        except Exception as error:
            error_id = log_internal_error(
                "Tool disconnect failed",
                tool_id=tool_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=502,
                detail=public_error(
                    "Could not disconnect the tool.",
                    error_id,
                ),
            ) from error

        return make_tool_response(
            tool,
            {"connected": False, "account": None, "account_id": None},
        )


@router.post("/api/browser/runs", response_model=BrowserRunResponse, status_code=201)
def start_browser_run(payload: BrowserRunCreate, current_user: CurrentUser = Depends(get_current_user)):
    if not payload.task.strip():
        raise HTTPException(status_code=422, detail="Browser task cannot be empty")

    with SessionLocal() as database:
        if payload.conversation_id:
            ensure_conversation_access(database, payload.conversation_id, current_user.id)

        try:
            run = create_browser_record(
                database,
                current_user.id,
                payload.task,
                conversation_id=payload.conversation_id,
            )
        except BrowserbaseError as error:
            error_id = log_internal_error(
                "Browser run creation failed",
                conversation_id=payload.conversation_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=error.status_code,
                detail=public_error(
                    "Could not start the browser task.",
                    error_id,
                ),
            ) from error

        return browser_response(run)


def get_owned_browser_run(database, run_id: str, user_id: str):
    run = database.get(BrowserRun, run_id)

    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=404, detail="Browser run not found")

    return run


@router.get("/api/browser/runs/{run_id}", response_model=BrowserRunResponse)
def browser_run_status(run_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        run = get_owned_browser_run(database, run_id, current_user.id)

        if run.provider_run_id and run.status.upper() not in BROWSERBASE_TERMINAL_STATUSES:
            try:
                refresh_browser_record(database, run, get_browser_run(run.provider_run_id))
            except BrowserbaseError as error:
                error_id = log_internal_error(
                    "Browser status refresh failed",
                    browser_run_id=run.id,
                    user_id=current_user.id,
                )
                raise HTTPException(
                    status_code=error.status_code,
                    detail=public_error(
                        "Could not refresh the browser task.",
                        error_id,
                    ),
                ) from error

        return browser_response(run)


def _continue_chat_after_browser_resume(browser_run_id: str, user_id: str, conversation_id: str):
    import asyncio
    from uuid import uuid4
    from ..agent_run_service import create_agent_run_record, execute_agent_run
    from ..browser_runtime import wait_for_browser_agent_task
    from ..inngest_service import inngest_is_configured, queue_agent_run_event

    try:
        result_text = wait_for_browser_agent_task(browser_run_id)
    except Exception as exc:
        result_text = f"Browser session ended with error: {exc}"

    if not result_text:
        return

    follow_up_run_id = str(uuid4())
    dispatch_mode = "inngest" if inngest_is_configured() else "direct"
    resume_prompt = (
        f"[System: The user resumed the paused browser session (ID: {browser_run_id}). "
        f"Browser output: {result_text[:4000]}. Continue and complete the user's original request.]"
    )

    with SessionLocal() as database:
        create_agent_run_record(
            database,
            run_id=follow_up_run_id,
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=resume_prompt,
            timezone="UTC",
            callback_url=None,
            dispatch_mode=dispatch_mode,
        )

    if dispatch_mode == "inngest":
        try:
            queue_agent_run_event(follow_up_run_id)
            return
        except Exception:
            pass
    asyncio.run(execute_agent_run(follow_up_run_id))


@router.post("/api/browser/runs/{run_id}/resume", response_model=BrowserRunResponse)
def continue_browser_run(
    run_id: str,
    payload: BrowserRunResume,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="Resume message cannot be empty")

    with SessionLocal() as database:
        run = get_owned_browser_run(database, run_id, current_user.id)

        try:
            run_data = resume_browser_run(run.provider_run_id, payload.message)
            refresh_browser_record(database, run, run_data)
        except BrowserbaseError as error:
            error_id = log_internal_error(
                "Browser resume failed",
                browser_run_id=run.id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=error.status_code,
                detail=public_error(
                    "Could not resume the browser task.",
                    error_id,
                ),
            ) from error

        if run.task_id:
            task_run = database.scalar(
                select(TaskRun)
                .where(TaskRun.browser_run_id == run.id)
                .order_by(TaskRun.created_at.desc())
                .limit(1)
            )

            if task_run:
                task_run.status = "running"
                task_run.error = None
                database.commit()
                queue_browser_resumed_event(run.id)
        elif run.conversation_id:
            import threading

            threading.Thread(
                target=_continue_chat_after_browser_resume,
                args=(run.id, current_user.id, run.conversation_id),
                daemon=True,
            ).start()

        return browser_response(run)

@router.post("/api/browser/runs/{run_id}/stop", response_model=BrowserRunResponse)
def end_browser_run(run_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        run = get_owned_browser_run(database, run_id, current_user.id)

        try:
            run_data = stop_browser_run(run.provider_run_id)
            refresh_browser_record(database, run, run_data)
        except BrowserbaseError as error:
            error_id = log_internal_error(
                "Browser stop failed",
                browser_run_id=run.id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=error.status_code,
                detail=public_error(
                    "Could not stop the browser task.",
                    error_id,
                ),
            ) from error

        return browser_response(run)
