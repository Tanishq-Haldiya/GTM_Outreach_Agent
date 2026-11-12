import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from app.tools.search import search_web

async def main():
    print("--- Query 1: Unkeyed (Zamp) ---")
    res1 = await search_web("Zamp Glassdoor employee reviews manual workload internal tools", max_results=4)
    for r in res1:
        print(r['title'], "-->", r['url'])

    print("\n--- Query 2: Keyed to Domain (zamp.com OR zamp.ai) ---")
    res2 = await search_web('"zamp.com" OR "zamp.ai" operations OR hiring OR employee reviews', max_results=4)
    for r in res2:
        print(r['title'], "-->", r['url'])

if __name__ == "__main__":
    asyncio.run(main())
