import logging
from typing import Optional
from app.tools.cache import get_cached, set_cached
from app.tools.http_client import get_http_client

logger = logging.getLogger(__name__)

async def fetch_page_text(url: str, max_chars: int = 4000) -> str:
    """
    Fetches clean Markdown/text from a URL using Jina Reader or direct HTTP fallback.
    """
    cache_key = f"fetch:{url}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached[:max_chars]

    # Try Jina Reader
    jina_url = f"https://r.jina.ai/{url}"
    client = get_http_client()
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.get(jina_url, headers=headers, timeout=8.0)
        if res.status_code == 200 and len(res.text.strip()) > 100:
            text = res.text.strip()[:max_chars]
            set_cached(cache_key, "fetch", text, ttl_seconds=86400 * 7)
            return text
    except Exception as e:
        logger.debug(f"Jina fetch failed for {url}: {e}")

    # Fallback to direct fetch
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = await client.get(url, headers=headers, timeout=6.0)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = " ".join(soup.stripped_strings)[:max_chars]
            if text:
                set_cached(cache_key, "fetch", text, ttl_seconds=86400 * 7)
                return text
    except Exception as e:
        logger.debug(f"Direct fetch failed for {url}: {e}")

    return ""
