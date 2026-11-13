import pytest
import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.demo_cache import (
    get_demo_cache, match_demo_case, create_and_seed_cached_run,
    replay_cached_demo, resume_cached_demo
)
from app.db import get_run, get_run_full_details

client = TestClient(app)

def test_demo_cache_loaded():
    cache = get_demo_cache()
    expected_cases = [
        "ramp_company", "person_only", "mercury_ambiguous",
        "ambiguous_person", "matiks_community", "mahalaxmi_employee",
        "brex_compliance", "shipbob_changelog"
    ]
    for case in expected_cases:
        assert case in cache, f"Expected {case} in demo cache!"
        data = cache[case]
        assert len(data.get("events", [])) > 0
        assert len(data.get("evidence", [])) > 0
        assert len(data.get("hypotheses", [])) > 0
        assert len(data.get("drafts", [])) > 0

def test_match_demo_case():
    assert match_demo_case(company_name="Ramp") == "ramp_company"
    assert match_demo_case(company_name="Ramp", role="CFO") == "ramp_role"
    assert match_demo_case(person_name="Immad Akhund") == "person_only"
    assert match_demo_case(person_name="Alex Smith") == "ambiguous_person"
    assert match_demo_case(company_name="Mercury") == "mercury_ambiguous"
    assert match_demo_case(company_name="Matiks") == "matiks_community"
    assert match_demo_case(company_name="Mahalaxmi Travels") == "mahalaxmi_employee"
    assert match_demo_case(company_name="Brex") == "brex_compliance"
    assert match_demo_case(company_name="ShipBob") == "shipbob_changelog"
    assert match_demo_case(person_name="Eric Glyman") == "ramp_person"
    # Fallback / non-match
    assert match_demo_case(company_name="Unknown Uncached Corp 12345") is None

def test_api_list_demo_cases():
    res = client.get("/api/demo-cases")
    assert res.status_code == 200
    data = res.json()
    assert "cases" in data
    cases = {c["case_id"]: c for c in data["cases"]}
    assert "ramp_company" in cases
    assert "mercury_ambiguous" in cases
    assert "matiks_community" in cases
    assert cases["ramp_company"]["hypotheses_count"] > 0

def test_api_create_cached_run():
    # 1. Start cached run for Brex
    payload = {
        "company_name": "Brex",
        "use_cache": True
    }
    res = client.post("/api/runs", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["cached"] is True
    assert data["demo_case"] == "brex_compliance"
    run_id = data["run_id"]

    # Verify run details were seeded into SQLite
    details = get_run_full_details(run_id)
    assert len(details.get("hypotheses", [])) > 0
    assert len(details.get("evidence", [])) > 0
    assert details.get("draft") is not None

def test_api_create_fresh_run_when_unchecked():
    # When use_cache is False, it should NOT use cached replay
    payload = {
        "company_name": "Matiks",
        "use_cache": False
    }
    res = client.post("/api/runs", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["cached"] is False

def test_replay_and_clarification_cycle():
    async def _run():
        run_id = f"test_cache_merc_{time.time()}"
        create_and_seed_cached_run(
            run_id=run_id,
            case_id="mercury_ambiguous",
            company_input="Mercury",
            person_name=None,
            hints={}
        )
        
        # Run the replay - it should pause at clarification_needed
        await replay_cached_demo(run_id, "mercury_ambiguous")
        run = get_run(run_id)
        assert run["status"] == "awaiting_clarification"

        # Now resume the clarification
        await resume_cached_demo(run_id, "mercury_ambiguous")
        run_after = get_run(run_id)
        assert run_after["status"] == "pending_review"

    import time
    asyncio.run(_run())
