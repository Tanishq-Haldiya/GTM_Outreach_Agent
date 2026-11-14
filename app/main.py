import uuid
import asyncio
import time
import json
import hashlib
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import ASSUMPTIONS_LOG, BASE_DIR
from app.db import (
    init_db, insert_run, get_run, get_all_runs,
    get_run_events, get_run_full_details, get_db, update_run_status
)
from app.events import subscribe, unsubscribe, format_sse
from app.models import (
    RunCreate, ClarifyRequest, ReviewRequest, SelectProblemRequest,
    PersonClarifyRequest, ProspectOverrideRequest
)
from app.orchestrator import (
    start_run, resume_with_clarification, generate_pipeline_for_hypothesis,
    resume_person_clarification, override_prospect
)
from app.demo_cache import (
    match_demo_case, create_and_seed_cached_run,
    replay_cached_demo, resume_cached_demo, get_demo_cache
)
from app.tools.http_client import get_http_client, close_http_client

app = FastAPI(title="GTM Outreach AI Pipeline", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database on startup
@app.on_event("startup")
def on_startup():
    init_db()

@app.on_event("shutdown")
async def on_shutdown():
    await close_http_client()

# Serve static web assets
web_dir = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

@app.get("/healthz")
async def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    if request.query_params.get("tab") or request.query_params.get("demo_case"):
        index_file = web_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    approach_file = web_dir / "approach.html"
    if approach_file.exists():
        return HTMLResponse(content=approach_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>GTM Outreach Backend Ready</h1>")

@app.get("/recipient")
@app.get("/personalised")
async def serve_recipient():
    return RedirectResponse(url="/?tab=live-run", status_code=303)

@app.get("/tier3")
@app.get("/person")
async def serve_tier3():
    return RedirectResponse(url="/?tab=live-run", status_code=303)

@app.post("/api/runs")
async def create_run(req: RunCreate, background_tasks: BackgroundTasks):
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    
    # Extract recipient fields
    recip_name = req.recipient_name or req.person_name or (req.recipient.get("name") if isinstance(req.recipient, dict) else None)
    recip_role = req.recipient_title or req.recipient_role or req.role_hint or (req.recipient.get("title") if isinstance(req.recipient, dict) else None)
    context_snippets = req.context or req.sdr_context or []

    person_hints = req.person_hints or {}
    company_hint = req.company_hint or person_hints.get("company_hint") or req.company_name
    city_hint = req.city_hint or person_hints.get("city_hint") or req.country_hint
    role_hint = req.role_hint or person_hints.get("role_hint") or recip_role
    linkedin_hint = req.linkedin_hint or person_hints.get("linkedin_hint")

    hints = {
        "website_hint": req.website_hint,
        # A person's city is useful for S0 identity resolution but does not imply company HQ.
        "country_hint": req.country_hint or (city_hint if not req.person_name else None),
        "city_hint": city_hint,
        "industry_hint": req.industry_hint,
        "recipient_name": recip_name,
        "recipient_role": recip_role,
        "recipient_title": recip_role,
        "context": context_snippets,
        "sdr_context": context_snippets,
        "person_name": req.person_name,
        "company_hint": company_hint,
        "role_hint": role_hint,
        "linkedin_hint": linkedin_hint,
        "company_override": req.company_override,
        "role_override": req.role_override,
    }
    company_input = req.company_name or company_hint or (f"Prospect: {req.person_name}" if req.person_name else "Target")

    # If cache is enabled (default), check if this matches any demo scenarios from the approach page
    if req.use_cache:
        matched_case = match_demo_case(
            company_name=req.company_name or company_hint,
            person_name=req.person_name,
            role=recip_role,
            demo_case=req.demo_case
        )
        if matched_case:
            create_and_seed_cached_run(run_id, matched_case, company_input, req.person_name, hints)
            background_tasks.add_task(replay_cached_demo, run_id, matched_case)
            return {"run_id": run_id, "status": "queued", "cached": True, "demo_case": matched_case}

    insert_run(run_id, company_input, hints, req.mode, person_name=req.person_name)
    
    # Launch async pipeline in background task
    background_tasks.add_task(start_run, run_id, company_input, hints, req.mode)
    
    return {"run_id": run_id, "status": "queued", "cached": False}

@app.get("/api/runs/{run_id}/events")
async def run_events_sse(run_id: str, request: Request):
    """Server-Sent Events endpoint streaming live stages and progress."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        # Subscribe before replaying persisted history to close the gap where
        # an event could otherwise be emitted between the read and subscription.
        queue = await subscribe(run_id)
        try:
            try:
                query_id = request.query_params.get("last_id")
                header_id = request.headers.get("last-event-id")
                last_id = max(0, int(query_id or header_id or "0"))
            except (TypeError, ValueError):
                last_id = 0

            current_run = get_run(run_id)
            is_active = current_run and current_run.get("status") in [
                "running", "drafting", "checking", "scoring", "resolving", "researching", "discovering"
            ]

            for ev in get_run_events(run_id, after_id=last_id):
                last_id = max(last_id, int(ev["id"]))
                yield format_sse(ev)
                if ev.get("event_type") in ["run_completed", "stage_failed"] and not is_active:
                    return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev_data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    event_id = int(ev_data.get("id", 0))
                    # Events produced while the persisted replay was loading
                    # are present in both sources; emit each id only once.
                    if event_id and event_id <= last_id:
                        continue
                    last_id = max(last_id, event_id)
                    yield format_sse(ev_data)
                    if ev_data.get("event_type") in ["run_completed", "stage_failed"]:
                        break
                except asyncio.TimeoutError:
                    # Send heartbeat ping to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/runs/{run_id}/clarify")
async def submit_clarification(run_id: str, req: ClarifyRequest, background_tasks: BackgroundTasks):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] != "awaiting_clarification":
        raise HTTPException(status_code=400, detail=f"Run is in state '{run['status']}', not awaiting clarification.")

    run_hints = run.get("hints") or {}
    if run_hints.get("use_cache") and run_hints.get("demo_case"):
        demo_case = run_hints["demo_case"]
        background_tasks.add_task(resume_cached_demo, run_id, demo_case)
        return {"status": "resumed", "run_id": run_id, "cached": True}

    background_tasks.add_task(
        resume_with_clarification,
        run_id,
        req.selected_domain,
        req.answers,
        req.none_of_these
    )
    return {"status": "resumed", "run_id": run_id}

@app.post("/api/runs/{run_id}/clarify-person")
async def clarify_person(run_id: str, req: PersonClarifyRequest, background_tasks: BackgroundTasks):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] != "awaiting_person_clarification":
        raise HTTPException(status_code=400, detail=f"Run is in state '{run['status']}', not awaiting person clarification.")

    run_hints = run.get("hints") or {}
    if run_hints.get("use_cache") and run_hints.get("demo_case"):
        demo_case = run_hints["demo_case"]
        background_tasks.add_task(resume_cached_demo, run_id, demo_case)
        return {"status": "resumed", "run_id": run_id, "cached": True}

    background_tasks.add_task(
        resume_person_clarification,
        run_id,
        req.selected_person_name,
        req.selected_company,
        req.selected_title,
        req.refinement_text,
        req.manual_company,
        req.manual_role,
        req.none_of_these
    )
    return {"status": "resumed", "run_id": run_id}

@app.post("/api/runs/{run_id}/override-prospect")
async def override_prospect_endpoint(run_id: str, req: ProspectOverrideRequest, background_tasks: BackgroundTasks):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    background_tasks.add_task(
        override_prospect,
        run_id,
        req.company_override,
        req.role_override,
        req.title_override,
        req.name_override
    )
    return {"status": "updating", "run_id": run_id}

@app.post("/api/runs/{run_id}/select_problem")
async def select_problem(run_id: str, req: SelectProblemRequest, background_tasks: BackgroundTasks):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Mark run as actively drafting for this hypothesis immediately
    update_run_status(run_id, "drafting", selected_hypothesis_id=req.hypothesis_id, final_draft_id=None)
    
    background_tasks.add_task(
        generate_pipeline_for_hypothesis,
        run_id,
        req.hypothesis_id
    )
    return {"status": "processing", "run_id": run_id, "hypothesis_id": req.hypothesis_id}

@app.get("/api/runs")
async def list_runs():
    runs = get_all_runs(limit=40)
    return {"runs": runs}

@app.get("/api/demo-cases")
async def list_demo_cases():
    cache = get_demo_cache()
    return {
        "cases": [
            {
                "case_id": k,
                "name": v.get("name"),
                "events_count": len(v.get("events", [])),
                "hypotheses_count": len(v.get("hypotheses", [])),
                "evidence_count": len(v.get("evidence", [])),
                "has_draft": len(v.get("drafts", [])) > 0
            }
            for k, v in cache.items()
        ]
    }

@app.get("/api/runs/{run_id}")
async def get_run_details(run_id: str):
    data = get_run_full_details(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data

@app.post("/api/drafts/{draft_id}/review")
async def review_draft(draft_id: str, req: ReviewRequest):
    conn = get_db()
    # Find run for this draft
    row = conn.execute(
        "SELECT d.run_id, r.status AS run_status FROM drafts d JOIN runs r ON r.id = d.run_id WHERE d.id = ?",
        (draft_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Draft not found")
    
    run_id = row["run_id"]
    if row["run_status"] not in {"pending_review", "approved", "edited", "rejected"}:
        conn.close()
        raise HTTPException(status_code=409, detail="Draft cannot be reviewed while its run is still processing.")

    if req.status == "edited" and req.reviewer_edits and req.reviewer_edits.strip():
        draft_row = conn.execute(
            "SELECT quality_report FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        try:
            quality_report = json.loads(draft_row["quality_report"] or "{}")
        except (TypeError, ValueError):
            quality_report = {}
        notes = quality_report.get("notes") or []
        notes.append("Human-edited after automated QA; recheck claim grounding against evidence.")
        quality_report.update({"verdict": "review_recommended", "notes": notes})
        conn.execute(
            "UPDATE drafts SET body = ?, claim_map = ?, quality_report = ?, version = version + 1 WHERE id = ?",
            (req.reviewer_edits, "{}", json.dumps(quality_report), draft_id),
        )

    conn.execute(
        "INSERT INTO reviews (draft_id, run_id, status, reviewer_edits, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (draft_id, run_id, req.status, req.reviewer_edits, req.reason, time.time())
    )
    conn.execute("UPDATE runs SET status = ? WHERE id = ?", (req.status, run_id))
    conn.commit()
    conn.close()
    return {"status": "reviewed", "draft_id": draft_id, "verdict": req.status}

@app.get("/api/preflight")
async def preflight_probe():
    """Probes all providers and returns latency and health status."""
    results = {}
    
    # Tavily
    from app.config import TAVILY_API_KEY, GROQ_API_KEY, GEMINI_API_KEY
    if TAVILY_API_KEY:
        t0 = time.time()
        try:
            client = get_http_client()
            res = await client.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": "probe", "max_results": 1}, timeout=4.0)
            results["tavily"] = {"status": "ok" if res.status_code == 200 else f"http_{res.status_code}", "latency_ms": int((time.time()-t0)*1000)}
        except Exception as e:
            results["tavily"] = {"status": "error", "error": str(e)}

    # Groq
    if GROQ_API_KEY:
        t0 = time.time()
        try:
            from app.llm.router import call_groq
            await call_groq("ping", max_tokens=2, timeout=4.0)
            results["groq"] = {"status": "ok", "latency_ms": int((time.time()-t0)*1000)}
        except Exception as e:
            results["groq"] = {"status": "error", "error": str(e)}

    # Gemini
    if GEMINI_API_KEY:
        t0 = time.time()
        try:
            from app.llm.router import call_gemini
            await call_gemini("ping", timeout=4.0)
            results["gemini"] = {"status": "ok", "latency_ms": int((time.time()-t0)*1000)}
        except Exception as e:
            results["gemini"] = {"status": "error", "error": str(e)}

    return results

@app.get("/api/assumptions")
async def get_assumptions():
    return {"assumptions": ASSUMPTIONS_LOG}
