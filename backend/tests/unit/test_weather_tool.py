"""Unit tests for LYRA WeatherTool with mocked Open-Meteo API."""

import asyncio
import io
import json
import socket
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from lyra.models.tools import ToolRequest
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.weather import WeatherTool

MOCK_GEO_RESPONSE = {
    "results": [
        {
            "id": 2643743,
            "name": "London",
            "latitude": 51.50853,
            "longitude": -0.12574,
            "admin1": "England",
            "country": "United Kingdom",
        }
    ]
}

MOCK_FORECAST_RESPONSE = {
    "latitude": 51.5,
    "longitude": -0.12,
    "current": {
      "time": "2026-09-12T12:00",
      "temperature_2m": 19.5,
      "relative_humidity_2m": 60,
      "apparent_temperature": 18.9,
      "precipitation": 0.0,
      "weather_code": 1,
      "wind_speed_10m": 14.0,
    }
}


def make_mock_response(data: dict) -> MagicMock:
    """Helper to mock urllib.request.urlopen context manager returning JSON."""
    raw = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


def test_weather_tool_metadata():
    """Verify tool identity, description, permissions, and schema."""
    tool = WeatherTool()
    assert tool.name == "weather"
    assert "weather" in tool.description.lower()
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert tool.input_schema["type"] == "object"
    assert "location" in tool.input_schema["properties"]
    assert "units" in tool.input_schema["properties"]


def test_weather_tool_successful_execution():
    """Verify successful weather retrieval and output structure."""
    tool = WeatherTool()

    def mock_urlopen(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "geocoding-api" in url:
            return make_mock_response(MOCK_GEO_RESPONSE)
        return make_mock_response(MOCK_FORECAST_RESPONSE)

    req = ToolRequest(tool_name="weather", arguments={"location": "London", "units": "celsius"})
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = asyncio.run(tool.execute(req))

    assert res.success is True
    assert res.tool_name == "weather"
    assert isinstance(res.output, dict)
    assert res.output["temperature"] == 19.5
    assert res.output["unit"] == "°C"
    assert res.output["conditions"] == "Mainly clear"
    assert "London" in res.output["location"]

    # Test format_result
    formatted = tool.format_result(res)
    assert "19.5°C" in formatted
    assert "Mainly clear" in formatted
    assert "London" in formatted


def test_weather_tool_geocoding_not_found():
    """Verify graceful handling when location is unknown."""
    tool = WeatherTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response({"results": []})):
        req = ToolRequest(tool_name="weather", arguments={"location": "AtlantisXYZ"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "Could not resolve coordinates" in res.error


def test_weather_tool_rate_limit_error():
    """Verify HTTP 429 rate limit is captured cleanly."""
    tool = WeatherTool()

    err = urllib.error.HTTPError(
        url="https://api.open-meteo.com/v1/forecast",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore
        fp=io.BytesIO(b"Rate limit exceeded"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        req = ToolRequest(tool_name="weather", arguments={"location": "London"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "rate limit exceeded" in res.error.lower()


def test_weather_tool_network_timeout():
    """Verify network timeout is captured without crashing."""
    tool = WeatherTool()

    with patch("urllib.request.urlopen", side_effect=socket.timeout("Operation timed out")):
        req = ToolRequest(tool_name="weather", arguments={"location": "London"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "timed out" in res.error.lower()


def test_weather_tool_invalid_json():
    """Verify malformed JSON response is handled safely."""
    tool = WeatherTool()

    bad_resp = MagicMock()
    bad_resp.read.return_value = b"<html>Service Down</html>"
    bad_resp.__enter__.return_value = bad_resp
    bad_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=bad_resp):
        req = ToolRequest(tool_name="weather", arguments={"location": "London"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "invalid json" in res.error.lower()


def test_weather_tool_can_handle():
    """Verify regex and trigger pattern recognition for weather intents."""
    tool = WeatherTool()

    assert tool.can_handle("What is the weather in Tokyo?") == {"location": "tokyo", "units": "celsius"}
    assert tool.can_handle("Weather for San Francisco in fahrenheit") == {"location": "san francisco", "units": "fahrenheit"}
    assert tool.can_handle("How hot is it in Madrid?") == {"location": "madrid", "units": "celsius"}
    assert tool.can_handle("Paris weather") == {"location": "paris", "units": "celsius"}

    # Irrelevant
    assert tool.can_handle("Hello LYRA") is None
    assert tool.can_handle("Who is Napoleon?") is None
