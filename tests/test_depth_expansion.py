import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from app.tools.search import search_web
from app.tools.fetch import fetch_page_text

async def main():
    domain = "zamp.ai"
    print(f"--- 1. Direct fetch for https://{domain} ---")
    page_text = await fetch_page_text(f"https://{domain}")
    print(f"Fetched {len(page_text)} chars.")
    print("Excerpt:\n", page_text[:300])

    print(f"\n--- 2. Expanded Search for {domain} ---")
    results = await search_web(f'"{domain}" (agents OR operations OR "case studies" OR reviews)', max_results=8)
    print(f"Found {len(results)} results:")
    for r in results:
        print(f"- {r['title']} ({r['url']})")

if __name__ == "__main__":
    asyncio.run(main())
