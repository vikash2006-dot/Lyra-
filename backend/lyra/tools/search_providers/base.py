"""Base abstractions for search providers in LYRA."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """Canonical model for a single web search result item."""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }


class SearchProvider(ABC):
    """Abstract base class for search provider adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name (e.g. 'duckduckgo', 'tavily')."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Indicate whether the provider has required credentials or network availability."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute web search and return structured search results.

        Args:
            query: Search query string.
            max_results: Maximum number of results to retrieve.

        Returns:
            List of SearchResult objects.
        """
