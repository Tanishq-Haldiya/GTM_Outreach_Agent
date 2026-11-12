import pytest
import asyncio
from app.models import CompanyIdentity, CompanyProfile, EvidenceItem, ProblemHypothesis, CompanyCandidate
from app.stages.s1_resolve import score_candidates_pool
from app.stages.s2_research import (
    _get_clean_company_name,
    _is_evidence_claim_valid,
    _is_boilerplate_url,
    _is_zero_signal_url,
    _is_inferred_only_url,
    audit_evidence_against_profile
)
from app.stages.s3_discovery import (
    _is_hypothesis_grounded_and_realistic,
    audit_problem_grounding
)

def test_boilerplate_url_filter():
    """S2 URL classification must partition zero-signal vs inferred-only pages."""
    # Zero signal (contact, about, legal)
    assert _is_zero_signal_url("https://mahalaxmibus.co.in/contact.html") is True
    assert _is_zero_signal_url("https://mahalaxmibus.co.in/contact") is True
    assert _is_zero_signal_url("https://mahalaxmibus.co.in/about-us") is True
    assert _is_zero_signal_url("https://company.com/privacy-policy") is True
    assert _is_zero_signal_url("https://company.com/parking") is True

    # Inferred-only signal (careers, branch, faq, press)
    assert _is_inferred_only_url("https://company.com/careers/senior-engineer") is True
    assert _is_inferred_only_url("https://company.com/branch/pune") is True
    assert _is_inferred_only_url("https://company.com/faq") is True
    assert _is_inferred_only_url("https://company.com/press") is True

    # Backward-compatible wrapper
    assert _is_boilerplate_url("https://mahalaxmibus.co.in/contact.html") is True
    assert _is_boilerplate_url("https://company.com/careers/senior-engineer") is True

    # Must NOT be blocked — legitimate operational / customer review signals
    assert _is_boilerplate_url("https://techcrunch.com/2024/matiks-funding") is False
    assert _is_boilerplate_url("https://reddit.com/r/mahalaxmitravels/complaints") is False
    assert _is_boilerplate_url("https://mahalaxmibus.co.in/routes") is False
    assert _is_boilerplate_url("https://mahalaxmibus.co.in/ticket-booking") is False
    assert _is_boilerplate_url("https://statuspage.io/incidents/12345") is False

def test_evidence_claim_guardrail_rejects_boilerplate_url():
    """_is_evidence_claim_valid rejects zero-signal pages, but permits inferred-signal pages."""
    company = CompanyIdentity(
        name="Mahalaxmi Travels",
        domain="mahalaxmibus.co.in",
        industry="Travel & Transportation",
        confidence=1.0
    )
    claim = "Mahalaxmi Travels provides designated phone contacts for E-Payment related issues."
    excerpt = "E-Payment related issues 6366967218"

    # From zero-signal contact page → rejected
    assert _is_evidence_claim_valid(
        claim, excerpt, company,
        url="https://www.mahalaxmibus.co.in/contact.html"
    ) is False

    # From an inferred-signal careers or branch page → allowed into evidence pool for Tier 2 Inferred discovery!
    assert _is_evidence_claim_valid(
        "Mahalaxmi is hiring 10 dispatch coordinators across Maharashtra.",
        "Hiring fleet dispatch coordinators in Pune and Mumbai.",
        company,
        url="https://www.mahalaxmibus.co.in/careers/dispatch-coordinator"
    ) is True

    # Same claim but from an editorial article → allowed
    assert _is_evidence_claim_valid(
        claim, excerpt, company,
        url="https://www.mahalaxmibus.co.in/news/payment-system-upgrade"
    ) is True

def test_clean_company_name_extraction():
    # Brand token extraction
    name = "Matiks Mental Arithmetic Private Limited"
    domain = "matiks.com"
    clean = _get_clean_company_name(name, domain)
    assert clean == "Matiks"

    name2 = "Warner Bros. Entertainment Inc."
    domain2 = "warnerbros.com"
    clean2 = _get_clean_company_name(name2, domain2)
    assert "Warner" in clean2

def test_company_profile_model_instantiation():
    profile = CompanyProfile(
        summary="Matiks is a mobile-first mental arithmetic battle and learning platform.",
        what_it_does="Offers 1v1 math duels, gamified streaks, and daily problem challenges.",
        target_consumers="Students, young gamers, and competitive math learners",
        business_model="Freemium app with in-app streaks and physical reward merchandise",
        trajectory="Pre-Series A $10M raised, 71 employees, 129% yearly growth",
        sources=["https://matiks.com", "https://techcrunch.com/matiks"]
    )
    assert profile.what_it_does.startswith("Offers")
    assert "Freemium" in profile.business_model
    assert len(profile.sources) == 2

