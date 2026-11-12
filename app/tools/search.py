import logging
from typing import List, Dict, Any, Optional
from app.config import TAVILY_API_KEY, SERPER_API_KEY
from app.tools.cache import get_cached, set_cached
from app.tools.http_client import get_http_client

logger = logging.getLogger(__name__)

async def search_web(
    query: str,
    max_results: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
    time_range: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Unified web search with Tavily primary and Serper fallback, backed by TTL cache.
    """
    domains_key = ",".join(include_domains) if include_domains else ""
    cache_key = f"search:{query}:{max_results}:{topic}:{domains_key}:{time_range or ''}"
    
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    results: List[Dict[str, Any]] = []
    client = get_http_client()

    # 1. Try Tavily
    if TAVILY_API_KEY:
        try:
            payload: Dict[str, Any] = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "topic": topic,
            }
            if include_domains:
                payload["include_domains"] = include_domains
            if time_range:
                payload["time_range"] = time_range

            res = await client.post("https://api.tavily.com/search", json=payload, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                for r in data.get("results", []):
                    results.append({
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("content", ""),
                        "published_date": r.get("published_date"),
                        "source": "tavily"
                    })
                if results:
                    set_cached(cache_key, "search", results, ttl_seconds=86400 * 3)
                    return results
        except Exception as e:
            logger.warning(f"Tavily search failed for '{query}': {e}. Falling back...")

    # 2. Try Serper Fallback
    if SERPER_API_KEY:
        try:
            headers = {
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json"
            }
            res = await client.post(
                "https://google.serper.dev/search",
                headers=headers,
                json={"q": query, "num": max_results},
                timeout=10.0,
            )
            if res.status_code == 200:
                data = res.json()
                for r in data.get("organic", []):
                    results.append({
                        "url": r.get("link", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "published_date": r.get("date"),
                        "source": "serper"
                    })
                if results:
                    set_cached(cache_key, "search", results, ttl_seconds=86400 * 3)
                    return results
        except Exception as e:
            logger.warning(f"Serper search fallback failed for '{query}': {e}")

    return results
