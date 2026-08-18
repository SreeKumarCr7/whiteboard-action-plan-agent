import os

from tavily import TavilyClient


class TavilyConfigError(Exception):
    """Raised when the Tavily API key is missing."""


class TavilyServiceError(Exception):
    """Raised when a Tavily query fails."""


def _get_client():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise TavilyConfigError(
            "Tavily API key is not configured. Set TAVILY_API_KEY as an "
            "environment variable."
        )
    return TavilyClient(api_key=api_key)


def research_terms(terms):
    """Look up each term via Tavily. Returns {term: {summary, source_url}}."""
    if not terms:
        return {}
    try:
        client = _get_client()
    except TavilyConfigError:
        raise
    result = {}
    for term in terms:
        try:
            response = client.search(
                query=term, search_depth="basic", max_results=3
            )
            results = (response or {}).get("results", [])
            if not results:
                result[term] = {
                    "summary": "No reliable information found",
                    "source_url": None,
                }
                continue
            top = results[0]
            content = (top.get("content") or "").strip()
            if not content:
                result[term] = {
                    "summary": "No reliable information found",
                    "source_url": None,
                }
                continue
            result[term] = {
                "summary": content,
                "source_url": top.get("url"),
            }
        except Exception as exc:  # noqa: BLE001 - surface as service error
            raise TavilyServiceError(
                f"Tavily query failed for '{term}': {exc}"
            ) from exc
    return result
