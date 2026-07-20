"""Knowledge retrieval — query interface above indexing layer."""

from typing import Optional
from .indexing import load_index, query_index, list_sources, build_index, save_index


# Global cache (lazy-loaded on first use)
_index_cache = None


def get_index(force_rebuild: bool = False):
    """Get or load the BM25 index (cached)."""
    global _index_cache
    if _index_cache is None or force_rebuild:
        if force_rebuild:
            _index_cache = build_index()
            save_index(_index_cache)
        else:
            _index_cache = load_index()
    return _index_cache


def search(query: str, top_k: int = 5, scope: Optional[str] = None) -> list[dict]:
    """Search knowledge base.

    Args:
        query: Natural language query
        top_k: Max results
        scope: Optional category filter ("core", "methods", "references", etc.)

    Returns:
        List of relevant chunks with scores
    """
    idx = get_index()
    results = query_index(query, idx, top_k=top_k * 3)

    if scope:
        results = [r for r in results if r["category"] == scope]

    return results[:top_k]


def sources() -> list[dict]:
    """List available knowledge sources."""
    idx = get_index()
    return list_sources(idx)


def rebuild():
    """Force rebuild the index from scratch."""
    global _index_cache
    _index_cache = build_index()
    save_index(_index_cache)
    return len(_index_cache["chunks"])
