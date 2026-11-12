import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
from app.tools.search import search_web
from app.llm.router import call_llm

async def main():
    for name in ["Mercury", "Apollo"]:
        res = await search_web(f"{name} company official website overview", max_results=6)
        snippets = "\n".join([f"- {r['title']}: {r['snippet']} (URL: {r['url']})" for r in res])
        prompt = f"""User searched for company: "{name}".
Search snippets:
{snippets}

Identify the distinct plausible companies named "{name}" (or containing "{name}").
Return JSON with key "candidates": list of objects with:
- name: clear distinctive company name
- domain: official website domain (e.g. mercury.com, apollo.io)
- industry: industry sector
- hq: headquarters if known or blank
- description: 1 concise sentence of what they do
- distinguishing_fact: the primary fact that distinguishes it from other entities with the same name"""
        data = await call_llm(prompt, task_type="fast", json_mode=True)
        print(f"=== CANDIDATES FOR {name} ===")
        print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
