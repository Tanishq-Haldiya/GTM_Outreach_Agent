import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.db import get_db, update_run_status
from app.events import emit_event

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parent / "demo_cache.json"
_DEMO_CACHE: Optional[Dict[str, Any]] = None

def get_demo_cache() -> Dict[str, Any]:
    global _DEMO_CACHE
    if _DEMO_CACHE is None:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _DEMO_CACHE = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load demo_cache.json: {e}")
                _DEMO_CACHE = {}
        else:
            _DEMO_CACHE = {}
    return _DEMO_CACHE

def match_demo_case(
    company_name: Optional[str] = None,
    person_name: Optional[str] = None,
    role: Optional[str] = None,
    demo_case: Optional[str] = None
) -> Optional[str]:
    """Matches request inputs against the available cached demo scenarios."""
    cache = get_demo_cache()
    if demo_case and demo_case in cache:
        return demo_case

    c_norm = (company_name or "").strip().lower()
    p_norm = (person_name or "").strip().lower()
    r_norm = (role or "").strip().lower()

    # Exact or prioritized matches
    if "alex smith" in p_norm:
        return "ambiguous_person"
    if "immad" in p_norm:
        return "person_only"
    if "glyman" in p_norm:
        return "ramp_person"
    if c_norm == "mercury" and not p_norm:
        return "mercury_ambiguous"
    if "matiks" in c_norm:
        return "matiks_community"
    if "mahalaxmi" in c_norm:
        return "mahalaxmi_employee"
    if "brex" in c_norm:
        return "brex_compliance"
    if "shipbob" in c_norm:
        return "shipbob_changelog"
    if c_norm == "ramp":
        if "cfo" in r_norm or "finance" in r_norm:
            return "ramp_role"
        return "ramp_company"

    return None

