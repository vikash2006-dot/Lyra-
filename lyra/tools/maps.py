"""Free OpenStreetMap (Nominatim & OSRM) Maps tool for LYRA."""

import asyncio
import json
import re
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from lyra.config.settings import load_settings
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

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OSRM_ROUTE_URL = "http://router.project-osrm.org/route/v1/driving"


class MapsTool(Tool):
    """Provides location search and route directions using OpenStreetMap and OSRM."""

    def __init__(
        self,
        user_agent: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        settings = load_settings()
        self.user_agent = user_agent or settings.nominatim_user_agent
        self.timeout_seconds = timeout_seconds
        self._logger = get_logger("tools.maps")

    @property
    def name(self) -> str:
        return "maps"

    @property
    def description(self) -> str:
        return "Search locations, coordinates, and calculate driving distance and travel duration between places."

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
                "action": {
                    "type": "string",
                    "enum": ["search", "directions"],
                    "description": "'search' to locate a place, or 'directions' to calculate travel distance and duration.",
                },
                "query": {
                    "type": "string",
                    "description": "Place name or address to locate (used when action is 'search').",
                },
                "origin": {
                    "type": "string",
                    "description": "Starting location (used when action is 'directions').",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination location (used when action is 'directions').",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def _http_get(self, url: str) -> Any:
        """Execute synchronous HTTP GET returning parsed JSON."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as http_err:
            if http_err.code == 429:
                raise ToolRateLimitError(f"Maps service rate limit exceeded (HTTP 429)") from http_err
            raise ToolNetworkError(f"Maps service HTTP error {http_err.code}: {http_err.reason}") from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ToolTimeoutError(f"Maps request connection timed out: {net_err}") from net_err
        except json.JSONDecodeError as json_err:
            raise ToolExecutionError(f"Maps service returned invalid JSON: {json_err}") from json_err

    def _geocode(self, place_name: str) -> dict[str, Any]:
        """Geocode a place name using Nominatim."""
        params = urllib.parse.urlencode({
            "q": place_name,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        })
        url = f"{NOMINATIM_SEARCH_URL}?{params}"
        payload = self._http_get(url)

        if not isinstance(payload, list) or not payload:
            raise ToolExecutionError(f"Location '{place_name}' could not be found on OpenStreetMap.")

        item = payload[0]
        return {
            "display_name": sanitize_external_text(item.get("display_name", place_name)),
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
            "type": item.get("type", "location"),
        }

    def _calculate_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> dict[str, Any]:
        """Calculate driving route via OSRM."""
        # Note: OSRM expects coordinates in {lon},{lat} format
        coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        url = f"{OSRM_ROUTE_URL}/{coords}?overview=false"

        payload = self._http_get(url)
        routes = payload.get("routes", [])
        if not routes:
            raise ToolExecutionError("Could not calculate a driving route between the specified locations.")

        best_route = routes[0]
        distance_meters = float(best_route.get("distance", 0.0))
        duration_seconds = float(best_route.get("duration", 0.0))

        distance_km = round(distance_meters / 1000.0, 1)
        distance_miles = round(distance_km * 0.621371, 1)

        total_mins = int(duration_seconds // 60)
        hours = total_mins // 60
        mins = total_mins % 60

        if hours > 0:
            duration_str = f"{hours} hr {mins} min" if mins > 0 else f"{hours} hr"
        else:
            duration_str = f"{mins} min"

        summary_road = ""
        legs = best_route.get("legs", [])
        if legs and isinstance(legs, list):
            summary_road = legs[0].get("summary", "")

        return {
            "distance_km": distance_km,
            "distance_miles": distance_miles,
            "duration_seconds": duration_seconds,
            "duration_readable": duration_str,
            "route_summary": summary_road,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute map search or routing."""
        action = request.arguments.get("action", "search")

        try:
            if action == "search":
                query = str(request.arguments.get("query", "")).strip()
                if not query:
                    return ToolResult(tool_name=self.name, success=False, error="Search query cannot be empty.")

                geo = await asyncio.to_thread(self._geocode, query)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "search",
                        "query": query,
                        "location": geo["display_name"],
                        "latitude": geo["latitude"],
                        "longitude": geo["longitude"],
                        "type": geo["type"],
                    },
                    metadata={"source": "nominatim"},
                )

            if action == "directions":
                origin = str(request.arguments.get("origin", "")).strip()
                dest = str(request.arguments.get("destination", "")).strip()
                if not origin or not dest:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Both origin and destination are required for directions.",
                    )

                origin_geo = await asyncio.to_thread(self._geocode, origin)
                dest_geo = await asyncio.to_thread(self._geocode, dest)

                route_info = await asyncio.to_thread(
                    self._calculate_route,
                    origin_geo["latitude"],
                    origin_geo["longitude"],
                    dest_geo["latitude"],
                    dest_geo["longitude"],
                )

                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "directions",
                        "origin": origin_geo["display_name"],
                        "destination": dest_geo["display_name"],
                        "distance_km": route_info["distance_km"],
                        "distance_miles": route_info["distance_miles"],
                        "duration": route_info["duration_readable"],
                        "summary_road": route_info["route_summary"],
                    },
                    metadata={"source": "osrm"},
                )

            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Unknown action '{action}'. Allowed actions: 'search', 'directions'.",
            )

        except ToolError as tool_err:
            self._logger.warning("Maps tool error: %s", tool_err)
            return ToolResult(tool_name=self.name, success=False, error=str(tool_err))
        except Exception as err:  # pylint: disable=broad-except
            self._logger.error("Unexpected maps error: %s", err)
            return ToolResult(tool_name=self.name, success=False, error=f"Maps error: {err}")

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Identify location search or direction routing requests."""
        lowered = user_input.lower().strip()

        # Directions: 'how far is X from Y', 'distance between X and Y', 'route from X to Y', 'directions from X to Y'
        dist_match = re.search(r"\bhow\s+far\s+is\s+([a-zA-Z\s,.-]+?)\s+(?:from|to)\s+([a-zA-Z\s,.-]+)", lowered)
        if dist_match:
            o, d = dist_match.group(1).strip("?.,! "), dist_match.group(2).strip("?.,! ")
            if o and d:
                return {"action": "directions", "origin": o, "destination": d}

        route_match = re.search(r"\b(?:distance\s+between|route\s+between)\s+([a-zA-Z\s,.-]+?)\s+and\s+([a-zA-Z\s,.-]+)", lowered)
        if route_match:
            o, d = route_match.group(1).strip("?.,! "), route_match.group(2).strip("?.,! ")
            if o and d:
                return {"action": "directions", "origin": o, "destination": d}

        dir_match = re.search(r"\b(?:directions|route)\s+from\s+([a-zA-Z\s,.-]+?)\s+to\s+([a-zA-Z\s,.-]+)", lowered)
        if dir_match:
            o, d = dir_match.group(1).strip("?.,! "), dir_match.group(2).strip("?.,! ")
            if o and d:
                return {"action": "directions", "origin": o, "destination": d}

        # Search: 'where is X', 'locate X', 'coordinates of X'
        search_match = re.search(r"\b(?:where\s+is|locate|coordinates\s+of|find\s+on\s+map)\s+([a-zA-Z0-9\s,.-]+)", lowered)
        if search_match:
            q = search_match.group(1).strip("?.,! ")
            if q:
                return {"action": "search", "query": q}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format map results into friendly companion text."""
        if not result.is_success():
            return f"I couldn't locate that on the map: {result.error}"

        out = result.output
        if isinstance(out, dict):
            action = out.get("action")
            if action == "directions":
                origin = out.get("origin", "origin")
                dest = out.get("destination", "destination")
                km = out.get("distance_km", 0)
                miles = out.get("distance_miles", 0)
                duration = out.get("duration", "")
                road = out.get("summary_road", "")
                via_str = f" via {road}" if road else ""
                return (
                    f"Driving from {origin} to {dest} is about {km} km ({miles} miles), "
                    f"taking approximately {duration}{via_str}."
                )

            loc = out.get("location", "the requested place")
            lat = out.get("latitude")
            lon = out.get("longitude")
            return f"Found location: {loc} (Coordinates: {lat}, {lon})."

        return result.to_text()
