import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from app.models import CompanyIdentity, EvidenceItem, ProblemHypothesis
from app.stages.s4_score import score_and_select_hypothesis
from app.stages.s5_solution import design_solution
from app.stages.s6_draft import generate_draft
from app.stages.s7_check import verify_grounding

@pytest.mark.anyio
async def test_descending_ranking_and_interactive_selection():
    evidence = [
        EvidenceItem(
            id="ev_tax_notice",
            researcher="hiring_and_operations",
            source_type="careers",
            url="https://zamp.ai/careers",
            title="Tax Notice Specialist at Zamp",
            claim="Zamp is hiring specialists to review and resolve state tax agency notices manually.",
            excerpt="Reviewing state sales tax notices, tracking discrepancies, and coordinating agency responses.",
            signal_type="manual_process",
            reliability_tier="A"
        ),
        EvidenceItem(
            id="ev_shopify_volume",
            researcher="integrations_and_tools",
            source_type="website",
            url="https://zamp.ai/integrations",
            title="Zamp Shopify & Stripe Integration",
            claim="Zamp connects to high-volume multi-state e-commerce channels with automated tax calculations.",
            excerpt="Real-time multi-state calculations across Shopify, BigCommerce, and custom ERPs.",
            signal_type="tool_stack",
            reliability_tier="A"
        )
    ]

    hypotheses = [
        ProblemHypothesis(
            id="hyp_inferred",
            problem="Multi-state jurisdiction nexus threshold tracking causes end-of-month reconciliation delays.",
            lens="finance_ops",
            lens_explanation="High-growth sellers trigger economic nexus unexpectedly across 45+ states.",
            layer="inferred",
            evidence_ids=["ev_shopify_volume"],
            evidence_strength=0.6,
            business_impact=0.7,
            automatability=0.8,
            timeliness=0.6,
            buyer_credibility=0.7,
            root_cause="Sudden transaction spikes triggering nexus without real-time tracking.",
            workflow_burden="Finance teams manually monitoring sales threshold sheets.",
            automation_fit="Automated threshold monitors that trigger registration workflows."
        ),
        ProblemHypothesis(
            id="hyp_stated",
            problem="Manual processing of high-volume state tax agency notices creates operational backlog.",
            lens="tax_filing_ops",
            lens_explanation="State tax departments send physical and PDF notices with strict 30-day response deadlines.",
            layer="stated",
            evidence_ids=["ev_tax_notice"],
            evidence_strength=0.9,
            business_impact=0.9,
            automatability=0.9,
            timeliness=0.85,
            buyer_credibility=0.9,
            root_cause="Jurisdictional notice variability and unstructured PDF formats.",
            workflow_burden="Tax analysts manually opening mail, logging notice codes, and researching ledger records.",
            automation_fit="OCR ingestion, document classification, and automated reconciliation against filings."
        )
    ]

    # Test S4: Scores and ranks descending
    ranked, winner, hook_ev = score_and_select_hypothesis(hypotheses, evidence)
    assert ranked[0].id == "hyp_stated", "Stated hypothesis with high scores should be rank #1"
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2
    assert ranked[0].final_score > ranked[1].final_score

    # Test Manual Selection of Rank #2 (Interactive Human Choice)
    chosen_hyp = ranked[1] # User chooses #2
    assert chosen_hyp.id == "hyp_inferred"
    
    # Generate S5 Solution for the chosen problem
    sol = await design_solution("Zamp", chosen_hyp, hook_ev)
    assert sol.process_name
    assert sol.hypothesis_id == chosen_hyp.id

    # Generate S6 Draft for the chosen problem
    draft = await generate_draft("Zamp", chosen_hyp, hook_ev, sol)
    assert len(draft.body.split()) >= 60
    assert "Hi" in draft.body
    assert "Best," in draft.body

    # Verify S7 Grounding
    verified_draft, report = await verify_grounding(draft, "Zamp", evidence)
    assert verified_draft.quality_verdict in ["pass", "pass_with_repair", "review_recommended"]
    # Ensure draft body was not corrupted by QA critique
    assert "fundamentally flawed" not in verified_draft.body.lower()
    print("\nSUCCESS: Verified descending ranking, structured problem diagnosis, and manual hypothesis selection.")

@pytest.mark.anyio
async def test_select_problem_cached_run_persistence():
    import time
    from app.demo_cache import create_and_seed_cached_run
    from app.orchestrator import generate_pipeline_for_hypothesis
    from app.db import get_run_full_details

    run_id = f"test_sel_cached_{time.time()}"
    create_and_seed_cached_run(run_id, 'drishti_matiks', 'Matiks', 'Drishti Pandita', {})
    
    details_init = get_run_full_details(run_id)
    assert len(details_init["hypotheses"]) >= 2
    hyp1 = details_init["hypotheses"][0]
    hyp2 = details_init["hypotheses"][1]
    assert hyp1["id"] != hyp2["id"]

    # Initial state should point to hyp1
    assert details_init["solution"]["hypothesis_id"] == hyp1["id"]

    # Switch to hyp2
    await generate_pipeline_for_hypothesis(run_id, hyp2["id"])

    details_after = get_run_full_details(run_id)
    assert details_after["run"]["selected_hypothesis_id"] == hyp2["id"]
    assert details_after["solution"]["hypothesis_id"] == hyp2["id"]
    assert details_after["draft"]["hypothesis_id"] == hyp2["id"]
    assert details_after["run"]["status"] == "pending_review"

def test_select_problem_endpoint_and_sse_query_param():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.demo_cache import create_and_seed_cached_run
    from app.db import get_run_full_details
    import time

    client = TestClient(app)
    run_id = f"test_sel_ep_{time.time()}"
    create_and_seed_cached_run(run_id, 'pedro_brex', 'Brex', 'Pedro Franceschi', {})

    details = get_run_full_details(run_id)
    alt_hyp = details["hypotheses"][1]["id"]

    # 1. Test POST /api/runs/{run_id}/select_problem
    with patch("app.main.generate_pipeline_for_hypothesis", new_callable=AsyncMock):
        resp = client.post(f"/api/runs/{run_id}/select_problem", json={"hypothesis_id": alt_hyp})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["hypothesis_id"] == alt_hyp

    # 2. Test SSE endpoint accepts ?last_id= parameter
    from app.events import emit_event
    from app.db import update_run_status
    asyncio.run(emit_event(run_id, "s7_check", "run_completed", "Finished", payload={}))
    update_run_status(run_id, "pending_review")

    sse_resp = client.get(f"/api/runs/{run_id}/events?last_id=0")
    assert sse_resp.status_code == 200
    assert "text/event-stream" in sse_resp.headers["content-type"]
    assert "run_completed" in sse_resp.text