def create_and_seed_cached_run(
    run_id: str,
    case_id: str,
    company_input: str,
    person_name: Optional[str],
    hints: Dict[str, Any]
) -> Dict[str, Any]:
    """Seeds the SQLite database with the cached run data (evidence, hypotheses, solution, draft)."""
    cache = get_demo_cache()
    case_data = cache.get(case_id)
    if not case_data:
        raise ValueError(f"Unknown demo case: {case_id}")

    cached_run = case_data.get("run", {})
    now = time.time()

    conn = get_db()
    cursor = conn.cursor()

    # Record hints marking this as a cached run
    enriched_hints = dict(hints)
    enriched_hints["use_cache"] = True
    enriched_hints["demo_case"] = case_id
    enriched_hints["is_cached_run"] = True

    # 1. Insert runs row
    cursor.execute("""
        INSERT INTO runs (
            id, company_input, hints, mode, status, confidence,
            confirmation_method, started_time, finished_time, duration,
            s1_pause_duration, confirmed_company, company_profile,
            selected_hypothesis_id, final_draft_id, error_message,
            person_name, person_confidence, person_company, person_title,
            person_function, person_seniority, person_profile,
            recipient_name, recipient_title, recipient_lens, seniority,
            fallback_banner_used, fallback_suggestions
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?
        )
    """, (
        run_id,
        company_input or cached_run.get("company_input") or "Target",
        json.dumps(enriched_hints),
        "cached",
        "running",
        cached_run.get("confidence", 0.95),
        cached_run.get("confirmation_method", "auto"),
        now,
        None,
        None,
        0.0,
        json.dumps(cached_run["confirmed_company"]) if isinstance(cached_run.get("confirmed_company"), dict) else cached_run.get("confirmed_company"),
        json.dumps(cached_run["company_profile"]) if isinstance(cached_run.get("company_profile"), dict) else cached_run.get("company_profile"),
        cached_run.get("selected_hypothesis_id"),
        cached_run.get("final_draft_id"),
        None,
        person_name or cached_run.get("person_name"),
        cached_run.get("person_confidence", 1.0),
        cached_run.get("person_company"),
        cached_run.get("person_title"),
        cached_run.get("person_function"),
        cached_run.get("person_seniority"),
        json.dumps(cached_run["person_profile"]) if isinstance(cached_run.get("person_profile"), dict) else cached_run.get("person_profile"),
        cached_run.get("recipient_name"),
        cached_run.get("recipient_title"),
        cached_run.get("recipient_lens"),
        cached_run.get("seniority"),
        cached_run.get("fallback_banner_used", 0),
        cached_run.get("fallback_suggestions", "[]")
    ))

    # 2. Seed Evidence
    evidence_items = case_data.get("evidence", [])
    for ev in evidence_items:
        cursor.execute("""
            INSERT OR REPLACE INTO evidence (
                id, run_id, researcher, source_type, url, title,
                claim, excerpt, signal_type, reliability_tier,
                published_date, recency_days, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"{run_id}_{ev.get('id', '')}" if ev.get('id') else f"{run_id}_{time.time()}",
            run_id,
            ev.get("researcher"),
            ev.get("source_type"),
            ev.get("url"),
            ev.get("title"),
            ev.get("claim"),
            ev.get("excerpt"),
            ev.get("signal_type"),
            ev.get("reliability_tier"),
            ev.get("published_date"),
            ev.get("recency_days", 0),
            now
        ))

    # 3. Seed Hypotheses
    hypotheses_items = case_data.get("hypotheses", [])
    for h in hypotheses_items:
        cursor.execute("""
            INSERT OR REPLACE INTO hypotheses (
                id, run_id, problem, lens, layer, evidence_ids,
                scores, final_score, rank, rationale,
                lens_explanation, root_cause, workflow_burden, automation_fit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h.get("id"),
            run_id,
            h.get("problem"),
            h.get("lens"),
            h.get("layer"),
            json.dumps(h.get("evidence_ids", [])) if isinstance(h.get("evidence_ids"), list) else h.get("evidence_ids"),
            json.dumps(h.get("scores", {})) if isinstance(h.get("scores"), dict) else h.get("scores"),
            h.get("final_score", 0.0),
            h.get("rank", 1),
            h.get("rationale"),
            h.get("lens_explanation"),
            h.get("root_cause"),
            h.get("workflow_burden"),
            h.get("automation_fit")
        ))

    # 4. Seed Solutions
    solutions = case_data.get("solutions", [])
    for s in solutions:
        cursor.execute("""
            INSERT OR REPLACE INTO solutions (
                id, run_id, hypothesis_id, payload, created_time
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            s.get("id"),
            run_id,
            s.get("hypothesis_id"),
            json.dumps(s.get("payload")) if isinstance(s.get("payload"), dict) else s.get("payload"),
            now
        ))

    # 5. Seed Drafts
    drafts = case_data.get("drafts", [])
    for d in drafts:
        cursor.execute("""
            INSERT OR REPLACE INTO drafts (
                id, run_id, subject, body, linkedin_note, claim_map,
                why_this_hook, quality_report, version, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.get("id"),
            run_id,
            d.get("subject"),
            d.get("body"),
            d.get("linkedin_note"),
            json.dumps(d.get("claim_map")) if isinstance(d.get("claim_map"), (dict, list)) else d.get("claim_map"),
            d.get("why_this_hook"),
            json.dumps(d.get("quality_report")) if isinstance(d.get("quality_report"), (dict, list)) else d.get("quality_report"),
            d.get("version", 1),
            now
        ))

    conn.commit()
    conn.close()
    return case_data

