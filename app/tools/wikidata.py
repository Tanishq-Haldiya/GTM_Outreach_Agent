import logging
from typing import List, Dict, Any
from app.tools.cache import get_cached, set_cached
from app.tools.http_client import get_http_client

logger = logging.getLogger(__name__)

async def search_wikidata_entities(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Searches Wikidata Entity API for candidate business entities and organizations.
    """
    cache_key = f"wikidata:{query.lower()}:{limit}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
        "type": "item",
        "limit": limit
    }
    
    results = []
    try:
        client = get_http_client()
        headers = {"User-Agent": "AntigravityGTM/1.0 (test@gtm.org)"}
        res = await client.get(url, params=params, headers=headers, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("search", []):
                label = item.get("label", "")
                results.append({
                    "id": item.get("id"),
                    "label": label,
                    "description": item.get("description", ""),
                    "url": item.get("concepturi", "")
                })
        set_cached(cache_key, "wikidata", results, ttl_seconds=86400 * 7)
    except Exception as e:
        logger.warning(f"Wikidata search error: {e}")

    return results
