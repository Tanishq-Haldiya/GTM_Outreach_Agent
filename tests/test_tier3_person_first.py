import pytest
import asyncio
from typing import List

from app.models import PersonCandidate, PersonProfile, ProblemHypothesis, EvidenceItem, OutreachDraft
from app.roles import (
    normalize_person_role, detect_person_seniority,
    get_person_role_fit_multiplier, load_role_map_config
)
from app.stages.s0_person import (
    score_person_candidates, _clean_name, is_ended_role
)
from app.stages.s3_discovery import apply_role_filtered_discovery
from app.stages.s4_score import score_and_select_hypothesis
from app.stages.s7_check import check_swap_the_role

def test_person_candidate_deduplication():
    """Candidates with matching (normalized_name, normalized_company) must merge without duplicates."""
    c1 = PersonCandidate(
        name="Nikil Viswanathan",
        first_name="Nikil",
        company_raw="Alchemy",
        title_raw="CEO & Co-founder",
        source_url="https://linkedin.com/in/nikilv",
        source_type="linkedin_snippet"
    )
    c2 = PersonCandidate(
        name="nikil viswanathan",
        company_raw="Alchemy Insights, Inc.",
        title_raw="Co-Founder and CEO",
        source_url="https://alchemy.com/about",
        source_type="leadership_page"
    )
    norm_c1 = (_clean_name(c1.name), _clean_name(c1.company_raw))
    norm_c2 = (_clean_name(c2.name), _clean_name(c2.company_raw))
    
    # Both normalize to nikil viswanathan at alchemy
    assert norm_c1[0] == norm_c2[0]
    assert "alchemy" in norm_c1[1] and "alchemy" in norm_c2[1]

def test_person_conf_scoring_and_penalties():
    """Tests PersonConf formula: corroboration, recency penalty, ambiguity factor."""
    # Strong candidate with 2 independent sources
    strong = PersonCandidate(
        name="Eric Glyman",
        first_name="Eric",
        company_raw="Ramp",
        title_raw="CEO",
        source_url="https://ramp.com/about",
        evidence_urls=["https://ramp.com/about", "https://forbes.com/eric-glyman"],
        independent_sources_count=2
    )
    scored, best, conf, is_confirmed = score_person_candidates([strong], "Eric Glyman", hints={"company_hint": "Ramp"})
    assert is_confirmed is True
    assert conf >= 0.80
    assert best.name == "Eric Glyman"

    # Former role penalty
    former = PersonCandidate(
        name="John Doe",
        company_raw="OldCo",
        title_raw="Former VP of Operations, Ex-OldCo",
        source_url="https://linkedin.com/in/johndoe",
        independent_sources_count=1
    )
    _, _, conf_former, is_confirmed_former = score_person_candidates([former], "John Doe")
    assert is_confirmed_former is False
    assert conf_former < 0.75  # Severely penalized below confirmation threshold

    # Ambiguity penalty (runner-up close to top candidate)
    cand_a = PersonCandidate(
        name="Alex Smith",
        company_raw="Company A",
        title_raw="Director of Operations",
        source_url="https://companya.com",
        independent_sources_count=1
    )
    cand_b = PersonCandidate(
        name="Alex Smith",
        company_raw="Company B",
        title_raw="Director of Operations",
        source_url="https://companyb.com",
        independent_sources_count=1
    )
    scored_ambig, best_ambig, conf_ambig, is_confirmed_ambig = score_person_candidates([cand_a, cand_b], "Alex Smith")
    assert is_confirmed_ambig is False
    assert conf_ambig < 0.80  # Separation penalty prevents auto-confirmation

