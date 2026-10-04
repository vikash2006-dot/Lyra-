"""Search providers package for LYRA."""

from lyra.tools.search_providers.base import SearchProvider, SearchResult
from lyra.tools.search_providers.duckduckgo import DuckDuckGoSearchProvider
from lyra.tools.search_providers.tavily import TavilySearchProvider

__all__ = [
    "SearchProvider",
    "SearchResult",
    "DuckDuckGoSearchProvider",
    "TavilySearchProvider",
]
