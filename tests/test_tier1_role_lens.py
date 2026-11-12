import pytest
from app.models import ProblemHypothesis, EvidenceItem
from app.roles import (
    load_roles_config, clean_title_string, match_role_in_config,
    detect_seniority, canonical_lens, normalize_recipient_role,
    get_role_fit_multiplier, suggest_roles_for_lens
)
from app.stages.s4_score import score_and_select_hypothesis

# 1. Test 30 sample titles map accurately to lenses and seniority
SAMPLE_TITLES_30 = [
    # Finance
    ("CFO", "finance ops", "c_level_or_vp"),
    ("VP Finance", "finance ops", "c_level_or_vp"),
    ("Controller", "finance ops", "director_or_head"),
    ("Head of AP or AR", "finance ops", "director_or_head"),
    ("Head of Accounts Payable", "finance ops", "director_or_head"),
    ("Finance Director", "finance ops", "director_or_head"),
    # Procurement
    ("CPO", "procurement", "c_level_or_vp"),
    ("Head of Procurement", "procurement", "director_or_head"),
    ("Sourcing Lead", "procurement", "director_or_head"),
    # Supply Chain & Logistics
    ("Head of Supply Chain", "supply chain and logistics", "director_or_head"),
    ("Logistics Lead", "supply chain and logistics", "director_or_head"),
    ("VP Logistics", "supply chain and logistics", "c_level_or_vp"),
    # HR & People
    ("CHRO", "HR and recruiting", "c_level_or_vp"),
    ("Head of People", "HR and recruiting", "director_or_head"),
    ("Head of Talent", "HR and recruiting", "director_or_head"),
    ("VP HR", "HR and recruiting", "c_level_or_vp"),
    # Support & CX
    ("Head of Support", "customer support", "director_or_head"),
    ("CX Lead", "customer support", "director_or_head"),
    ("VP Customer Experience", "customer support", "c_level_or_vp"),
    # Sales & RevOps
    ("CRO", "sales and GTM ops", "c_level_or_vp"),
    ("VP Sales", "sales and GTM ops", "c_level_or_vp"),
    ("Head of RevOps", "sales and GTM ops", "director_or_head"),
    ("Head of GTM", "sales and GTM ops", "director_or_head"),
    # Compliance & Risk
    ("Chief Compliance Officer", "compliance and KYC", "c_level_or_vp"),
    ("MLRO", "compliance and KYC", "c_level_or_vp"),
    ("Head of Risk", "compliance and KYC", "director_or_head"),
    # IT & Engineering
    ("CIO", "IT ops", "c_level_or_vp"),
    ("CTO", "IT ops", "c_level_or_vp"),
    ("Head of IT", "IT ops", "director_or_head"),
    # Legal
    ("General Counsel", "legal and contracts", "c_level_or_vp"),
    # Data & Analytics
    ("Head of Data", "data and reporting", "director_or_head"),
    # Claims
    ("Head of Claims", "claims and case handling", "director_or_head"),
    # Executive / Operations
    ("CEO", "broad (neutral weights)", "c_level_or_vp"),
    ("COO", "broad (neutral weights)", "c_level_or_vp"),
    ("Head of Operations", "broad (neutral weights)", "director_or_head")
]

@pytest.mark.anyio
async def test_30_sample_titles_mapping():
    """Build step 2: 30 sample titles map as expected, and unknown titles degrade to broad."""
    for title, expected_lens, expected_seniority in SAMPLE_TITLES_30:
        res = await normalize_recipient_role(title)
        assert res["lens"] == expected_lens, f"Title '{title}' mapped to lens '{res['lens']}', expected '{expected_lens}'"
        assert res["seniority"] == expected_seniority, f"Title '{title}' mapped to seniority '{res['seniority']}', expected '{expected_seniority}'"

@pytest.mark.anyio
async def test_unknown_title_degrades_to_broad():
    """Unknown or odd title falls back to broad role with visible chip flag."""
    res = await normalize_recipient_role("Chief Galaxy Wizard 9000")
    assert res["lens"] == "broad (neutral weights)"
    assert res["role_unrecognized"] is True or res["confidence"] < 0.60