@pytest.mark.anyio
async def test_title_normalization_taxonomy():
    """Verify 30+ titles normalize to correct functional taxonomy and seniority level."""
    test_cases = [
        # (raw_title, expected_function, expected_seniority)
        ("Founder & CEO", "Executive/GM", "C-level"),
        ("Chief Executive Officer", "Executive/GM", "C-level"),
        ("Chief of Staff", "Executive/GM", "Director"),
        ("COO", "Operations", "C-level"),
        ("Head of Operations", "Operations", "VP/Head"),
        ("VP of Business Operations", "Operations", "VP/Head"),
        ("Operations Director", "Operations", "Director"),
        ("VP Customer Experience", "Customer Support/CX", "VP/Head"),
        ("Head of Support", "Customer Support/CX", "VP/Head"),
        ("CX Lead", "Customer Support/CX", "Director"),
        ("Customer Support Manager", "Customer Support/CX", "Manager"),
        ("CFO", "Finance/Accounting", "C-level"),
        ("VP Finance", "Finance/Accounting", "VP/Head"),
        ("Corporate Controller", "Finance/Accounting", "Director"),
        ("Head of AP and Billing", "Finance/Accounting", "VP/Head"),
        ("Billing Specialist", "Finance/Accounting", "IC"),
        ("Chief Procurement Officer", "Supply Chain/Logistics", "C-level"),
        ("Head of Supply Chain", "Supply Chain/Logistics", "VP/Head"),
        ("VP Logistics", "Supply Chain/Logistics", "VP/Head"),
        ("CTO", "Engineering/IT", "C-level"),
        ("VP Engineering", "Engineering/IT", "VP/Head"),
        ("Head of Infrastructure", "Engineering/IT", "VP/Head"),
        ("Chief Product Officer", "Product", "C-level"),
        ("VP Product", "Product", "VP/Head"),
        ("CRO", "Sales/Growth/Marketing", "C-level"),
        ("VP Sales", "Sales/Growth/Marketing", "VP/Head"),
        ("Head of RevOps", "Sales/Growth/Marketing", "VP/Head"),
        ("Chief People Officer", "HR/People", "C-level"),
        ("Head of People", "HR/People", "VP/Head"),
        ("General Counsel", "Compliance/Legal", "C-level"),
        ("Chief Compliance Officer", "Compliance/Legal", "C-level"),
        ("Head of Regulatory Affairs", "Compliance/Legal", "VP/Head"),
        ("Merchandiser at Centex Fabrics Exports Unit", "Supply Chain/Logistics", "IC"),
        ("Student at All India Institute of Medical Sciences", "Academic/Student", "Student"),
        ("Founding Product Led Growth at Matiks", "Product", "Director"),
    ]

    for raw, exp_func, exp_sen in test_cases:
        norm = await normalize_person_role(raw)
        assert norm["function"] == exp_func, f"Failed function for '{raw}': got {norm['function']}, expected {exp_func}"
        assert norm["seniority"] == exp_sen, f"Failed seniority for '{raw}': got {norm['seniority']}, expected {exp_sen}"

def test_role_fit_multiplier_and_fallback():
    """Verify 1.0 (direct), 0.75 (adjacent), 0.80 (executive), 0.40 (distant) and 3-minimum fallback."""
    # Direct
    mult_direct, _ = get_person_role_fit_multiplier("Customer Support/CX", "Customer Support/CX")
    assert mult_direct == 1.0

    # Adjacent (Support <-> Operations)
    mult_adj, _ = get_person_role_fit_multiplier("Operations", "Customer Support/CX")
    assert mult_adj == 0.75

    # Executive (Executive/GM accepts any function with 0.80)
    mult_exec, _ = get_person_role_fit_multiplier("Finance/Accounting", "Executive/GM")
    assert mult_exec == 0.80

    # Distant (Customer Support <-> Compliance/Legal)
    mult_distant, _ = get_person_role_fit_multiplier("Compliance/Legal", "Customer Support/CX")
    assert mult_distant == 0.40

    # Test 3-hypothesis minimum fallback in apply_role_filtered_discovery
    person = PersonProfile(
        name="Sarah Connor",
        company_raw="Cyberdyne",
        title_raw="Head of Customer Experience",
        function="Customer Support/CX",
        seniority="VP/Head"
    )

    hypotheses = [
        ProblemHypothesis(
            id="h1",
            problem="KYC regulatory compliance backlog",
            lens="compliance_kyc",
            layer="stated",
            evidence_strength=0.9,
            business_impact=0.9,
            final_score=0.9,
            owner_function="Compliance/Legal"
        ),
        ProblemHypothesis(
            id="h2",
            problem="Month-end invoice reconciliation friction",
            lens="finance_ops",
            layer="stated",
            evidence_strength=0.85,
            business_impact=0.85,
            final_score=0.85,
            owner_function="Finance/Accounting"
        )
    ]
    # Only 2 hypotheses exist, both distant. Fallback must kick in to keep at least 3 (or all available) hypotheses
    filtered = apply_role_filtered_discovery(hypotheses, person)
    assert len(filtered) == 2  # Kept both rather than dropping
    assert filtered[0].role_fit == 0.40  # Marked with role_fit 0.40

