import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import uuid
import pytest
from app.db import init_db, get_run
from app.orchestrator import start_run, resume_with_clarification

@pytest.mark.anyio
async def test_live_clarification_loop():
    init_db()
    from app.db import insert_run
    run_id = f"test_merc_{uuid.uuid4().hex[:6]}"
    insert_run(run_id, "Mercury", {}, "fast")
    print(f"--- 1. Starting initial run for 'Mercury' ({run_id}) ---")
    await start_run(run_id, "Mercury", hints={}, mode="fast")
    
    run = get_run(run_id)
    print("Run Status after start:", run["status"])
    print("Confidence:", run["confidence"])
    assert run["status"] == "awaiting_clarification"
    
    print("\n--- 2. Submitting vague answer (Round 1) ---")
    await resume_with_clarification(run_id, answers={"q_0": "It is an operating business"})
    run = get_run(run_id)
    print("Run Status after vague answer:", run["status"])
    print("Confidence:", run["confidence"])
    assert run["status"] == "awaiting_clarification"
    
    print("\n--- 3. Submitting separating answer (Round 2) ---")
    # Provide the distinguishing info: fintech banking for startups
    await resume_with_clarification(run_id, answers={"q_1": "It is the US fintech business banking platform for startups"})
    run = get_run(run_id)
    print("Run Status after separating answer:", run["status"])
    print("Confidence:", run["confidence"])
    print("Confirmed Target Domain:", run["confirmed_company"]["domain"])
    assert run["confidence"] >= 0.80
    assert run["confirmed_company"]["domain"] == "mercury.com"
    print("\nSUCCESS: Multi-turn clarification loop kept asking questions until the threshold was crossed and confirmed the exact right company!")

if __name__ == "__main__":
    asyncio.run(test_live_clarification_loop())
