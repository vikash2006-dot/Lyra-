"""Unit tests for SearchTool and SearchProvider subsystem."""

import asyncio
import io
import json
import socket
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from lyra.core.exceptions import ToolExecutionError
from lyra.models.tools import ToolRequest
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.search import SearchTool
from lyra.tools.search_providers.base import SearchProvider, SearchResult
from lyra.tools.search_providers.duckduckgo import DuckDuckGoHTMLParser, DuckDuckGoSearchProvider
from lyra.tools.search_providers.tavily import TavilySearchProvider

MOCK_DDG_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="results">
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org&rut=1">Python Programming</a>
    <div class="result__snippet">Python is a programming language that lets you work quickly.</div>
  </div>
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org&rut=1">Python Documentation</a>
    <div class="result__snippet">Official documentation for Python releases and standard library.</div>
  </div>
</div>
</body>
</html>
"""

MOCK_DDG_API = {
    "Heading": "Python",
    "AbstractText": "Python is a high-level general-purpose programming language.",
    "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "RelatedTopics": [
        {"Text": "Guido van Rossum - Creator of Python", "FirstURL": "https://en.wikipedia.org/wiki/Guido_van_Rossum"}
    ],
}

MOCK_TAVILY_RESPONSE = {
    "results": [
        {
            "title": "Python 3.14 Release Notes",
            "url": "https://docs.python.org/3.14/whatsnew/",
            "content": "What's new in Python 3.14: performance enhancements and interpreter improvements.",
        }
    ]
}


def make_mock_response(content: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = content
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


def test_search_models():
    """Verify SearchResult dataclass conversion."""
    res = SearchResult(title="Test", url="https://example.com", snippet="Example snippet")
    d = res.to_dict()
    assert d["title"] == "Test"
    assert d["url"] == "https://example.com"
    assert d["snippet"] == "Example snippet"


def test_ddg_html_parser():
    """Verify DuckDuckGoHTMLParser extracts clean links and snippets."""
    parser = DuckDuckGoHTMLParser()
    parser.feed(MOCK_DDG_HTML)

    assert len(parser.results) == 2
    assert parser.results[0]["title"] == "Python Programming"
    assert parser.results[0]["url"] == "https://python.org"
    assert "work quickly" in parser.results[0]["snippet"]


def test_ddg_provider_html_search_success():
    """Verify DuckDuckGoSearchProvider succeeds with HTML response."""
    provider = DuckDuckGoSearchProvider()
    assert provider.is_available is True

    with patch("urllib.request.urlopen", return_value=make_mock_response(MOCK_DDG_HTML.encode())):
        results = asyncio.run(provider.search("python programming", max_results=2))

    assert len(results) == 2
    assert results[0].title == "Python Programming"
    assert results[0].url == "https://python.org"


def test_ddg_provider_fallback_to_instant_answer():
    """Verify DuckDuckGoSearchProvider falls back to Instant Answer if HTML has no results."""
    provider = DuckDuckGoSearchProvider()

    # Return empty HTML, then Instant Answer JSON
    def mock_urlopen(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "html.duckduckgo.com" in url:
            return make_mock_response(b"<html><body>No results</body></html>")
        return make_mock_response(json.dumps(MOCK_DDG_API).encode())

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        results = asyncio.run(provider.search("python", max_results=2))

    assert len(results) >= 1
    assert "Python" in results[0].title
    assert "programming language" in results[0].snippet


def test_tavily_provider_unconfigured():
    """Verify TavilySearchProvider reports unavailable and raises error when unconfigured."""
    provider = TavilySearchProvider(api_key=None)
    assert provider.is_available is False

    with pytest.raises(ToolExecutionError, match="not configured"):
        asyncio.run(provider.search("python"))


def test_tavily_provider_successful_search():
    """Verify TavilySearchProvider succeeds when API key is provided."""
    provider = TavilySearchProvider(api_key="tvly-test-key")
    assert provider.is_available is True

    raw = json.dumps(MOCK_TAVILY_RESPONSE).encode()
    with patch("urllib.request.urlopen", return_value=make_mock_response(raw)):
        results = asyncio.run(provider.search("python 3.14", max_results=1))

    assert len(results) == 1
    assert results[0].title == "Python 3.14 Release Notes"
    assert "whatsnew" in results[0].url


def test_search_tool_execution_with_fallback():
    """Verify SearchTool selects available provider and falls back safely on error."""
    # Custom provider that fails
    class FailingProvider(SearchProvider):
        @property
        def name(self) -> str:
            return "failing"

        @property
        def is_available(self) -> bool:
            return True

        async def search(self, query: str, max_results: int = 5):
            raise RuntimeError("API quota exceeded")

    class WorkingProvider(SearchProvider):
        @property
        def name(self) -> str:
            return "working"

        @property
        def is_available(self) -> bool:
            return True

        async def search(self, query: str, max_results: int = 5):
            return [SearchResult(title="Fallback Result", url="https://test.org", snippet="It worked")]

    tool = SearchTool(providers=[FailingProvider(), WorkingProvider()])
    req = ToolRequest(tool_name="search", arguments={"query": "test query"})
    res = asyncio.run(tool.execute(req))

    assert res.success is True
    assert res.output["provider"] == "working"
    assert len(res.output["results"]) == 1
    assert res.output["results"][0]["title"] == "Fallback Result"

    formatted = tool.format_result(res)
    assert "Fallback Result" in formatted
    assert "https://test.org" in formatted


def test_search_tool_can_handle():
    """Verify search tool intent detection."""
    tool = SearchTool()

    assert tool.can_handle("search the web for Python tutorials") == {"query": "python tutorials"}
    assert tool.can_handle("google latest quantum computing news") == {"query": "latest quantum computing news"}
    assert tool.can_handle("look up on the web astronomy") == {"query": "astronomy"}

    # Irrelevant
    assert tool.can_handle("What time is it?") is None