def test_role_fit_in_s4_scoring():
    """Verify RoleFit multiplier is applied cleanly in score calculation and breakdown."""
    person = PersonProfile(
        name="Alex Smith",
        company_raw="Ramp",
        title_raw="VP Finance",
        function="Finance/Accounting",
        seniority="VP/Head"
    )

    hypotheses = [
        ProblemHypothesis(
            id="h_fin",
            problem="Invoice reconciliation takes 12 days at month-end",
            lens="finance_ops",
            layer="stated",
            evidence_strength=0.8,
            business_impact=0.8,
            automatability=0.8,
            timeliness=0.8,
            buyer_credibility=0.8,
            owner_function="Finance/Accounting"
        ),
        ProblemHypothesis(
            id="h_cx",
            problem="Support response time spiked 4x during outage",
            lens="customer_support",
            layer="stated",
            evidence_strength=0.8,
            business_impact=0.8,
            automatability=0.8,
            timeliness=0.8,
            buyer_credibility=0.8,
            owner_function="Customer Support/CX"
        )
    ]

    ev_list = [
        EvidenceItem(
            id="ev1",
            researcher="filings",
            source_type="sec_filing",
            url="https://sec.gov",
            title="10-K",
            claim="Invoicing is delayed",
            excerpt="Invoices took 12 days",
            signal_type="friction",
            reliability_tier="A"
        )
    ]

    ranked, winner, hook, fallback = score_and_select_hypothesis(
        hypotheses,
        ev_list,
        recipient_lens="finance_ops",
        person_profile=person,
        return_fallback_info=True
    )

    # Finance hypothesis must win for VP Finance due to 1.0x vs 0.40x RoleFit multiplier
    assert winner.id == "h_fin"
    assert winner.role_fit == 1.0
    assert ranked[1].id == "h_cx"
    assert ranked[1].role_fit == 0.40
    assert winner.final_score > ranked[1].final_score

def test_s7_swap_the_role_detector():
    """Verify S7 swap-the-role test checks domain specificity."""
    # Draft aimed at Customer Support containing AP/invoicing jargon and zero support terminology
    draft_mismatch = OutreachDraft(
        id="d1",
        subject="Invoice reconciliation",
        body="Hi Alex, noticed Ramp's accounts payable ledger has month-end invoice reconciliation and 3-way matching discrepancies.",
        linkedin_note="Quick note on invoice reconciliation.",
        why_this_hook="Testing",
        selected_hook_id="ev1"
    )
    passed, reason = check_swap_the_role(draft_mismatch.body, recipient_function="Customer Support/CX")
    assert passed is False
    assert "Swap-the-role failed" in reason

    # Draft aimed at Customer Support with support-specific terminology
    draft_match = OutreachDraft(
        id="d2",
        subject="Support ticket backlog",
        body="Hi Sarah, noticed customer support ticket volume escalated after the recent release with CSAT dropping on dispute triage.",
        linkedin_note="Quick note on customer triage.",
        why_this_hook="Testing",
        selected_hook_id="ev1"
    )
    passed_good, reason_good = check_swap_the_role(draft_match.body, recipient_function="Customer Support/CX")
    assert passed_good is True

def test_backward_compatibility_company_only():
    """Verify company-only runs without person_name work with neutral defaults."""
    mult, badge = get_person_role_fit_multiplier("Finance/Accounting", None)
    assert mult == 1.0  # Neutral 1.0 when no person profile is provided

