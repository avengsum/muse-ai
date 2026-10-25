import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")


def _get_e2b_api_key() -> str:
    raw = (os.getenv("E2B_API_KEY") or "").strip().strip("'\"")
    if "E2B_API_KEY=" in raw:
        raw = raw.split("E2B_API_KEY=", 1)[1].strip()
    return raw


def e2b_is_configured() -> bool:
    key = _get_e2b_api_key()
    return bool(key and not key.lower().startswith("your_") and "<" not in key)


def execute_python_in_sandbox(
    code: str,
    title: str = "Python Sandbox",
    expose_port: int | None = None,
    emit_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    clean_code = (code or "").strip()
    clean_title = (title or "Python Sandbox").strip()[:80]

    if not clean_code:
        raise ValueError("Python code cannot be empty")

    api_key = _get_e2b_api_key()
    if not api_key:
        raise RuntimeError(
            "E2B_API_KEY is missing. Add E2B_API_KEY to your .env file."
        )

    if emit_event:
        emit_event(
            {
                "type": "sandbox",
                "sandbox": {
                    "title": clean_title,
                    "status": "running",
                    "code": clean_code,
                    "stdout": "",
                    "stderr": "",
                    "error": None,
                    "charts": [],
                    "preview_url": None,
                },
            }
        )

    sbx = None
    try:
        from e2b_code_interpreter import Sandbox

        sandbox_timeout = 300 if expose_port else 90

        # e2b-code-interpreter v2.x uses Sandbox.create(); v1.x uses Sandbox()
        if hasattr(Sandbox, "create") and callable(getattr(Sandbox, "create")):
            sbx = Sandbox.create(api_key=api_key, timeout=sandbox_timeout)
        else:
            sbx = Sandbox(api_key=api_key, timeout=sandbox_timeout)

        execution = sbx.run_code(clean_code)

        stdout_list = getattr(execution.logs, "stdout", []) if getattr(execution, "logs", None) else []
        stderr_list = getattr(execution.logs, "stderr", []) if getattr(execution, "logs", None) else []
        stdout_text = "\n".join(str(line) for line in stdout_list).strip()
        stderr_text = "\n".join(str(line) for line in stderr_list).strip()

        error_text = None
        if getattr(execution, "error", None):
            err = execution.error
            error_text = (
                f"{getattr(err, 'name', 'Error')}: {getattr(err, 'value', '')}\n"
                f"{getattr(err, 'traceback', '')}"
            ).strip()

        charts: list[str] = []
        text_results: list[str] = []

        for item in getattr(execution, "results", None) or []:
            png_data = getattr(item, "png", None)
            if png_data:
                charts.append(png_data)
            text_val = getattr(item, "text", None)
            if text_val:
                text_results.append(str(text_val))

        if not stdout_text and getattr(execution, "text", None):
            stdout_text = str(execution.text).strip()
        elif not stdout_text and text_results:
            stdout_text = "\n".join(text_results).strip()

        preview_url = None
        if expose_port and 1 <= int(expose_port) <= 65535:
            host = sbx.get_host(int(expose_port))
            preview_url = f"https://{host}"

        payload = {
            "title": clean_title,
            "status": "failed" if error_text else "completed",
            "code": clean_code,
            "stdout": stdout_text[:8000],
            "stderr": stderr_text[:4000],
            "error": error_text[:4000] if error_text else None,
            "charts": charts[:3],
            "preview_url": preview_url,
        }

        if emit_event:
            emit_event({"type": "sandbox", "sandbox": payload})

        return payload

    except Exception as exc:
        # CRITICAL: Always emit a terminal 'failed' state so the UI spinner stops!
        failed_payload = {
            "title": clean_title,
            "status": "failed",
            "code": clean_code,
            "stdout": "",
            "stderr": "",
            "error": f"Sandbox error: {exc}",
            "charts": [],
            "preview_url": None,
        }
        if emit_event:
            emit_event({"type": "sandbox", "sandbox": failed_payload})
        return failed_payload

    finally:
        if sbx is not None and not expose_port:
            try:
                sbx.kill()
            except Exception:
                pass