async def replay_cached_demo(run_id: str, case_id: str):
    """Replays the cached stage events with realistic streaming cadence."""
    cache = get_demo_cache()
    case_data = cache.get(case_id)
    if not case_data:
        logger.error(f"Cannot replay: missing case {case_id}")
        return

    events = case_data.get("events", [])
    pause_on = case_data.get("pause_on")

    start_time = time.time()

    for idx, ev in enumerate(events):
        event_type = ev.get("event_type")
        stage = ev.get("stage", "")
        message = ev.get("message", "")
        payload = ev.get("payload")
        duration = ev.get("duration", 0.0)

        # Check if this case should pause for interactive user clarification
        if pause_on and event_type == pause_on:
            if event_type == "clarification_needed":
                update_run_status(run_id, "awaiting_clarification")
            elif event_type == "s0_clarification_needed":
                update_run_status(run_id, "awaiting_person_clarification")
            
            await emit_event(run_id, stage, event_type, message, payload=payload, duration=duration)
            logger.info(f"Cached demo {case_id} paused for clarification at event {idx}")
            return  # Pause here; user will click clarification and trigger resume_cached_demo

        # Stage status updates in SQLite
        if event_type == "s0_started":
            update_run_status(run_id, "resolving_person")
        elif event_type == "s0_resolved":
            update_run_status(run_id, "person_confirmed")
        elif event_type == "stage_started":
            stage_status_map = {
                "s1_resolve": "resolving",
                "s2_research": "researching",
                "s3_discovery": "discovering",
                "s4_score": "scoring",
                "s5_solution": "designing",
                "s6_draft": "drafting",
                "s7_check": "verifying"
            }
            if stage in stage_status_map:
                update_run_status(run_id, stage_status_map[stage])
        elif event_type == "run_completed":
            total_dur = round(time.time() - start_time, 1)
            if isinstance(payload, dict):
                payload["total_duration"] = total_dur
            update_run_status(
                run_id,
                "pending_review",
                finished_time=time.time(),
                duration=total_dur
            )

        await emit_event(run_id, stage, event_type, message, payload=payload, duration=duration)

        # Smooth, realistic pacing between events for demo recording (0.12s - 0.25s)
        if event_type in ("stage_completed", "profile_built", "draft_created", "run_completed"):
            await asyncio.sleep(0.25)
        elif event_type in ("llm_usage", "researcher_activity"):
            await asyncio.sleep(0.10)
        else:
            await asyncio.sleep(0.16)

async def resume_cached_demo(run_id: str, case_id: str):
    """Resumes replaying cached events after an interactive clarification step."""
    cache = get_demo_cache()
    case_data = cache.get(case_id)
    if not case_data:
        logger.error(f"Cannot resume: missing case {case_id}")
        return

    events = case_data.get("events", [])
    pause_on = case_data.get("pause_on")

    # Find the index of the event after the pause event
    resume_index = 0
    if pause_on:
        for i, ev in enumerate(events):
            if ev.get("event_type") == pause_on:
                resume_index = i + 1
                break

    start_time = time.time()
    for ev in events[resume_index:]:
        event_type = ev.get("event_type")
        stage = ev.get("stage", "")
        message = ev.get("message", "")
        payload = ev.get("payload")
        duration = ev.get("duration", 0.0)

        # Skip duplicate intermediate clarification rounds in demo replay
        if event_type in ("clarification_needed", "s0_clarification_needed"):
            continue

        if event_type == "stage_started":
            stage_status_map = {
                "s1_resolve": "resolving",
                "s2_research": "researching",
                "s3_discovery": "discovering",
                "s4_score": "scoring",
                "s5_solution": "designing",
                "s6_draft": "drafting",
                "s7_check": "verifying"
            }
            if stage in stage_status_map:
                update_run_status(run_id, stage_status_map[stage])
        elif event_type == "run_completed":
            total_dur = round(time.time() - start_time + 4.0, 1)
            if isinstance(payload, dict):
                payload["total_duration"] = total_dur
            update_run_status(
                run_id,
                "pending_review",
                finished_time=time.time(),
                duration=total_dur
            )

        await emit_event(run_id, stage, event_type, message, payload=payload, duration=duration)

        if event_type in ("stage_completed", "profile_built", "draft_created", "run_completed"):
            await asyncio.sleep(0.25)
        elif event_type in ("llm_usage", "researcher_activity"):
            await asyncio.sleep(0.10)
        else:
            await asyncio.sleep(0.16)
