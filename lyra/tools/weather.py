"""Free, no-key Weather tool for LYRA using Open-Meteo."""

import asyncio
import json
import re
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
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.sanitizer import sanitize_external_text

WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherTool(Tool):
    """Retrieves current weather conditions for any location via free Open-Meteo API."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._logger = get_logger("tools.weather")

    @property
    def name(self) -> str:
        return "weather"

    @property
    def description(self) -> str:
        return "Get current weather conditions (temperature, humidity, precipitation, conditions) for a city or location."

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
                "location": {
                    "type": "string",
                    "description": "City or location name (e.g. 'Tokyo', 'London', 'San Francisco').",
                },
                "units": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "Temperature unit to return ('celsius' or 'fahrenheit'). Defaults to 'celsius'.",
                },
            },
            "required": ["location"],
            "additionalProperties": False,
        }

    def _http_get(self, url: str) -> dict[str, Any]:
        """Perform a synchronous HTTP GET request with standard headers."""
        headers = {
            "User-Agent": "LYRA-Personal-AI-OS/1.0",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as http_err:
            if http_err.code == 429:
                raise ToolRateLimitError(f"Open-Meteo rate limit exceeded (HTTP 429)") from http_err
            raise ToolNetworkError(
                f"Open-Meteo API HTTP error {http_err.code}: {http_err.reason}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ToolTimeoutError(f"Open-Meteo request timed out or network unreachable: {net_err}") from net_err
        except json.JSONDecodeError as json_err:
            raise ToolExecutionError(f"Open-Meteo returned invalid JSON: {json_err}") from json_err

    def _geocode_location(self, location_name: str) -> dict[str, Any]:
        """Resolve a city or place name to latitude, longitude, and display label."""
        query_params = urllib.parse.urlencode({
            "name": location_name,
            "count": 1,
            "language": "en",
            "format": "json",
        })
        url = f"{GEOCODING_API_URL}?{query_params}"
        payload = self._http_get(url)

        results = payload.get("results")
        if not results or not isinstance(results, list):
            raise ToolExecutionError(f"Could not resolve coordinates for location '{location_name}'.")

        best = results[0]
        name = best.get("name", location_name)
        country = best.get("country", "")
        admin1 = best.get("admin1", "")
        place_parts = [p for p in [name, admin1, country] if p]
        full_name = ", ".join(place_parts)

        return {
            "latitude": best["latitude"],
            "longitude": best["longitude"],
            "display_name": full_name,
        }

    def _fetch_forecast(self, lat: float, lon: float, units: str) -> dict[str, Any]:
        """Fetch current conditions from Open-Meteo forecast endpoint."""
        query_params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "temperature_unit": units,
            "wind_speed_unit": "kmh",
        })
        url = f"{FORECAST_API_URL}?{query_params}"
        return self._http_get(url)

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Fetch and return current weather conditions."""
        location = str(request.arguments.get("location", "")).strip()
        if not location:
            return ToolResult(tool_name=self.name, success=False, error="Location cannot be empty.")

        units = request.arguments.get("units", "celsius")
        temp_symbol = "°C" if units == "celsius" else "°F"

        try:
            # 1. Geocode location name
            geo = await asyncio.to_thread(self._geocode_location, location)

            # 2. Fetch forecast
            forecast_data = await asyncio.to_thread(
                self._fetch_forecast,
                geo["latitude"],
                geo["longitude"],
                units,
            )

            current = forecast_data.get("current", {})
            weather_code = current.get("weather_code", 0)
            condition_desc = WMO_WEATHER_CODES.get(weather_code, "Unknown conditions")

            temp = current.get("temperature_2m")
            feels_like = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            wind_speed = current.get("wind_speed_10m")
            precipitation = current.get("precipitation", 0.0)

            summary = (
                f"{condition_desc}, {temp}{temp_symbol} "
                f"(feels like {feels_like}{temp_symbol}), "
                f"humidity: {humidity}%, wind: {wind_speed} km/h"
            )

            clean_summary = sanitize_external_text(summary)
            clean_display = sanitize_external_text(geo["display_name"])

            structured = {
                "location": clean_display,
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "temperature": temp,
                "apparent_temperature": feels_like,
                "unit": temp_symbol,
                "conditions": condition_desc,
                "humidity_percent": humidity,
                "wind_speed_kmh": wind_speed,
                "precipitation_mm": precipitation,
                "summary": clean_summary,
            }

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=structured,
                metadata={"source": "open-meteo"},
            )

        except ToolError as tool_err:
            self._logger.warning("Weather tool error for '%s': %s", location, tool_err)
            return ToolResult(tool_name=self.name, success=False, error=str(tool_err))
        except Exception as err:  # pylint: disable=broad-except
            self._logger.error("Unexpected weather retrieval error: %s", err)
            return ToolResult(tool_name=self.name, success=False, error=f"Weather error: {err}")

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Evaluate if user query is asking for weather information."""
        lowered = user_input.lower().strip()
        weather_triggers = ("weather", "temperature", "forecast", "is it raining", "how hot is", "how cold is")

        if not any(trigger in lowered for trigger in weather_triggers):
            return None

        # Determine units
        units = "fahrenheit" if ("fahrenheit" in lowered or "°f" in lowered) else "celsius"

        # Extract location candidate using preposition patterns
        match = re.search(r"\b(?:in|for|at|around)\s+([a-zA-Z\s,.-]+)", lowered)
        if match:
            candidate = match.group(1).strip("?.,! ")
            # Remove trailing units and words if present
            candidate = re.sub(
                r"\b(in\s+fahrenheit|in\s+celsius|fahrenheit|celsius|today|tomorrow|right now|currently|please)\b",
                "",
                candidate,
            ).strip()
            if candidate:
                return {"location": candidate, "units": units}

        # Match '<city> weather'
        match_suffix = re.search(r"([a-zA-Z\s,.-]+)\s+weather", lowered)
        if match_suffix:
            candidate = match_suffix.group(1).strip("?.,! ")
            candidate = re.sub(r"\b(what is the|how is the|what's the|tell me the|the)\b", "", candidate).strip()
            if candidate and len(candidate) > 2:
                return {"location": candidate, "units": units}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format weather result into a natural, friendly companion message."""
        if not result.is_success():
            return f"I couldn't fetch the weather: {result.error}"

        out = result.output
        if isinstance(out, dict):
            loc = out.get("location", "the requested location")
            temp = out.get("temperature", "--")
            unit = out.get("unit", "°C")
            cond = out.get("conditions", "Clear")
            feels = out.get("apparent_temperature", temp)
            humidity = out.get("humidity_percent", "--")
            wind = out.get("wind_speed_kmh", "--")
            return (
                f"The current weather in {loc} is {temp}{unit} ({cond}, feels like {feels}{unit}) "
                f"with {humidity}% humidity and wind at {wind} km/h."
            )
        return result.to_text()
