import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")


BROWSERBASE_BASE_URL = "https://api.browserbase.com"
BROWSERBASE_TERMINAL_STATUSES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "STOPPED",
        "TIMED_OUT",
    }
)
BROWSERBASE_ACTIVE_STATUSES = frozenset(
    {
        "PENDING",
        "RUNNING",
        "PAUSED",
    }
)
DEFAULT_PAUSE_WHEN = (
    "Pause when login, verification, payment, purchase, deletion, "
    "message sending, form submission, or user approval is required."
)


class BrowserbaseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        details: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def browserbase_is_configured() -> bool:
    return bool(os.getenv("BROWSERBASE_API_KEY"))


def get_browserbase_client() -> "BrowserbaseClient":
    return BrowserbaseClient()


class BrowserbaseClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        raw_key = (
            api_key
            or os.getenv("BROWSERBASE_API_KEY")
            or ""
        ).strip().strip("'\"")
        if "BROWSERBASE_API_KEY=" in raw_key:
            raw_key = raw_key.split("BROWSERBASE_API_KEY=", 1)[1].strip()
        self.api_key = raw_key
        self.base_url = (
            base_url
            or os.getenv("BROWSERBASE_BASE_URL")
            or BROWSERBASE_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        self.transport = transport

        if not self.api_key:
            raise BrowserbaseError(
                "BROWSERBASE_API_KEY is missing",
                status_code=503,
            )

    def create_run(
        self,
        task: str,
        *,
        agent_id: str | None = None,
        result_schema: Mapping[str, Any] | None = None,
        browser_settings: Mapping[str, Any] | None = None,
        variables: Mapping[str, Any] | None = None,
        pause_when: str | None = DEFAULT_PAUSE_WHEN,
    ) -> dict[str, Any]:
        normalized_task = task.strip()

        if not normalized_task:
            raise ValueError("Browser task cannot be empty")

        payload: dict[str, Any] = {
            "task": normalized_task,
        }

        selected_agent_id = (
            agent_id
            or os.getenv("BROWSERBASE_AGENT_ID")
            or ""
        ).strip().strip("'\"")

        if (
            selected_agent_id
            and not selected_agent_id.lower().startswith("your_")
            and "<" not in selected_agent_id
        ):
            payload["agentId"] = selected_agent_id

        if result_schema is not None:
            payload["resultSchema"] = dict(result_schema)

        if browser_settings is not None:
            payload["browserSettings"] = dict(browser_settings)

        if variables is not None:
            payload["variables"] = dict(variables)

        if pause_when and pause_when.strip():
            payload["pauseWhen"] = pause_when.strip()

        return self._request(
            "POST",
            "/v1/agents/runs",
            json_body=payload,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/agents/runs/{self._identifier(run_id)}",
        )

    def get_run_messages(
        self,
        run_id: str,
        *,
        since: str | None = None,
        limit: int = 20,
        include_all: bool = False,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ValueError("Message limit must be between 1 and 100")

        params: dict[str, Any] = {
            "limit": limit,
            "all": str(include_all).lower(),
        }

        if since:
            params["since"] = since

        return self._request(
            "GET",
            (
                f"/v1/agents/runs/"
                f"{self._identifier(run_id)}/messages"
            ),
            params=params,
        )

    def resume_run(
        self,
        run_id: str,
        task: str,
        *,
        variables: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_task = task.strip()

        if not normalized_task:
            raise ValueError("Resume task cannot be empty")

        payload: dict[str, Any] = {
            "task": normalized_task,
        }

        if variables is not None:
            payload["variables"] = dict(variables)

        return self._request(
            "POST",
            f"/v1/agents/runs/{self._identifier(run_id)}/resume",
            json_body=payload,
        )

    def stop_run(self, run_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/agents/runs/{self._identifier(run_id)}/stop",
        )

    def get_live_urls(
        self,
        session_id: str,
        *,
        expires_in: int = 900,
    ) -> dict[str, Any]:
        if expires_in < 60 or expires_in > 21600:
            raise ValueError(
                "Live URL expiry must be between 60 and 21600 seconds"
            )

        return self._request(
            "GET",
            f"/v1/sessions/{self._identifier(session_id)}/debug",
            params={
                "expiresIn": expires_in,
            },
        )

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout: float = 300,
        poll_interval: float = 2,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if timeout <= 0:
            raise ValueError("Timeout must be greater than zero")

        if poll_interval <= 0:
            raise ValueError("Poll interval must be greater than zero")

        deadline = time.monotonic() + timeout
        previous_marker: tuple[Any, ...] | None = None

        while True:
            run = self.get_run(run_id)
            status = str(run.get("status") or "").upper()

            marker = (
                status,
                run.get("updatedAt"),
                run.get("sessionId"),
            )

            if on_update and marker != previous_marker:
                on_update(run)

            previous_marker = marker

            if status in BROWSERBASE_TERMINAL_STATUSES:
                return run

            if status == "PAUSED":
                return run

            if time.monotonic() >= deadline:
                raise BrowserbaseError(
                    "Browserbase run timed out while waiting",
                    status_code=504,
                    details={
                        "run_id": run_id,
                        "status": status,
                    },
                )

            time.sleep(poll_interval)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers={
                        "X-BB-API-Key": self.api_key,
                        "Accept": "application/json",
                    },
                    json=(
                        dict(json_body)
                        if json_body is not None
                        else None
                    ),
                    params=(
                        dict(params)
                        if params is not None
                        else None
                    ),
                )
        except httpx.TimeoutException as error:
            raise BrowserbaseError(
                "Browserbase request timed out",
                status_code=504,
            ) from error
        except httpx.RequestError as error:
            raise BrowserbaseError(
                "Browserbase is unavailable",
                status_code=503,
            ) from error

        data = self._response_data(response)

        if response.is_error:
            raise BrowserbaseError(
                self._error_message(data, response.status_code),
                status_code=response.status_code,
                details=data,
            )

        if not isinstance(data, dict):
            raise BrowserbaseError(
                "Browserbase returned an invalid response",
                details=data,
            )

        return data

    @staticmethod
    def _identifier(value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Browserbase identifier cannot be empty")

        if not all(
            character.isalnum() or character in "-_"
            for character in normalized
        ):
            raise ValueError("Browserbase identifier is invalid")

        return normalized

    @staticmethod
    def _response_data(response: httpx.Response) -> Any:
        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError:
            return {
                "message": response.text[:1000],
            }

    @staticmethod
    def _error_message(
        data: Any,
        status_code: int,
    ) -> str:
        if isinstance(data, dict):
            cause = data.get("cause")

            if isinstance(cause, dict) and cause.get("message"):
                return str(cause["message"])

            for key in ("message", "error", "detail"):
                if data.get(key):
                    return str(data[key])

        return f"Browserbase request failed with status {status_code}"


def create_browser_run(
    task: str,
    **options: Any,
) -> dict[str, Any]:
    return get_browserbase_client().create_run(
        task,
        **options,
    )


def get_browser_run(run_id: str) -> dict[str, Any]:
    return get_browserbase_client().get_run(run_id)


def get_browser_run_messages(
    run_id: str,
    **options: Any,
) -> dict[str, Any]:
    return get_browserbase_client().get_run_messages(
        run_id,
        **options,
    )


def resume_browser_run(
    run_id: str,
    task: str,
    **options: Any,
) -> dict[str, Any]:
    return get_browserbase_client().resume_run(
        run_id,
        task,
        **options,
    )


def stop_browser_run(run_id: str) -> dict[str, Any]:
    return get_browserbase_client().stop_run(run_id)


def wait_for_browser_run(
    run_id: str,
    **options: Any,
) -> dict[str, Any]:
    return get_browserbase_client().wait_for_run(
        run_id,
        **options,
    )


def get_browser_live_urls(
    session_id: str,
    *,
    expires_in: int = 900,
) -> dict[str, Any]:
    return get_browserbase_client().get_live_urls(
        session_id,
        expires_in=expires_in,
    )


def get_browser_event(
    run: Mapping[str, Any],
    live_urls: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pages = (
        live_urls.get("pages", [])
        if live_urls
        else []
    )
    current_page = (
        pages[-1]
        if isinstance(pages, list) and pages
        else {}
    )

    return {
        "type": "browser",
        "run_id": run.get("runId"),
        "preview_url": (
            live_urls.get("debuggerFullscreenUrl")
            if live_urls
            else None
        ),
        "current_url": (
            current_page.get("url")
            if isinstance(current_page, dict)
            else None
        ),
        "status": str(run.get("status") or "PENDING").upper(),
    }