def test_deterministic_role_fit_ranking():
    """
    Build step 4: Fixed hypothesis set ranks deterministically for each role.
    Role fit factors: primary 1.0, adjacent 0.85, any other 0.60.
    """
    ev1 = EvidenceItem(
        id="ev_fin", researcher="filings", source_type="sec_filing",
        url="https://test.com/fin", title="Financial Discrepancy",
        claim="Invoice reconciliation cycle time is 14 days",
        excerpt="Invoice reconciliation takes 14 days manually",
        signal_type="friction", reliability_tier="A", authority_score=0.95
    )
    ev2 = EvidenceItem(
        id="ev_cs", researcher="customer_voice", source_type="review",
        url="https://test.com/cs", title="Customer Delays",
        claim="Users report 48-hour wait times on support tickets",
        excerpt="Support queue currently averages 48 hours",
        signal_type="friction", reliability_tier="B", authority_score=0.85
    )

    hyp_finance = ProblemHypothesis(
        id="hyp_fin",
        problem="Manual invoice exception reconciliation slows monthly close",
        lens="finance ops",
        layer="stated",
        evidence_ids=["ev_fin"],
        evidence_strength=0.9,
        business_impact=0.8,
        automatability=0.85,
        timeliness=0.8,
        buyer_credibility=0.8
    )

    hyp_support = ProblemHypothesis(
        id="hyp_cs",
        problem="High support ticket triage latency during billing disputes",
        lens="customer support",
        layer="stated",
        evidence_ids=["ev_cs"],
        evidence_strength=0.9,
        business_impact=0.8,
        automatability=0.85,
        timeliness=0.8,
        buyer_credibility=0.8
    )

    hypotheses = [hyp_finance, hyp_support]
    evidence = [ev1, ev2]

    # When recipient is CFO (finance ops is primary, customer support is other lens)
    ranked_cfo, winner_cfo, hook_cfo = score_and_select_hypothesis(
        [hyp.model_copy() for hyp in hypotheses],
        evidence,
        recipient_lens="finance ops",
        adjacent_lenses=["data and reporting", "compliance and KYC"]
    )
    assert winner_cfo.lens == "finance ops"
    assert winner_cfo.role_fit == 1.0
    assert winner_cfo.role_fit_badge == "primary"
    
    # Check that customer support was discounted to 0.60
    cs_hyp = next(h for h in ranked_cfo if h.lens == "customer support")
    assert cs_hyp.role_fit == 0.60
    assert cs_hyp.role_fit_badge == "other"

    # When recipient is Head of Support (customer support is primary)
    ranked_cs, winner_cs, hook_cs = score_and_select_hypothesis(
        [hyp.model_copy() for hyp in hypotheses],
        evidence,
        recipient_lens="customer support",
        adjacent_lenses=["data and reporting"]
    )
    assert winner_cs.lens == "customer support"
    assert winner_cs.role_fit == 1.0
    assert winner_cs.role_fit_badge == "primary"

def test_fallback_banner_and_better_fit_hints():
    """
    Section 4.4 Fallback:
    If no problem in the primary or adjacent lenses has base score >= 0.35,
    draft for best company-level problem and show banner and better-fit suggestions.
    """
    ev = EvidenceItem(
        id="ev_cs", researcher="customer_voice", source_type="review",
        url="https://test.com/cs", title="Support Latency",
        claim="Support response backlog is 3 days",
        excerpt="Support queue takes 3 days",
        signal_type="friction", reliability_tier="B", authority_score=0.85
    )

    # Only customer support problem exists with strong score
    hyp_support = ProblemHypothesis(
        id="hyp_cs",
        problem="High customer support ticket backlog",
        lens="customer support",
        layer="stated",
        evidence_ids=["ev_cs"],
        evidence_strength=0.9,
        business_impact=0.85,
        automatability=0.8,
        timeliness=0.8,
        buyer_credibility=0.85
    )

    # Target role is CFO (primary: finance ops, adjacent: data & compliance).
    # Customer support is neither primary nor adjacent.
    ranked, winner, hook, fb_info = score_and_select_hypothesis(
        [hyp_support],
        [ev],
        recipient_lens="finance ops",
        adjacent_lenses=["data and reporting", "compliance and KYC"],
        return_fallback_info=True
    )

    assert fb_info["fallback_banner_used"] is True
    assert "No strong problem was found in this role's area" in fb_info["banner_message"]
    # Reverse lookup suggestions for customer support
    assert len(fb_info["suggested_roles"]) > 0
    assert any("support" in r.lower() or "cx" in r.lower() for r in fb_info["suggested_roles"])

def test_tier0_non_regression_with_no_inputs():
    """
    Section 4.8 & 8 Non-regression test:
    With no recipient role/name, outputs match Tier 0 exactly.
    """
    ev = EvidenceItem(
        id="ev_1", researcher="careers", source_type="careers",
        url="https://test.com/ops", title="Hiring Surge",
        claim="Company is hiring 10 manual operations analysts",
        excerpt="Hiring 10 manual operations analysts",
        signal_type="operational_strain", reliability_tier="A", authority_score=0.90
    )
    hyp = ProblemHypothesis(
        id="hyp_1",
        problem="Manual back-office coordination bottlenecks",
        lens="operations",
        layer="implied",
        evidence_ids=["ev_1"],
        evidence_strength=0.75,
        business_impact=0.80,
        automatability=0.80,
        timeliness=0.70,
        buyer_credibility=0.75
    )

    # Calling with None recipient
    ranked, winner, hook = score_and_select_hypothesis([hyp], [ev], recipient_lens=None)
    assert winner.role_fit == 1.0
    assert winner.role_fit_badge == "broad"
    assert winner.final_score == winner.base_score
