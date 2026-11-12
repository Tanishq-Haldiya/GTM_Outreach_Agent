import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from app.models import CompanyIdentity
from app.stages.s2_research import execute_research_fanout
from app.stages.s3_discovery import discover_problems

async def main():
    company = CompanyIdentity(
        name="Zamp AI",
        domain="zamp.ai",
        industry="Artificial Intelligence / Autonomous AI Employees",
        confidence=1.0,
        confirmation_method="user_selected"
    )
    print(f"Executing domain-keyed research for {company.name} ({company.domain})...")
    evidence = await execute_research_fanout(company)
    print(f"\n--- GATHERED EVIDENCE ({len(evidence)} items) ---")
    for ev in evidence:
        print(f"[{ev.researcher}] URL: {ev.url}")
        print(f"   Claim: {ev.claim}")
        print(f"   Excerpt: '{ev.excerpt[:100]}...'")

    # Verify no foreign companies (like zamp solar or zamp racing) entered
    for ev in evidence:
        assert "solar" not in ev.claim.lower(), f"Leaked solar company: {ev.claim}"
        assert "racing" not in ev.claim.lower(), f"Leaked racing company: {ev.claim}"
        assert "helmet" not in ev.claim.lower(), f"Leaked helmet company: {ev.claim}"

    print("\nRunning Problem Discovery on zamp.ai...")
    hypotheses = await discover_problems(company, evidence)
    print(f"\n--- HYPOTHESES ({len(hypotheses)} items) ---")
    for h in hypotheses:
        print(f"[{h.layer.upper()}] (Score: {h.final_score:.2f}) {h.problem}")
        print(f"   Lens: {h.lens} | Rationale: {h.rationale[:120]}...")

if __name__ == "__main__":
    asyncio.run(main())
