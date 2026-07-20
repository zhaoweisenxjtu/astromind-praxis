from abc import ABC, abstractmethod
from typing import Optional


class SearchStrategy(ABC):
    """All search strategies must implement this interface.

    Returns:
        None if the strategy is unavailable (no API key, network error).
        Empty list if search returned no results.
        List of dicts with keys: title, url, content, source.
    """

    @abstractmethod
    def search(self, query: str, max_results: int = 10, **kwargs) -> Optional[list[dict]]:
        pass
