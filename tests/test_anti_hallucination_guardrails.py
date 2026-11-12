import pytest
from app.models import CompanyIdentity, EvidenceItem, ProblemHypothesis
from app.stages.s2_research import _is_evidence_claim_valid, _crawl_official_website, _is_result_relevant_to_entity
from app.stages.s3_discovery import _is_hypothesis_grounded_and_realistic
from app.config import AGGREGATOR_DOMAINS, AGGREGATOR_BRANDS

def test_aggregator_domains_configured():
    assert "rocketreach.co" in AGGREGATOR_DOMAINS
    assert "zoominfo.com" in AGGREGATOR_DOMAINS
    assert "apollo.io" in AGGREGATOR_DOMAINS
    assert "rocketreach" in AGGREGATOR_BRANDS
    assert "zoominfo" in AGGREGATOR_BRANDS

def test_evidence_claim_guardrail_rejects_aggregator_pitch():
    company = CompanyIdentity(
        name="ARB Bearings Limited",
        domain="arb-bearings.com",
        industry="Automotive & Industrial Bearings Manufacturing",
        confidence=0.95,
        status="confirmed"
    )

    # 1. Exact case reported by user: RocketReach marketing excerpt
    bad_claim = "RocketReach offers AI-powered recommendations and an AI-writer to help users craft outreach messages faster."
    bad_excerpt = "Boost outreach with AI-powered recommendations and Messages' AI-writer to help you connect smarter and faster"
    assert not _is_evidence_claim_valid(bad_claim, bad_excerpt, company)

    # 2. Another aggregator pitch
    bad_claim_2 = "ZoomInfo provides direct dials and verified business emails for ARB Bearings employees."
    bad_excerpt_2 = "Find contact info and phone numbers for ARB Bearings staff with free trial."
    assert not _is_evidence_claim_valid(bad_claim_2, bad_excerpt_2, company)

    # 3. Valid first-party industrial fact about ARB Bearings
    good_claim = "ARB Bearings manufactures precision deep groove ball bearings and taper roller bearings across its Delhi manufacturing units."
    good_excerpt = "With over 70 years of experience, ARB Bearings operates state-of-the-art facilities producing bearings for automotive and industrial clients."
    assert _is_evidence_claim_valid(good_claim, good_excerpt, company)

def test_hypothesis_guardrail_rejects_unrealistic_software_for_industrial():
    industrial_company = CompanyIdentity(
        name="ARB Bearings Limited",
        domain="arb-bearings.com",
        industry="Industrial Bearings & Manufacturing",
        confidence=0.95,
        status="confirmed"
    )

    # Unrealistic software/email hypothesis
    bad_hyp = ProblemHypothesis(
        id="hyp_bad",
        problem="Lack of automated AI email writer reduces SDR outbound message speed at ARB Bearings.",
        lens="sales_ops",
        layer="implied",
        root_cause="RocketReach AI-writer integration gaps.",
        workflow_burden="Sales reps typing manual emails to bearing buyers.",
        automation_fit="Deploy AI email copywriter."
    )
    assert not _is_hypothesis_grounded_and_realistic(bad_hyp, industrial_company)

    # Unrealistic streaming/licensing hypothesis
    bad_hyp_media = ProblemHypothesis(
        id="hyp_bad2",
        problem="Cross-territory digital streaming and content licensing rights reconciliation backlog.",
        lens="legal_contracts",
        layer="inferred",
        root_cause="Fragmented digital distribution rights databases.",
        workflow_burden="Analysts verifying streaming windows.",
        automation_fit="Digital rights smart contract engine."
    )
    assert not _is_hypothesis_grounded_and_realistic(bad_hyp_media, industrial_company)

    # Realistic industrial supply chain hypothesis
    good_hyp = ProblemHypothesis(
        id="hyp_good",
        problem="Manual dealer order reconciliation and distributor invoice discrepancies create multi-day delivery backlogs.",
        lens="supply_chain_logistics",
        layer="implied",
        root_cause="Tier-2 distributor purchase orders submitted via PDF and WhatsApp images.",
        workflow_burden="Operations team cross-referencing distributor credit limits and stock availability.",
        automation_fit="Automated distributor PO extraction and inventory reservation agent."
    )
    assert _is_hypothesis_grounded_and_realistic(good_hyp, industrial_company)

import asyncio

