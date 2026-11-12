import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.models import CompanyCandidate
from app.stages.s1_resolve import score_candidates_pool, generate_clarifying_question

def test_multi_round_clarification_loop():
    candidates = [
        CompanyCandidate(
            name="Mercury",
            domain="mercury.com",
            industry="Fintech / Banking",
            hq="San Francisco, CA",
            description="Banking platform designed for startups and venture-backed companies.",
            distinguishing_fact="US fintech providing online business checking and banking"
        ),
        CompanyCandidate(
            name="Mercury NZ",
            domain="mercury.co.nz",
            industry="Utilities / Energy",
            hq="Auckland, New Zealand",
            description="New Zealand electricity generator and retailer.",
            distinguishing_fact="New Zealand renewable energy utility provider"
        ),
        CompanyCandidate(
            name="Mercury IT",
            domain="mercuryit.com.au",
            industry="IT Services",
            hq="Queensland, Australia",
            description="Managed IT services, cybersecurity and cloud consulting.",
            distinguishing_fact="Australian IT support and cybersecurity provider"
        )
    ]

    # --- Initial State (No hints) ---
    scored, best, conf_0, confirmed_0 = score_candidates_pool(
        candidates, "Mercury", hints={}, answers_history=[]
    )
    # Because there are 3 close candidates with name 'Mercury', runner-up trails closely
    # Ambiguity factor pulls it below 0.80
    assert confirmed_0 is False
    assert conf_0 < 0.80

    # Round 1 Question generated
    q1 = generate_clarifying_question(scored, round_num=1)
    assert "industry" in q1.lower() or "sector" in q1.lower()

    # --- User answers vaguely: "it's an operating business" ---
    scored, best, conf_vague, confirmed_vague = score_candidates_pool(
        candidates, "Mercury", hints={}, answers_history=["it's an operating business"]
    )
    # Still not confirmed! We do NOT want to guess the wrong company!
    assert confirmed_vague is False
    assert conf_vague < 0.80

    # Round 2 Question generated (asking for HQ / location / domain)
    q2 = generate_clarifying_question(scored, round_num=2)
    assert "location" in q2.lower() or "headquarters" in q2.lower() or "domain" in q2.lower()

    # --- User answers with separating signal: "it is a fintech banking platform for startups" ---
    scored, best, conf_final, confirmed_final = score_candidates_pool(
        candidates, "Mercury", hints={}, answers_history=["it's an operating business", "fintech banking platform for startups in San Francisco"]
    )
    # Now Mercury (Banking) gets full hint match, runner-up falls far behind, confidence >= 0.80!
    assert confirmed_final is True
    assert conf_final >= 0.80
    assert best.domain == "mercury.com"
    assert best.name == "Mercury"

@pytest.mark.anyio
async def test_dynamic_candidate_rediscovery_mahalaxmi():
    from app.stages.s1_resolve import discover_candidates
    # When initial target is ambiguous like "Mahalaxmi", candidates are conglomerates/foods/packaging
    # If refined query is "Mahalaxmi Travels", discover_candidates should find travel entities
    discovered = await discover_candidates("Mahalaxmi Travels")
    assert len(discovered) > 0
    domains = [c.domain for c in discovered]
    names = [c.name for c in discovered]
    assert any("mahalaxmi" in d.lower() or "mahalaxmi" in n.lower() for d, n in zip(domains, names))
    assert any("travel" in c.industry.lower() or "transport" in c.industry.lower() or "bus" in c.domain.lower() for c in discovered)

    # Re-scoring with refined query must confirm Mahalaxmi Travels >= 0.80
    scored, best, conf, confirmed = score_candidates_pool(
        discovered, "Mahalaxmi Travels", hints={}, answers_history=["Mahalaxmi Travels"]
    )
    assert confirmed is True
    assert conf >= 0.80
    assert "mahalaxmi" in best.name.lower()
