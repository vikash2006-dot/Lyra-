"""Free, public RSS News tool for LYRA."""

import asyncio
from html.parser import HTMLParser
import re
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from lyra.core.exceptions import (
    ToolError,
    ToolExecutionError,
    ToolNetworkError,
    ToolRateLimitError,
    ToolTimeoutError,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.sanitizer import sanitize_external_text

BBC_FEEDS: dict[str, str] = {
    "top": "https://feeds.bbci.co.uk/news/rss.xml",
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
}

GOOGLE_NEWS_TOP_URL = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/rss/search"


class HTMLStripper(HTMLParser):
    """Utility to strip raw HTML markup from RSS descriptions."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self.text_parts).split())


def strip_html_tags(html_text: str) -> str:
    """Strip tags and entities from HTML text."""
    if not html_text:
        return ""
    try:
        stripper = HTMLStripper()
        stripper.feed(html_text)
        return stripper.get_text()
    except Exception:
        # Fallback regex strip
        return re.sub(r"<[^>]+>", "", html_text).strip()


class NewsTool(Tool):
    """Retrieves current news headlines and articles from public RSS feeds."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._logger = get_logger("tools.news")

    @property
    def name(self) -> str:
        return "news"

    @property
    def description(self) -> str:
        return "Get latest breaking news headlines and articles by topic or search query using public feeds."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def requires_network(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["top", "world", "technology", "business", "science"],
                    "description": "News topic category ('top', 'world', 'technology', 'business', 'science').",
                },
                "query": {
                    "type": "string",
                    "description": "Optional search term to filter or search news headlines.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of news stories to return (1 to 10). Defaults to 5.",
                },
            },
            "additionalProperties": False,
        }

    def _fetch_rss_content(self, url: str) -> str:
        """Fetch raw XML data from an RSS endpoint."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as http_err:
            if http_err.code == 429:
                raise ToolRateLimitError("News RSS feed rate limit exceeded (HTTP 429)") from http_err
            raise ToolNetworkError(
                f"News RSS feed HTTP error {http_err.code}: {http_err.reason}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ToolTimeoutError(f"News RSS connection timed out: {net_err}") from net_err

    def _parse_feed(self, xml_text: str, limit: int) -> list[dict[str, str]]:
        """Parse XML RSS into clean, sanitized article dictionaries."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as err:
            raise ToolExecutionError(f"Failed to parse news RSS feed XML: {err}") from err

        channel = root.find("channel")
        if channel is None:
            channel = root

        articles: list[dict[str, str]] = []
        for item in channel.findall("item")[:limit]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_date_el = item.find("pubDate")
            source_el = item.find("source")

            title = title_el.text if title_el is not None and title_el.text else "Untitled"
            link = link_el.text if link_el is not None and link_el.text else ""
            raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""
            pub_date = pub_date_el.text if pub_date_el is not None and pub_date_el.text else ""
            source = source_el.text if source_el is not None and source_el.text else ""

            clean_desc = strip_html_tags(raw_desc)
            clean_title = sanitize_external_text(title)
            clean_snippet = sanitize_external_text(clean_desc)

            if clean_title:
                articles.append({
                    "title": clean_title,
                    "url": link.strip(),
                    "summary": clean_snippet,
                    "published": pub_date.strip(),
                    "source": source.strip(),
                })

        return articles

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Fetch and return news articles."""
        topic = request.arguments.get("topic", "top")
        query = str(request.arguments.get("query", "")).strip()
        limit = int(request.arguments.get("limit") or 5)
        limit = max(1, min(10, limit))

        try:
            # 1. Determine feed URL
            if query:
                # Use Google News RSS search
                params = urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
                feed_url = f"{GOOGLE_NEWS_SEARCH_URL}?{params}"
                source_label = f"Search: {query}"
            else:
                feed_url = BBC_FEEDS.get(topic, BBC_FEEDS["top"])
                source_label = f"BBC News ({topic.capitalize()})"

            # 2. Fetch and parse
            xml_text = await asyncio.to_thread(self._fetch_rss_content, feed_url)
            articles = await asyncio.to_thread(self._parse_feed, xml_text, limit)

            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "topic": topic if not query else "search",
                    "query": query or None,
                    "count": len(articles),
                    "articles": articles,
                    "source_feed": source_label,
                },
                metadata={"source": "rss"},
            )

        except ToolError as tool_err:
            self._logger.warning("News tool error: %s", tool_err)
            return ToolResult(tool_name=self.name, success=False, error=str(tool_err))
        except Exception as err:  # pylint: disable=broad-except
            self._logger.error("Unexpected error in news tool: %s", err)
            return ToolResult(tool_name=self.name, success=False, error=f"News error: {err}")

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Evaluate if user query is asking for news headlines or articles."""
        lowered = user_input.lower().strip()
        news_triggers = ("news", "headlines", "latest news", "breaking news", "what's in the news", "what happened today")

        if not any(trigger in lowered for trigger in news_triggers):
            return None

        # Check for specific topics
        for t in ("world", "technology", "business", "science"):
            if t in lowered or (t == "technology" and "tech" in lowered):
                return {"topic": t}

        # Check for query like 'news about <topic>' or 'news on <topic>'
        match = re.search(r"\bnews\s+(?:about|on|regarding)\s+([a-zA-Z0-9\s,.-]+)", lowered)
        if match:
            q = match.group(1).strip("?.,! ")
            if q:
                return {"query": q}

        return {"topic": "top"}

    def format_result(self, result: ToolResult) -> str:
        """Format news items into friendly markdown text."""
        if not result.is_success():
            return f"I couldn't load the news headlines: {result.error}"

        out = result.output
        if isinstance(out, dict):
            articles = out.get("articles", [])
            source_label = out.get("source_feed", "News Feed")
            if not articles:
                return f"No news articles found from {source_label}."

            lines = [f"### Latest Headlines ({source_label}):\n"]
            for i, item in enumerate(articles, 1):
                title = item.get("title", "Untitled")
                url = item.get("url", "")
                summary = item.get("summary", "")
                pub = item.get("published", "")
                pub_text = f" *({pub})*" if pub else ""

                if url:
                    lines.append(f"{i}. [{title}]({url}){pub_text}")
                else:
                    lines.append(f"{i}. **{title}**{pub_text}")

                if summary:
                    lines.append(f"   {summary}")

            return "\n".join(lines)

        return result.to_text()