def test_crawl_blocks_aggregator_domains():
    quarantined_company = CompanyIdentity(
        name="ARB Bearings",
        domain="rocketreach.co",
        industry="Manufacturing",
        confidence=0.7,
        status="quarantined"
    )
    # Direct crawl should immediately return empty list and refuse to crawl
    items = asyncio.run(_crawl_official_website(quarantined_company))
    assert items == []

def test_reddit_community_friction_evidence_and_hypothesis():
    matiks_company = CompanyIdentity(
        name="Matiks Mental Arithmetic Private Limited",
        domain="matiks.com",
        industry="Mobile Gaming Apps",
        confidence=0.85,
        status="confirmed"
    )

    # 1. Reddit post relevance check
    reddit_res = {
        "title": "Did anyone receive the Coupon/ rewards..? : r/matiks - Reddit",
        "url": "https://www.reddit.com/r/matiks/comments/1q34ro8/did_anyone_receive_the_coupon_rewards",
        "snippet": "Did anyone Receive the coupon/ follow up details about this reward which was awarded after new year 7 day streak..?? Even after I filled the form no mail received."
    }
    assert _is_result_relevant_to_entity(reddit_res, matiks_company)

    # 2. Evidence claim validation
    claim = "Matiks users report that physical streak gifts and coupon rewards are delayed by over a month with no confirmation emails."
    excerpt = "Did anyone Receive the coupon/ follow up details about this reward which was awarded after new year 7 day streak"
    assert _is_evidence_claim_valid(claim, excerpt, matiks_company)

    # 3. Grounded hypothesis check
    hyp = ProblemHypothesis(
        id="hyp_rewards",
        problem="Manual streak reward redemption and milestone gift fulfillment (hoodies, t-shirts, cakes) create multi-week delivery backlogs.",
        lens="fulfillment_ops",
        layer="stated",
        root_cause="Manual address collation and disconnected third-party courier dispatch.",
        workflow_burden="Support team manually fielding Reddit and Discord tickets about delayed shipments.",
        automation_fit="Automated address verification, carrier API integration (e.g., Shiprocket/Delhivery), and real-time tracking webhook updates."
    )
    assert _is_hypothesis_grounded_and_realistic(hyp, matiks_company)

@pytest.mark.anyio
async def test_s7_repair_deterministic_verification_rejects_invented_metrics():
    """Finding #9: S7 autonomous repair must be deterministically checked before accepting."""
    from unittest.mock import AsyncMock, patch
    from app.models import OutreachDraft
    from app.stages.s7_check import verify_grounding

    ev = EvidenceItem(
        id="ev_1", researcher="official_overview", source_type="website",
        url="https://acme.com", title="Acme", claim="Acme operates across 5 regions",
        excerpt="Acme operates across 5 regions", signal_type="expansion", reliability_tier="A"
    )
    draft = OutreachDraft(
        id="d1", subject="ops question", body="Hi Acme Team,\n\nWe love your work.\n\nBest,\nTanishq",
        linkedin_note="Hi", why_this_hook="hook", selected_hook_id="ev_1"
    )

    # Bad repair that hallucinates a 74% savings metric not in the evidence
    bad_repair = {
        "passed_swap_test": False,
        "swap_test_notes": "Too generic",
        "repair_suggestion": "Hi Acme Team,\n\nWe saw you operate across 5 regions. We helped peers cut cycle times by 74% using automated triage.\n\nBest,\nTanishq"
    }
    with patch("app.stages.s7_check.call_llm", new_callable=AsyncMock) as m:
        m.return_value = bad_repair
        v_draft, rep = await verify_grounding(draft, "Acme", [ev])
        # The repair with uncited metric must be rejected and original draft preserved
        assert any("repair rejected" in n for n in rep.notes)
        assert v_draft.body == draft.body

    # Clean repair with grounded facts only
    good_repair = {
        "passed_swap_test": False,
        "swap_test_notes": "Too generic",
        "repair_suggestion": "Hi Acme Team,\n\nSaw that Acme recently noted operations across 5 regions. With that scale, teams often face manual coordination bottlenecks. We build automated workflow pipelines to reconcile cross-system items.\n\nOpen to comparing notes?\n\nBest,\nTanishq"
    }
    with patch("app.stages.s7_check.call_llm", new_callable=AsyncMock) as m:
        m.return_value = good_repair
        v_draft, rep = await verify_grounding(draft, "Acme", [ev])
        assert rep.repaired is True
        assert "5 regions" in v_draft.body
