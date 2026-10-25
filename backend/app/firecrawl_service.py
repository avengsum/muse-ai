import ipaddress
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")

FIRECRAWL_BASE_URL = (
    os.getenv("FIRECRAWL_BASE_URL") or "https://api.firecrawl.dev/v1"
).rstrip("/")


class FirecrawlError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _get_firecrawl_key() -> str:
    raw = (os.getenv("FIRECRAWL_API_KEY") or "").strip().strip("'\"")
    if "FIRECRAWL_API_KEY=" in raw:
        raw = raw.split("FIRECRAWL_API_KEY=", 1)[1].strip()
    return raw


def firecrawl_is_configured() -> bool:
    key = _get_firecrawl_key()
    return bool(key and not key.lower().startswith("your_") and "<" not in key)


def is_safe_public_url(url: str) -> bool:
    """Blocks SSRF attempts against localhost, private VPC IPs, and cloud metadata endpoints."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        hostname = parsed.hostname.lower()
        if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or hostname.endswith(".local"):
            return False
        for info in socket.getaddrinfo(hostname, None):
            ip_str = info[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
            ):
                return False
        return True
    except Exception:
        return False


def firecrawl_scrape_url(
    url: str,
    *,
    only_main_content: bool = True,
    timeout: float = 30.0,
) -> tuple[str, str]:
    """
    Scrapes a single URL into clean, LLM-ready Markdown via Firecrawl /v1/scrape.
    Returns (formatted_markdown, final_source_url).
    """
    api_key = _get_firecrawl_key()
    if not api_key:
        raise FirecrawlError("FIRECRAWL_API_KEY is not configured", 503)

    if not is_safe_public_url(url):
        raise FirecrawlError(f"Blocked unsafe or private URL: {url}", 400)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": only_main_content,
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{FIRECRAWL_BASE_URL}/scrape",
            headers=headers,
            json=payload,
        )

    if response.is_error:
        raise FirecrawlError(
            f"Firecrawl scrape failed ({response.status_code}): {response.text[:300]}",
            response.status_code,
        )

    body: dict[str, Any] = response.json()
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    markdown = (data.get("markdown") or "").strip()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    title = (metadata.get("title") or "").strip()
    source_url = str(metadata.get("sourceURL") or url)

    if not markdown:
        raise FirecrawlError(f"Firecrawl returned empty content for {url}")

    header = f"# {title}\nSource URL: {source_url}\n\n" if title else f"Source URL: {source_url}\n\n"
    return f"{header}{markdown[:18000]}", source_url


def firecrawl_search(
    query: str,
    *,
    limit: int = 5,
    scrape_markdown: bool = True,
    timeout: float = 35.0,
) -> tuple[str, str | None]:
    """
    Searches the live web and extracts clean Markdown from the top results in one call via Firecrawl /v1/search.
    Returns (formatted_results_markdown, top_result_url).
    """
    api_key = _get_firecrawl_key()
    if not api_key:
        raise FirecrawlError("FIRECRAWL_API_KEY is not configured", 503)

    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("Search query cannot be empty")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "query": clean_query,
        "limit": max(1, min(limit, 8)),
    }
    if scrape_markdown:
        payload["scrapeOptions"] = {
            "formats": ["markdown"],
            "onlyMainContent": True,
        }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{FIRECRAWL_BASE_URL}/search",
            headers=headers,
            json=payload,
        )

    if response.is_error:
        raise FirecrawlError(
            f"Firecrawl search failed ({response.status_code}): {response.text[:300]}",
            response.status_code,
        )

    body = response.json()
    items = body.get("data") if isinstance(body, dict) else []
    if not isinstance(items, list) or not items:
        raise FirecrawlError(f"No search results found for '{clean_query}'")

    sections: list[str] = [f"### Firecrawl Web Search Results for: '{clean_query}'\n"]
    first_url: str | None = None

    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url and not first_url:
            first_url = url
        title = str(item.get("title") or "Untitled Result").strip()
        desc = str(item.get("description") or "").strip()
        md_snippet = str(item.get("markdown") or "").strip()[:3200]

        block = [f"#### {idx}. {title}", f"URL: {url}"]
        if desc:
            block.append(f"Summary: {desc}")
        if md_snippet:
            block.append(f"Extracted Content:\n{md_snippet}")
        sections.append("\n".join(block))

    return "\n\n---\n\n".join(sections)[:20000], first_url