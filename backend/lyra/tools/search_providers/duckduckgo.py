"""Free, zero-key DuckDuckGo search provider adapter for LYRA."""

import asyncio
from html.parser import HTMLParser
import json
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

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

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_API_URL = "https://api.duckduckgo.com/"


class DuckDuckGoHTMLParser(HTMLParser):
    """Parses search results from DuckDuckGo HTML response."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        classes = attr_dict.get("class", "").split()

        if tag == "a" and "result__a" in classes:
            self._in_title = True
            raw_url = attr_dict.get("href", "")
            self._current_url = self._clean_ddg_url(raw_url)
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif self._in_snippet and tag in ("a", "div", "td", "p"):
            self._in_snippet = False
            # If we have gathered both title and snippet, record result
            if self._current_title and self._current_url:
                title = " ".join("".join(self._current_title).split())
                snippet = " ".join("".join(self._current_snippet).split())
                self.results.append({
                    "title": title,
                    "url": self._current_url,
                    "snippet": snippet,
                })
                self._current_title = []
                self._current_snippet = []
                self._current_url = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    @staticmethod
    def _clean_ddg_url(raw_url: str) -> str:
        """Extract the destination URL from DuckDuckGo redirect links."""
        if not raw_url:
            return ""
        if "uddg=" in raw_url:
            parsed = urllib.parse.urlparse(raw_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            uddg = query_params.get("uddg")
            if uddg and uddg[0]:
                return uddg[0]
        if raw_url.startswith("//"):
            return "https:" + raw_url
        return raw_url


class DuckDuckGoSearchProvider(SearchProvider):
    """Default zero-key search provider using DuckDuckGo."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._logger = get_logger("search.duckduckgo")

    @property
    def name(self) -> str:
        return "duckduckgo"

    @property
    def is_available(self) -> bool:
        return True

    def _execute_http(self, req: urllib.request.Request) -> str:
        """Execute HTTP request with appropriate error mapping."""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as http_err:
            if http_err.code == 429:
                raise ToolRateLimitError("DuckDuckGo rate limit exceeded (HTTP 429)") from http_err
            raise ToolNetworkError(
                f"DuckDuckGo search HTTP error {http_err.code}: {http_err.reason}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ToolTimeoutError(
                f"DuckDuckGo search connection timed out: {net_err}"
            ) from net_err

    def _search_html(self, query: str, max_results: int) -> list[SearchResult]:
        """Perform search by querying DuckDuckGo HTML endpoint."""
        post_data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        req = urllib.request.Request(DDG_HTML_URL, data=post_data, headers=headers, method="POST")
        html_content = self._execute_http(req)

        parser = DuckDuckGoHTMLParser()
        parser.feed(html_content)

        results: list[SearchResult] = []
        for item in parser.results[:max_results]:
            title = sanitize_external_text(item["title"])
            snippet = sanitize_external_text(item["snippet"])
            url = item["url"].strip()
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))

        return results

    def _search_instant_answer(self, query: str, max_results: int) -> list[SearchResult]:
        """Fallback to DuckDuckGo Instant Answer API."""
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        })
        url = f"{DDG_API_URL}?{params}"
        headers = {"User-Agent": "LYRA-Personal-AI-OS/1.0", "Accept": "application/json"}
        req = urllib.request.Request(url, headers=headers, method="GET")

        raw_body = self._execute_http(req)
        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as err:
            raise ToolExecutionError(f"DuckDuckGo returned invalid JSON: {err}") from err

        results: list[SearchResult] = []

        # Abstract
        abstract = data.get("AbstractText", "").strip()
        heading = data.get("Heading", query).strip()
        abstract_url = data.get("AbstractURL", "").strip()
        if abstract:
            results.append(
                SearchResult(
                    title=sanitize_external_text(heading),
                    url=abstract_url or "https://duckduckgo.com",
                    snippet=sanitize_external_text(abstract),
                )
            )

        # Related topics
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if isinstance(topic, dict) and "Text" in topic:
                text = topic["Text"]
                first_url = topic.get("FirstURL", "")
                title = text.split(" - ")[0] if " - " in text else text[:60]
                results.append(
                    SearchResult(
                        title=sanitize_external_text(title),
                        url=first_url or "https://duckduckgo.com",
                        snippet=sanitize_external_text(text),
                    )
                )

        return results

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute web search using HTML endpoint, falling back to Instant Answer API."""
        clean_q = query.strip()
        if not clean_q:
            return []

        def _do_search() -> list[SearchResult]:
            try:
                results = self._search_html(clean_q, max_results)
                if results:
                    return results
            except Exception as html_err:
                self._logger.debug("DuckDuckGo HTML search fell through: %s", html_err)

            # Fallback to Instant Answer API
            return self._search_instant_answer(clean_q, max_results)

        return await asyncio.to_thread(_do_search)