@pytest.mark.anyio
async def test_resume_person_clarification_db_lifecycle():
    """Verify resume_person_clarification properly deserializes person_profile from SQLite DB string and updates run state."""
    from app.db import insert_run, update_run_status, get_run
    from app.orchestrator import resume_person_clarification
    from unittest.mock import patch, AsyncMock
    import uuid

    run_id = f"test_run_{uuid.uuid4().hex[:8]}"
    hints = {"person_name": "Drishti Pandita"}
    insert_run(run_id, "Prospect: Drishti Pandita", hints, mode="fast", person_name="Drishti Pandita")

    # Simulate S0 pausing at identity gate and writing person_profile dict to DB (which SQLite stores as string)
    s0_payload = {
        "name": "Drishti Pandita",
        "confidence": 0.51,
        "alternatives": [
            {
                "name": "Drishti Pandita",
                "company_raw": "Matiks",
                "title_raw": "Founding Product Led Growth",
                "title_normalized": "Product Lead",
                "function": "Product",
                "seniority": "Director",
                "source_url": "https://matiks.com"
            }
        ]
    }
    update_run_status(run_id, "awaiting_person_clarification", person_profile=s0_payload)

    # Verify get_run deserializes person_profile properly
    loaded_run = get_run(run_id)
    assert isinstance(loaded_run["person_profile"], dict)
    assert loaded_run["person_profile"]["alternatives"][0]["company_raw"] == "Matiks"

    # Now call resume_person_clarification with selected candidate
    with patch("app.orchestrator._continue_from_s0_to_pipeline", new_callable=AsyncMock) as mock_cont:
        await resume_person_clarification(
            run_id,
            selected_person_name="Drishti Pandita",
            selected_company="Matiks",
            selected_title="Founding Product Led Growth"
        )
        assert mock_cont.called
        profile_arg = mock_cont.call_args[0][1]
        assert profile_arg.name == "Drishti Pandita"
        assert profile_arg.company_raw == "Matiks"
        assert profile_arg.confidence == 1.0

    # Also test manual entry
    with patch("app.orchestrator._continue_from_s0_to_pipeline", new_callable=AsyncMock) as mock_cont2:
        await resume_person_clarification(
            run_id,
            manual_company="Custom Corp",
            manual_role="VP Operations"
        )
        assert mock_cont2.called
        profile_arg2 = mock_cont2.call_args[0][1]
        assert profile_arg2.company_raw == "Custom Corp"
        assert profile_arg2.role_source == "manual"

def test_score_source_authority_all_signal_types():
    """Verify s2_research.compute_source_authority evaluates all signal types without NameError or unhandled exceptions."""
    from app.stages.s2_research import compute_source_authority

    signals = [
        "friction", "outage_downtime", "manual_process",
        "compliance_risk", "expansion", "leadership_priority",
        "hiring", "scaling_strain"
    ]
    sources = ["review", "community", "employee_voice", "website", "sec_filing", "compliance", "exec_voice"]

    for sig in signals:
        for src in sources:
            score = compute_source_authority(
                url="https://matiks.com/news",
                source_type=src,
                reliability_tier="A",
                excerpt="This is a detailed excerpt that contains sufficient words to pass the length threshold.",
                signal_type=sig,
                company_domain="matiks.com"
            )
            assert 0.40 <= score <= 0.99

