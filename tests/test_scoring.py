import pytest
from app.models import ProblemHypothesis, EvidenceItem
from app.stages.s4_score import score_and_select_hypothesis
from app.config import SCORE_WEIGHTS, LAYER_MULTIPLIERS

def test_hypothesis_scoring_and_ranking():
    ev1 = EvidenceItem(
        id="ev_1",
        researcher="hiring",
        source_type="careers",
        url="https://example.com/jobs",
        title="Job Board",
        claim="Hiring 12 AP accountants to handle manual invoice discrepancies",
        excerpt="We need AP specialists to manually match invoices to POs",
        signal_type="manual_process",
        reliability_tier="A"
    )

    hyp_stated = ProblemHypothesis(
        id="hyp_stated",
        problem="High invoice exception volume requiring manual matching",
        lens="finance_ops",
        layer="stated",
        evidence_ids=["ev_1"],
        evidence_strength=1.0,
        business_impact=0.9,
        automatability=0.9,
        timeliness=0.8,
        buyer_credibility=0.85
    )

    hyp_inferred = ProblemHypothesis(
        id="hyp_inferred",
        problem="Potential delay in customer support resolution times",
        lens="customer_support",
        layer="inferred",
        evidence_ids=["ev_1"],
        evidence_strength=0.3,
        business_impact=0.6,
        automatability=0.7,
        timeliness=0.5,
        buyer_credibility=0.6
    )

    ranked, winner, hook = score_and_select_hypothesis([hyp_inferred, hyp_stated], [ev1])

    # Stated hypothesis with high scores and 1.0 layer multiplier should win
    assert winner.id == "hyp_stated"
    assert ranked[0].id == "hyp_stated"
    assert ranked[1].id == "hyp_inferred"
    assert hook.id == "ev_1"
    assert winner.final_score > ranked[1].final_score

def test_layer_multipliers():
    assert LAYER_MULTIPLIERS["stated"] == 1.0
    assert LAYER_MULTIPLIERS["implied"] == 0.9
    assert LAYER_MULTIPLIERS["inferred"] == 0.6

def test_quantitative_source_authority_and_breakdown():
    from app.stages.s2_research import compute_source_authority
    
    # Official SEC / Compliance / Status should have >= 0.95 authority
    sec_auth = compute_source_authority("https://www.sec.gov/edgar/data/ramp", "sec_filing", "A")
    assert sec_auth >= 0.95

    # Status incident on statuspage.io should have >= 0.95 authority
    status_auth = compute_source_authority("https://status.ramp.com", "status_incident", "A")
    assert status_auth >= 0.95

    # Structured reviews should have ~ 0.80 - 0.88 authority
    g2_auth = compute_source_authority("https://www.g2.com/products/ramp/reviews", "review", "B")
    assert 0.80 <= g2_auth <= 0.88

    # Community forums should have ~ 0.70 - 0.80 authority
    reddit_auth = compute_source_authority("https://reddit.com/r/ramp", "community", "C")
    assert 0.70 <= reddit_auth <= 0.80

    # Ensure score_breakdown is populated in S4
    ev = EvidenceItem(
        id="ev_sec",
        researcher="compliance_and_regulatory",
        source_type="compliance",
        url="https://sec.gov/filing",
        title="SEC 10-K",
        claim="Multi-state sales tax nexus expansion triggers audit exposure",
        excerpt="We expanded sales tax compliance requirements across 42 states.",
        signal_type="compliance_risk",
        reliability_tier="A",
        authority_score=sec_auth
    )
    hyp = ProblemHypothesis(
        id="hyp_comp",
        problem="Multi-state sales tax nexus calculation and audit exposure",
        lens="compliance_kyc",
        layer="stated",
        evidence_ids=["ev_sec"],
        evidence_strength=0.9,
        business_impact=0.85,
        automatability=0.85,
        timeliness=0.85,
        buyer_credibility=0.9
    )
    ranked, winner, hook = score_and_select_hypothesis([hyp], [ev])
    assert winner.score_breakdown is not None
    assert winner.score_breakdown["avg_source_authority"] == sec_auth
    assert "layer_mult" in winner.score_breakdown