def test_evidence_claim_guardrail_filters_aggregators():
    company = CompanyIdentity(
        name="Matiks",
        domain="matiks.com",
        industry="Mobile Gaming & EdTech",
        confidence=1.0
    )

    # Aggregator ad pitch should be rejected
    bad_claim = "RocketReach offers AI-powered recommendations and an AI-writer to help users craft outreach messages faster."
    bad_excerpt = "Boost outreach with AI-powered recommendations and Messages' AI-writer"
    assert _is_evidence_claim_valid(bad_claim, bad_excerpt, company) is False

    # Authentic Reddit complaint should be accepted
    good_claim = "Matiks users report delays exceeding 40 days for 100-day photo cakes and streak reward delivery."
    good_excerpt = "My 100-day cake from Matiks still has not arrived after waiting over a month"
    assert _is_evidence_claim_valid(good_claim, good_excerpt, company) is True

def test_hypothesis_guardrail_categorization():
    company = CompanyIdentity(
        name="Matiks",
        domain="matiks.com",
        industry="Mobile Gaming & EdTech",
        confidence=1.0
    )

    # Direct stated problem
    direct_hyp = ProblemHypothesis(
        id="hyp_dir_1",
        problem="Physical streak reward fulfillment bottlenecks are causing widespread Reddit customer complaints.",
        lens="fulfillment_ops",
        layer="stated",
        category_label="Direct / Stated (Explicit)",
        evidence_ids=["ev_reddit_1"],
        evidence_strength=0.9,
        business_impact=0.85,
        automatability=0.8,
        timeliness=0.9,
        buyer_credibility=0.9,
        final_score=87.5,
        rank=1,
        rationale="Reddit users cite repeated delays in receiving 100-day streak merchandise and cakes.",
        root_cause="Manual vendor dispatch and tracking across fragmented merchandise suppliers.",
        workflow_burden="Support teams manually fielding hundreds of missing reward delivery tickets.",
        automation_fit="Automated reward webhook dispatch and third-party logistics tracking portal."
    )
    assert _is_hypothesis_grounded_and_realistic(direct_hyp, company) is True
    assert direct_hyp.category_label == "Direct / Stated (Explicit)"

    # Inferred problem
    inferred_hyp = ProblemHypothesis(
        id="hyp_inf_1",
        problem="Headcount scaling from 31 to 71 creates cross-departmental coordination overhead.",
        lens="operations_management",
        layer="inferred",
        category_label="Inferred / Assumed (Hypothesized)",
        evidence_ids=["ev_scale_1"],
        evidence_strength=0.75,
        business_impact=0.7,
        automatability=0.7,
        timeliness=0.75,
        buyer_credibility=0.75,
        final_score=72.0,
        rank=2,
        rationale="Rapid doubling of team size often strains informal communication.",
        root_cause="Rapid onboarding without standardized project management tooling.",
        workflow_burden="Ad-hoc meetings and redundant sync cycles across engineering and design.",
        automation_fit="Automated cross-functional sprint sync and project tracking."
    )
    assert inferred_hyp.category_label == "Inferred / Assumed (Hypothesized)"

def test_staleness_penalty_in_scoring():
    from app.stages.s4_score import score_and_select_hypothesis

    dummy_ev = [
        EvidenceItem(
            id="ev_1",
            researcher="community",
            source_type="community",
            url="https://reddit.com/r/matiks/1",
            title="Old post",
            claim="Claim text",
            excerpt="Excerpt text",
            signal_type="friction",
            reliability_tier="C"
        )
    ]

    # Stale seasonal hypothesis (e.g. New Year promo from 10 months ago, timeliness=0.3)
    stale_hyp = ProblemHypothesis(
        id="hyp_stale",
        problem="Delays in New Year 2024 campaign bonus coupon delivery.",
        lens="fulfillment_ops",
        layer="stated",
        evidence_ids=["ev_1"],
        evidence_strength=0.85,
        business_impact=0.8,
        automatability=0.8,
        timeliness=0.3, # Stale!
        buyer_credibility=0.8
    )

    # Active ongoing hypothesis (timeliness=0.85)
    active_hyp = ProblemHypothesis(
        id="hyp_active",
        problem="Physical milestone merchandise fulfillment bottlenecks cause ongoing support backlogs.",
        lens="fulfillment_ops",
        layer="stated",
        evidence_ids=["ev_1"],
        evidence_strength=0.85,
        business_impact=0.8,
        automatability=0.8,
        timeliness=0.85, # Active!
        buyer_credibility=0.8
    )

    ranked, winner, hook = score_and_select_hypothesis([stale_hyp, active_hyp], dummy_ev)
    assert winner.id == "hyp_active", "Active ongoing problem should win over stale seasonal problem"
    assert ranked[0].id == "hyp_active"
    assert ranked[1].id == "hyp_stale"
    assert ranked[0].final_score > ranked[1].final_score

