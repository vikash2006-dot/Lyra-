"""Unit tests for LYRA NewsTool with mocked RSS feeds."""

import asyncio
import io
import socket
from unittest.mock import MagicMock, patch
import urllib.error

from lyra.models.tools import ToolRequest
from lyra.tools.news import NewsTool, strip_html_tags
from lyra.tools.permissions import ToolPermissionLevel

MOCK_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>BBC News - Technology</title>
    <item>
      <title>AI Breakthrough in Chip Design</title>
      <link>https://www.bbc.co.uk/news/technology-101</link>
      <description>&lt;p&gt;Engineers utilize machine learning to accelerate processor layout design.&lt;/p&gt;</description>
      <pubDate>Sat, 12 Sep 2026 09:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Quantum Computing Milestone Reached</title>
      <link>https://www.bbc.co.uk/news/technology-102</link>
      <description>Scientists achieve fault-tolerant logical qubits at scale.</description>
      <pubDate>Sat, 12 Sep 2026 11:15:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def make_mock_response(content: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = content
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


def test_strip_html_tags():
    """Verify HTML stripping utility cleans description text."""
    html_text = "<b>Breaking:</b> Discoveries announced in <i>Nature</i> &amp; Science."
    stripped = strip_html_tags(html_text)
    assert "<b>" not in stripped
    assert "<i>" not in stripped
    assert "Breaking: Discoveries announced in Nature" in stripped


def test_news_tool_metadata():
    """Verify NewsTool properties, permissions, and input schema."""
    tool = NewsTool()
    assert tool.name == "news"
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert "topic" in tool.input_schema["properties"]
    assert "query" in tool.input_schema["properties"]


def test_news_tool_successful_topic_fetch():
    """Verify successful news parsing from mocked RSS feed."""
    tool = NewsTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response(MOCK_RSS_XML.encode())):
        req = ToolRequest(tool_name="news", arguments={"topic": "technology", "limit": 2})
        res = asyncio.run(tool.execute(req))

    assert res.success is True
    assert res.output["count"] == 2
    articles = res.output["articles"]
    assert articles[0]["title"] == "AI Breakthrough in Chip Design"
    assert "https://www.bbc.co.uk/news/technology-101" in articles[0]["url"]
    assert "processor layout" in articles[0]["summary"]

    formatted = tool.format_result(res)
    assert "Latest Headlines" in formatted
    assert "AI Breakthrough in Chip Design" in formatted


def test_news_tool_search_query():
    """Verify searching news with a query uses the search feed."""
    tool = NewsTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response(MOCK_RSS_XML.encode())) as mock_open:
        req = ToolRequest(tool_name="news", arguments={"query": "semiconductors"})
        res = asyncio.run(tool.execute(req))

        assert res.success is True
        called_req = mock_open.call_args[0][0]
        url = called_req.full_url if hasattr(called_req, "full_url") else str(called_req)
        assert "news.google.com/rss/search" in url


def test_news_tool_malformed_xml():
    """Verify invalid XML handled cleanly without crash."""
    tool = NewsTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response(b"Not XML content at all")):
        req = ToolRequest(tool_name="news", arguments={})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "Failed to parse news RSS feed" in res.error


def test_news_tool_rate_limit():
    """Verify HTTP 429 is captured."""
    tool = NewsTool()

    err = urllib.error.HTTPError(
        url="https://feeds.bbci.co.uk/news/rss.xml",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore
        fp=io.BytesIO(b"Rate limit"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        req = ToolRequest(tool_name="news", arguments={})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "rate limit exceeded" in res.error.lower()


def test_news_tool_timeout():
    """Verify connection timeout is handled gracefully."""
    tool = NewsTool()

    with patch("urllib.request.urlopen", side_effect=socket.timeout("Timed out")):
        req = ToolRequest(tool_name="news", arguments={})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "timed out" in res.error.lower()


def test_news_tool_can_handle():
    """Verify query trigger detection for news."""
    tool = NewsTool()

    assert tool.can_handle("What is the latest news?") == {"topic": "top"}
    assert tool.can_handle("Show me tech news") == {"topic": "technology"}
    assert tool.can_handle("News about artificial intelligence") == {"query": "artificial intelligence"}

    assert tool.can_handle("What time is it in Tokyo?") is None
