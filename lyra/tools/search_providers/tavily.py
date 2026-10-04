"""Optional free-tier Tavily search provider adapter for LYRA."""

import asyncio
import json
import socket
from typing import Any
import urllib.error
import urllib.request

from lyra.config.settings import load_settings
from lyra.core.exceptions import (
    ToolError,
    ToolExecutionError,
    ToolNetworkError,
    ToolRateLimitError,
    ToolTimeoutError,
)
from lyra.observability.logging import get_logger
from lyra.tools.sanitizer import sanitize_external_text
from lyra.tools.search_providers.base import SearchProvider, SearchResult

TAVILY_API_URL = "https://api.tavily.com/search"


class TavilySearchProvider(SearchProvider):
    """Search provider using Tavily Search API (optional free tier)."""

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 10.0) -> None:
        settings = load_settings()
        self._api_key = api_key if api_key is not None else settings.tavily_api_key
        self.timeout_seconds = timeout_seconds
        self._logger = get_logger("search.tavily")

    @property
    def name(self) -> str:
        return "tavily"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _execute_search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute Tavily search query over HTTP."""
        if not self.is_available:
            raise ToolExecutionError("TavilySearchProvider is not configured with an API key.")

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LYRA-Personal-AI-OS/1.0",
        }
        req = urllib.request.Request(TAVILY_API_URL, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
                response_json = json.loads(body)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            if http_err.code == 429:
                raise ToolRateLimitError("Tavily search rate limit exceeded (HTTP 429)") from http_err
            if http_err.code in (401, 403):
                raise ToolExecutionError(f"Tavily authentication failed (HTTP {http_err.code}): {raw_err}") from http_err
            raise ToolNetworkError(f"Tavily API HTTP {http_err.code}: {raw_err}") from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ToolTimeoutError(f"Tavily request timed out: {net_err}") from net_err
        except json.JSONDecodeError as json_err:
            raise ToolExecutionError(f"Tavily returned invalid JSON: {json_err}") from json_err

        results_list = response_json.get("results", [])
        results: list[SearchResult] = []
        for item in results_list[:max_results]:
            title = sanitize_external_text(item.get("title", ""))
            url = item.get("url", "").strip()
            content = sanitize_external_text(item.get("content", ""))
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=content))

        return results

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        clean_q = query.strip()
        if not clean_q:
            return []
        return await asyncio.to_thread(self._execute_search, clean_q, max_results)