def test_api_runs_person_first_http_lifecycle():
    """Integration test via FastAPI TestClient verifying POST /api/runs with person_name works without 500 error."""
    from fastapi.testclient import TestClient
    from app.main import app
    from unittest.mock import patch, AsyncMock

    client = TestClient(app)

    with patch("app.main.start_run", new_callable=AsyncMock) as mock_start:
        response = client.post(
            "/api/runs",
            json={"person_name": "Drishti Pandita", "company_hint": "Matiks", "mode": "fast"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "queued"

def test_api_clarify_person_http_lifecycle():
    """Integration test via FastAPI TestClient verifying POST /api/runs/{run_id}/clarify-person deserializes and resumes without 500."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import insert_run, update_run_status
    from unittest.mock import patch, AsyncMock
    import uuid

    client = TestClient(app)
    run_id = f"test_api_{uuid.uuid4().hex[:8]}"
    insert_run(run_id, "Prospect: Drishti Pandita", {"person_name": "Drishti Pandita"}, mode="fast", person_name="Drishti Pandita")

    s0_payload = {
        "name": "Drishti Pandita",
        "confidence": 0.51,
        "alternatives": [
            {
                "name": "Drishti Pandita",
                "company_raw": "Matiks",
                "title_raw": "Founding Product Led Growth",
                "title_normalized": "Product Lead",
                "function": "Product",
                "seniority": "Director",
                "source_url": "https://matiks.com"
            }
        ]
    }
    update_run_status(run_id, "awaiting_person_clarification", person_profile=s0_payload)

    with patch("app.main.resume_person_clarification", new_callable=AsyncMock) as mock_resume:
        response = client.post(
            f"/api/runs/{run_id}/clarify-person",
            json={
                "selected_person_name": "Drishti Pandita",
                "selected_company": "Matiks",
                "selected_title": "Founding Product Led Growth"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "resumed"

def test_score_person_candidates_caps_at_max_8():
    """Verify people search returns up to max 8 candidate cards."""
    cands = [
        PersonCandidate(name="Drishti Pandita", company_raw=f"Company {i}", title_raw=f"Role {i}")
        for i in range(15)
    ]
    scored, best, conf, is_confirmed = score_person_candidates(cands, "Drishti Pandita")
    assert len(scored) == 8, f"Expected 8 cards, got {len(scored)}"

def test_is_ended_role_filter():
    """Verify past and ended roles are accurately identified and excluded/penalized."""
    # 1. Active LinkedIn role with 'present'
    snip_active = "Drishti Pandita · Founding Product Led Growth at Matiks (Nov 2024 to present) · Delhi, India"
    assert is_ended_role("Founding Product Led Growth", "Matiks", snip_active) is False

    # 2. Closed past date range
    snip_closed = "Drishti Pandita · Merchandiser at Rajan Enterprise (May 2022 to Jun 2024)"
    assert is_ended_role("Merchandiser", "Rajan Enterprise", snip_closed) is True

    # 3. Explicit 'Past:' section in snippet
    snip_past = "Drishti Pandita - Current: Matiks · Past: Stripe, Airbnb (2018 - 2021)"
    assert is_ended_role("Engineer", "Airbnb", snip_past) is True
    assert is_ended_role("Product Lead", "Matiks", snip_past) is False

    # 4. Title with 'Former' or 'Ex-'
    assert is_ended_role("Former VP of Operations", "TechCorp", "") is True
    assert is_ended_role("Ex-Stripe Product Manager", "Stripe", "") is True

    # 5. Company name variant (stripped suffix) with closed date
    snip_variant = "Drishti Pandita · Merchandiser at Centex Fabrics (May 2022 – Jun 2024)"
    assert is_ended_role("Merchandiser", "Centex Fabrics Exports Unit", snip_variant) is True

    # 6. Verify score_person_candidates heavily penalizes ended roles
    ended_cand = PersonCandidate(
        name="Drishti Pandita",
        company_raw="OldCo",
        title_raw="Past Analyst",
        snippet_text="Drishti Pandita at OldCo (2019 to 2021)"
    )
    active_cand = PersonCandidate(
        name="Drishti Pandita",
        company_raw="CurrentCo",
        title_raw="Founding Lead",
        snippet_text="Drishti Pandita at CurrentCo (2023 to present)"
    )
    scored, best, conf, is_confirmed = score_person_candidates([ended_cand, active_cand], "Drishti Pandita")
    assert ended_cand.recency_score == 0.10
    assert ended_cand.is_current is False
    assert best.company_raw == "CurrentCo"
    # Ended candidate should be excluded from active choices when active candidate exists
    assert all(c.company_raw != "OldCo" for c in scored)

    # 7. Within the same company: closed date role must be detected as ended even if another role is present
    snip_multi_role_same_comp = (
        "## Experience\n"
        "- Vice Captain at Team KNOx IIT Roorkee (Apr 2026 to present)\n"
        "- Powertrain Engineer at Team KNOx IIT Roorkee (Jan 2025 to Apr 2026)"
    )
    assert is_ended_role("Powertrain Engineer", "Team KNOx IIT Roorkee", snip_multi_role_same_comp) is True
    assert is_ended_role("Vice Captain", "Team KNOx IIT Roorkee", snip_multi_role_same_comp) is False

    # 8. Inline dot-delimited format (e.g. Google · Software Engineer · 2018 - 2021 · 3 yrs)
    snip_inline_dot = "Google · Software Engineer · 2018 - 2021 · 3 yrs"
    assert is_ended_role("Software Engineer", "Google", snip_inline_dot) is True

    # 9. Past internships and closed student roles
    snip_fest = (
        "## Experience\n"
        "- Manager at Cognizance, IIT Roorkee (Sep 2025 to present)\n"
        "- Event Executive at Cognizance, IIT Roorkee (Jan 2024 to Aug 2025)"
    )
    assert is_ended_role("Event Executive", "Cognizance, IIT Roorkee", snip_fest) is True
    assert is_ended_role("Manager", "Cognizance, IIT Roorkee", snip_fest) is False

    # 10. Present role explicitly stating 'to present' on the profile must NOT be assumed to have ended
    snip_trainee = "## Experience\n- Data Science Trainee at CustomerInsights.AI (May 2026 to present)"
    assert is_ended_role("Data Science Trainee", "CustomerInsights.AI", snip_trainee) is False





