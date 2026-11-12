import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
import uuid
from app.db import init_db, get_run_full_details, insert_run
from app.orchestrator import start_run

async def main():
    init_db()
    run_id = f"test_ramp_{uuid.uuid4().hex[:6]}"
    print("Initiating full end-to-end pipeline run for Ramp...")
    t0 = time.time()
    insert_run(run_id, "Ramp", {"website_hint": "ramp.com"}, "fast")
    await start_run(run_id, "Ramp", {"website_hint": "ramp.com"}, mode="fast")
    total = time.time() - t0
    print(f"\nPipeline finished in {total:.2f} seconds.")

    details = get_run_full_details(run_id)
    run = details["run"]
    print("\n================== RUN SUMMARY ==================")
    print(f"Status: {run['status']}")
    print(f"Confidence: {run['confidence']}")
    print(f"Recorded Duration: {run['duration']}s")

    evidence = details["evidence"]
    print(f"\n================== EVIDENCE GATHERED ({len(evidence)} items) ==================")
    for ev in evidence[:4]:
        print(f"[{ev['researcher']}] Tier {ev['reliability_tier']}: {ev['claim']}")
        print(f"   Excerpt: '{ev['excerpt'][:120]}...'")

    hypotheses = details["hypotheses"]
    print(f"\n================== PROBLEM DISCOVERY ({len(hypotheses)} hypotheses) ==================")
    for h in hypotheses:
        star = " [WINNER]" if h['id'] == run.get('selected_hypothesis_id') else ""
        print(f"[{h['layer'].upper()}] (Score: {h['final_score']:.2f}){star} Lens: {h['lens']}")
        print(f"   Problem: {h['problem']}")
        print(f"   Rationale: {h['rationale']}")

    sol = details["solution"]
    if sol:
        print("\n================== SOLUTION ARCHITECTURE (S5) ==================")
        print(f"Process: {sol.get('process_name')}")
        print(f"What it automates: {sol.get('what_it_automates')}")
        print(f"Input: {sol.get('input_consumed')}")
        print(f"Impact: {sol.get('impact_direction')}")

    draft = details["draft"]
    if draft:
        print("\n================== OUTREACH DRAFT (S6 / S7) ==================")
        print(f"Subject: {draft.get('subject')}")
        print(f"Word Count: {len(draft.get('body', '').split())} words")
        print("\nEmail Body:")
        print(draft.get("body"))
        print("\nLinkedIn Note:")
        print(draft.get("linkedin_note"))
        print("\nInternal SDR Guidance:")
        print(draft.get("why_this_hook"))
        print("\nQA Quality Report:")
        print(draft.get("quality_report"))

if __name__ == "__main__":
    asyncio.run(main())
