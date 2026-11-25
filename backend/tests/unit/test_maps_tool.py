"""Unit tests for LYRA MapsTool with OpenStreetMap and OSRM mocks."""

import asyncio
import io
import json
import socket
from unittest.mock import MagicMock, patch
import urllib.error

from lyra.models.tools import ToolRequest
from lyra.tools.maps import MapsTool
from lyra.tools.permissions import ToolPermissionLevel

MOCK_PARIS_GEO = [
    {
        "lat": "48.8588897",
        "lon": "2.3200410",
        "display_name": "Paris, Île-de-France, France",
        "type": "city",
    }
]

MOCK_LYON_GEO = [
    {
        "lat": "45.7578137",
        "lon": "4.8320114",
        "display_name": "Lyon, Métropole de Lyon, France",
        "type": "city",
    }
]

MOCK_OSRM_ROUTE = {
    "code": "Ok",
    "routes": [
        {
            "distance": 465200.0,
            "duration": 15420.0,
            "legs": [{"summary": "A 6"}],
        }
    ],
}


def make_mock_response(data: dict | list) -> MagicMock:
    raw = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


def test_maps_tool_metadata():
    """Verify MapsTool properties, permissions, and input schema."""
    tool = MapsTool()
    assert tool.name == "maps"
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert tool.input_schema["properties"]["action"]["enum"] == ["search", "directions"]


def test_maps_tool_search_success():
    """Verify location search with Nominatim mock."""
    tool = MapsTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response(MOCK_PARIS_GEO)):
        req = ToolRequest(tool_name="maps", arguments={"action": "search", "query": "Paris"})
        res = asyncio.run(tool.execute(req))

    assert res.success is True
    assert res.output["latitude"] == 48.8588897
    assert res.output["longitude"] == 2.320041
    assert "Paris" in res.output["location"]

    formatted = tool.format_result(res)
    assert "Found location: Paris" in formatted
    assert "48.8588897" in formatted


def test_maps_tool_search_not_found():
    """Verify handling when place is not found."""
    tool = MapsTool()

    with patch("urllib.request.urlopen", return_value=make_mock_response([])):
        req = ToolRequest(tool_name="maps", arguments={"action": "search", "query": "NonexistentPlace999"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "could not be found" in res.error


def test_maps_tool_directions_success():
    """Verify driving route calculation between two places."""
    tool = MapsTool()

    def mock_urlopen(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "nominatim" in url:
            if "Paris" in url:
                return make_mock_response(MOCK_PARIS_GEO)
            return make_mock_response(MOCK_LYON_GEO)
        if "router.project-osrm.org" in url:
            return make_mock_response(MOCK_OSRM_ROUTE)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        req = ToolRequest(
            tool_name="maps",
            arguments={"action": "directions", "origin": "Paris", "destination": "Lyon"},
        )
        res = asyncio.run(tool.execute(req))

    assert res.success is True
    assert res.output["distance_km"] == 465.2
    assert res.output["distance_miles"] == 289.1
    assert "4 hr 17 min" in res.output["duration"]
    assert res.output["summary_road"] == "A 6"

    formatted = tool.format_result(res)
    assert "465.2 km" in formatted
    assert "4 hr 17 min" in formatted
    assert "via A 6" in formatted


def test_maps_tool_rate_limit():
    """Verify HTTP 429 rate limit is captured cleanly."""
    tool = MapsTool()

    err = urllib.error.HTTPError(
        url="https://nominatim.openstreetmap.org/search",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore
        fp=io.BytesIO(b"Rate limit"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        req = ToolRequest(tool_name="maps", arguments={"action": "search", "query": "Paris"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "rate limit exceeded" in res.error.lower()


def test_maps_tool_timeout():
    """Verify connection timeout is handled gracefully."""
    tool = MapsTool()

    with patch("urllib.request.urlopen", side_effect=socket.timeout("Timed out")):
        req = ToolRequest(tool_name="maps", arguments={"action": "search", "query": "Paris"})
        res = asyncio.run(tool.execute(req))

    assert res.success is False
    assert "timed out" in res.error.lower()


def test_maps_tool_can_handle():
    """Verify intent matching for maps tool queries."""
    tool = MapsTool()

    # Search
    assert tool.can_handle("Where is the Eiffel Tower?") == {"action": "search", "query": "the eiffel tower"}
    assert tool.can_handle("Locate Central Park") == {"action": "search", "query": "central park"}

    # Directions
    assert tool.can_handle("How far is Paris from Lyon?") == {"action": "directions", "origin": "paris", "destination": "lyon"}
    assert tool.can_handle("Distance between London and Edinburgh") == {"action": "directions", "origin": "london", "destination": "edinburgh"}
    assert tool.can_handle("Directions from Berlin to Munich") == {"action": "directions", "origin": "berlin", "destination": "munich"}

    # Irrelevant
    assert tool.can_handle("Hello LYRA, what is 2+2?") is None