def test_deterministic_tier_guard_reclassifies_bare_phone_excerpt():
    """
    The narrow tier guard demotes hypotheses whose ONLY evidence excerpt is a bare
    phone number string — the upstream S2 boilerplate filter is the primary defense;
    this guard is the last-resort catch for anything that slips through.
    The guard must NOT demote when the excerpt contains genuine textual content.
    """
    from app.stages.s3_discovery import _enforce_deterministic_tier_guard

    # Case 1: excerpt is a bare phone number → must demote
    bare_phone_ev = EvidenceItem(
        id="ev_bare_phone",
        researcher="changelogs_and_migrations",
        source_type="changelog",   # not a complaint source
        url="https://www.mahalaxmibus.co.in/something",
        title="Contact Info",
        claim="Dedicated E-Payment phone line.",
        excerpt="6366967218",      # pure digits, no complaint text
        reliability_tier="A",
        signal_type="migration_sunset"
    )
    hyp_bare = ProblemHypothesis(
        id="hyp_bare",
        problem="Customers face payment processing issues requiring dedicated phone support.",
        lens="finance_ops",
        layer="stated",
        category_label="Direct / Stated (Explicit)",
        evidence_ids=["ev_bare_phone"],
        evidence_strength=0.9, business_impact=0.85,
        automatability=0.85, timeliness=0.85, buyer_credibility=0.9
    )
    _enforce_deterministic_tier_guard(hyp_bare, {"ev_bare_phone": bare_phone_ev})
    assert hyp_bare.category_label == "Inferred / Assumed (Hypothesized)"
    assert hyp_bare.layer == "inferred"
    assert "inferred" in hyp_bare.grounding_critique.lower()

    # Case 2: excerpt has real complaint text → must NOT demote
    real_complaint_ev = EvidenceItem(
        id="ev_real_complaint",
        researcher="community_review",
        source_type="reviews",    # authentic complaint source
        url="https://play.google.com/store/apps/details?id=in.mahalaxmi",
        title="1-star review",
        claim="Customers report money deducted but booking not confirmed.",
        excerpt="Money was deducted but I never got a confirmation. Worst experience ever.",
        reliability_tier="B",
        signal_type="complaint"
    )
    hyp_real = ProblemHypothesis(
        id="hyp_real",
        problem="Payment deductions without booking confirmation causing customer frustration.",
        lens="finance_ops",
        layer="stated",
        category_label="Direct / Stated (Explicit)",
        evidence_ids=["ev_real_complaint"],
        evidence_strength=0.9, business_impact=0.85,
        automatability=0.85, timeliness=0.85, buyer_credibility=0.9
    )
    _enforce_deterministic_tier_guard(hyp_real, {"ev_real_complaint": real_complaint_ev})
    # Must remain Direct / Stated — real complaint evidence
    assert hyp_real.category_label == "Direct / Stated (Explicit)"
    assert hyp_real.layer == "stated"

def test_candidate_pool_deduplication():
    """Duplicate candidate entities with the same domain must be deduplicated to avoid self-competition."""
    candidates = [
        CompanyCandidate(
            name="Mahalaxmi Travels",
            domain="mahalaxmibus.com",
            industry="Travel & Transportation",
            hq="Pune, Maharashtra",
            description="A travel agency and bus service provider based in Pune, India."
        ),
        CompanyCandidate(
            name="Mahalaxmi Tour and Travels",
            domain="mahalaxmitravels.com",
            industry="Tourism & Pilgrimage",
            hq="Haridwar, Uttarakhand",
            description="Tour operator specializing in Char Dham yatras."
        ),
        CompanyCandidate(
            name="Mahalaxmi Travels",
            domain="mahalaxmibus.com",  # Duplicate domain!
            industry="Transportation & Logistics",
            hq="",
            description="Listed on LinkedIn with 144 followers."
        )
    ]
    scored, best, conf, confirmed = score_candidates_pool(
        candidates, "Mahalaxmi Travels", hints={}
    )
    # The pool must be deduplicated from 3 candidates down to 2 distinct domains
    domains = [c.domain for c in scored]
    assert len(domains) == 2
    assert len(set(domains)) == 2
    assert "mahalaxmibus.com" in domains
    assert "mahalaxmitravels.com" in domains
