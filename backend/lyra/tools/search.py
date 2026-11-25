"""Web search tool for LYRA with provider abstraction."""

import asyncio
import re
from typing import Any, Sequence

from lyra.core.exceptions import ToolError, ToolExecutionError
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.search_providers.base import SearchProvider, SearchResult
from lyra.tools.search_providers.duckduckgo import DuckDuckGoSearchProvider
from lyra.tools.search_providers.tavily import TavilySearchProvider


class SearchTool(Tool):
    """Tool allowing LYRA to perform live web searches."""

    def __init__(
        self,
        providers: Sequence[SearchProvider] | None = None,
        default_max_results: int = 5,
    ) -> None:
        if providers:
            self._providers = list(providers)
        else:
            # Default pool: Tavily (if configured) first, followed by DuckDuckGo (free, zero-key)
            self._providers = [TavilySearchProvider(), DuckDuckGoSearchProvider()]

        self.default_max_results = default_max_results
        self._logger = get_logger("tools.search")

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return "Search the web for up-to-date information, documentation, articles, or answers."

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
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to retrieve (1 to 10).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def _select_provider(self) -> SearchProvider:
        """Select the first available search provider."""
        for prov in self._providers:
            if prov.is_available:
                return prov
        # Fallback to DuckDuckGo even if not explicitly marked
        return DuckDuckGoSearchProvider()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute web search across available providers."""
        query = str(request.arguments.get("query", "")).strip()
        if not query:
            return ToolResult(tool_name=self.name, success=False, error="Search query cannot be empty.")

        max_results = int(request.arguments.get("max_results") or self.default_max_results)
        max_results = max(1, min(10, max_results))

        last_error: Exception | None = None
        for provider in self._providers:
            if not provider.is_available:
                continue

            try:
                self._logger.info("Executing web search using '%s' provider", provider.name)
                results: list[SearchResult] = await provider.search(query=query, max_results=max_results)
                if results:
                    return ToolResult(
                        tool_name=self.name,
                        success=True,
                        output={
                            "query": query,
                            "count": len(results),
                            "results": [r.to_dict() for r in results],
                            "provider": provider.name,
                        },
                        metadata={"provider": provider.name},
                    )
            except Exception as err:  # pylint: disable=broad-except
                self._logger.warning("Search provider '%s' failed: %s; trying fallback", provider.name, err)
                last_error = err

        # If all configured providers returned empty or failed, try guaranteed fallback
        if not last_error:
            # Query returned 0 results
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "query": query,
                    "count": 0,
                    "results": [],
                    "message": f"No web search results found for '{query}'.",
                },
            )

        return ToolResult(
            tool_name=self.name,
            success=False,
            error=f"Web search failed: {last_error}",
        )

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect query to identify search intent."""
        lowered = user_input.lower().strip()

        search_patterns = (
            r"\b(?:search\s+the\s+web\s+for|search\s+for|google|web\s+search\s+for|look\s+up\s+on\s+the\s+web|find\s+info\s+on)\s+(.+)",
            r"\b(?:search\s+about|find\s+articles\s+about)\s+(.+)",
        )

        for pat in search_patterns:
            match = re.search(pat, lowered)
            if match:
                q = match.group(1).strip("?.,! ")
                if q:
                    return {"query": q}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format search results for friendly user consumption."""
        if not result.is_success():
            return f"I wasn't able to complete the web search: {result.error}"

        out = result.output
        if isinstance(out, dict):
            query = out.get("query", "")
            items = out.get("results", [])
            if not items:
                return f"I couldn't find any web search results for '{query}'."

            formatted_items: list[str] = []
            for i, item in enumerate(items, 1):
                title = item.get("title", "Untitled")
                url = item.get("url", "")
                snippet = item.get("snippet", "")
                formatted_items.append(f"{i}. [{title}]({url})\n   {snippet}")

            body = "\n\n".join(formatted_items)
            return f"Here is what I found for '{query}':\n\n{body}"

        return result.to_text()
