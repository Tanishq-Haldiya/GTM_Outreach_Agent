import sqlite3
import json
import time
from typing import Optional, List, Dict, Any
from app.config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

_db_initialized = False

def ensure_db():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True

def init_db():
    global _db_initialized

    conn = get_db()
    # WAL is database-wide; setting it on every short-lived connection adds
    # avoidable work and can contend with active readers/writers.
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        company_input TEXT NOT NULL,
        hints TEXT,
        mode TEXT DEFAULT 'fast',
        status TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        confirmation_method TEXT,
        started_time REAL NOT NULL,
        finished_time REAL,
        duration REAL,
        s1_pause_duration REAL DEFAULT 0.0,
        confirmed_company TEXT,
        company_profile TEXT,
        selected_hypothesis_id TEXT,
        final_draft_id TEXT,
        error_message TEXT
    );

    CREATE TABLE IF NOT EXISTS stage_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT,
        payload TEXT,
        timestamp REAL NOT NULL,
        duration REAL DEFAULT 0.0,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS clarifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        round INTEGER DEFAULT 1,
        questions TEXT,
        candidates_shown TEXT,
        answer TEXT,
        timestamp REAL NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS evidence (
        id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        researcher TEXT,
        source_type TEXT,
        url TEXT,
        title TEXT,
        claim TEXT,
        excerpt TEXT,
        signal_type TEXT,
        reliability_tier TEXT,
        published_date TEXT,
        recency_days INTEGER,
        created_time REAL NOT NULL,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS hypotheses (
        id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        problem TEXT,
        lens TEXT,
        layer TEXT,
        evidence_ids TEXT,
        scores TEXT,
        final_score REAL,
        rank INTEGER,
        rationale TEXT,
        lens_explanation TEXT,
        root_cause TEXT,
        workflow_burden TEXT,
        automation_fit TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS solutions (
        id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        hypothesis_id TEXT,
        payload TEXT,
        created_time REAL NOT NULL,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS drafts (
        id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        subject TEXT,
        body TEXT,
        linkedin_note TEXT,
        claim_map TEXT,
        why_this_hook TEXT,
        quality_report TEXT,
        version INTEGER DEFAULT 1,
        created_time REAL NOT NULL,
        hypothesis_id TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        status TEXT NOT NULL,
        reviewer_edits TEXT,
        reason TEXT,
        timestamp REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cache (
        cache_key TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_time REAL NOT NULL,
        ttl_seconds REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        stage TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        created_time REAL NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE TABLE IF NOT EXISTS sdr_context (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        label TEXT,
        text TEXT,
        source_url TEXT,
        provided_date TEXT,
        sensitivity_flags TEXT,
        entity_warning TEXT,
        created_time REAL NOT NULL,
        FOREIGN KEY(run_id) REFERENCES runs(id)
    );

    CREATE INDEX IF NOT EXISTS idx_runs_started_time ON runs(started_time DESC);
    CREATE INDEX IF NOT EXISTS idx_events_run_id_id ON stage_events(run_id, id);
    CREATE INDEX IF NOT EXISTS idx_evidence_run_id ON evidence(run_id);
    CREATE INDEX IF NOT EXISTS idx_hypotheses_run_id_score ON hypotheses(run_id, final_score DESC);
    CREATE INDEX IF NOT EXISTS idx_solutions_run_id_created ON solutions(run_id, created_time DESC);
    CREATE INDEX IF NOT EXISTS idx_drafts_run_id_created ON drafts(run_id, created_time DESC);
    CREATE INDEX IF NOT EXISTS idx_reviews_run_id_timestamp ON reviews(run_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_context_run_id_created ON sdr_context(run_id, created_time ASC);
    CREATE INDEX IF NOT EXISTS idx_llm_usage_run_id ON llm_usage(run_id, created_time);
    """)

    # Migrate extra hypothesis columns if missing
    existing_hypo_cols = [c[1] for c in conn.execute("PRAGMA table_info(hypotheses)").fetchall()]
    for col_name, col_type in [
        ("rank", "INTEGER"),
        ("lens_explanation", "TEXT"),
        ("root_cause", "TEXT"),
        ("workflow_burden", "TEXT"),
        ("automation_fit", "TEXT"),
        ("category_label", "TEXT"),
        ("grounding_status", "TEXT"),
        ("grounding_critique", "TEXT"),
        ("score_breakdown", "TEXT"),
        ("base_score", "REAL"),
        ("role_fit", "REAL DEFAULT 1.0"),
        ("role_fit_badge", "TEXT DEFAULT 'broad'"),
        ("adjusted_score", "REAL"),
        ("owner_function", "TEXT")
    ]:
        if col_name not in existing_hypo_cols:
            try:
                conn.execute(f"ALTER TABLE hypotheses ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # Migrate extra runs columns if missing
    existing_run_cols = [c[1] for c in conn.execute("PRAGMA table_info(runs)").fetchall()]
    for col_name, col_type in [
        ("company_profile", "TEXT"),
        ("recipient_name", "TEXT"),
        ("recipient_title", "TEXT"),
        ("recipient_lens", "TEXT"),
        ("seniority", "TEXT"),
        ("role_fit_applied", "INTEGER DEFAULT 0"),
        ("has_sender_context", "INTEGER DEFAULT 0"),
        ("fallback_banner_used", "INTEGER DEFAULT 0"),
        ("fallback_suggestions", "TEXT"),
        ("person_name", "TEXT"),
        ("person_profile", "TEXT"),
        ("person_confidence", "REAL DEFAULT 0.0"),
        ("role_source", "TEXT DEFAULT 'web'"),
        ("person_company", "TEXT"),
        ("person_title", "TEXT"),
        ("person_function", "TEXT"),
        ("person_seniority", "TEXT")
    ]:
        if col_name not in existing_run_cols:
            try:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # Migrate extra evidence columns if missing
    existing_ev_cols = [c[1] for c in conn.execute("PRAGMA table_info(evidence)").fetchall()]
    for col_name, col_type in [
        ("relevance_status", "TEXT"),
        ("relevance_reason", "TEXT"),
        ("authority_score", "REAL DEFAULT 0.85"),
        ("sdr_context_id", "TEXT"),
        ("span_start", "INTEGER"),
        ("span_end", "INTEGER"),
        ("about", "TEXT DEFAULT 'company'"),
        ("sensitivity", "TEXT DEFAULT 'none'")
    ]:
        if col_name not in existing_ev_cols:
            try:
                conn.execute(f"ALTER TABLE evidence ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # Migrate extra drafts columns if missing
    existing_draft_cols = [c[1] for c in conn.execute("PRAGMA table_info(drafts)").fetchall()]
    for col_name, col_type in [
        ("subject_alternatives", "TEXT"),
        ("recipient_fields_used", "TEXT"),
        ("person_hook_cited", "INTEGER DEFAULT 0"),
        ("hypothesis_id", "TEXT")
    ]:
        if col_name not in existing_draft_cols:
            try:
                conn.execute(f"ALTER TABLE drafts ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # Migrate tables to compound PK (run_id, id) if they were previously created with id TEXT PRIMARY KEY
    for table_name in ["evidence", "hypotheses", "solutions", "drafts"]:
        try:
            info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            has_run_id = any(c[1] == "run_id" for c in info)
            run_id_pk = any(c[1] == "run_id" and c[5] > 0 for c in info)
            if has_run_id and not run_id_pk:
                col_defs = []
                col_names = []
                for col in info:
                    cid, name, col_type, notnull, dflt, pk = col
                    col_names.append(name)
                    notnull_str = " NOT NULL" if (notnull or name in ("id", "run_id")) else ""
                    dflt_str = f" DEFAULT {dflt}" if dflt is not None else ""
                    col_defs.append(f"{name} {col_type}{notnull_str}{dflt_str}")
                col_defs_str = ",\n                ".join(col_defs)
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name}_new (
                        {col_defs_str},
                        PRIMARY KEY (run_id, id),
                        FOREIGN KEY(run_id) REFERENCES runs(id)
                    )
                """)
                cols_csv = ", ".join(col_names)
                conn.execute(f"INSERT OR IGNORE INTO {table_name}_new ({cols_csv}) SELECT {cols_csv} FROM {table_name}")
                conn.execute(f"DROP TABLE {table_name}")
                conn.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
        except Exception:
            pass

    # Migrate extra clarifications columns if missing
    existing_clarif_cols = [c[1] for c in conn.execute("PRAGMA table_info(clarifications)").fetchall()]
    if "stage" not in existing_clarif_cols:
        try:
            conn.execute("ALTER TABLE clarifications ADD COLUMN stage TEXT DEFAULT 's1'")
        except Exception:
            pass

    conn.commit()
    conn.close()
    _db_initialized = True

# Database helper functions
def insert_run(run_id: str, company: str, hints: dict, mode: str = "fast", person_name: Optional[str] = None):
    conn = get_db()
    recip_name = hints.get("recipient_name")
    recip_title = hints.get("recipient_title") or hints.get("recipient_role")
    p_name = person_name or hints.get("person_name")
    has_ctx = 1 if (hints.get("context") or hints.get("sdr_context")) else 0
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, company_input, hints, mode, status, started_time, recipient_name, recipient_title, person_name, has_sender_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, company, json.dumps(hints), mode, "queued", time.time(), recip_name, recip_title, p_name, has_ctx)
    )
    conn.commit()
    conn.close()

def update_run_status(run_id: str, status: str, **kwargs):
    conn = get_db()
    fields = ["status = ?"]
    params = [status]
    for k, v in kwargs.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v)
        fields.append(f"{k} = ?")
        params.append(v)
    params.append(run_id)
    conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()

def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("hints"):
        try: d["hints"] = json.loads(d["hints"])
        except: pass
    if d.get("confirmed_company"):
        try: d["confirmed_company"] = json.loads(d["confirmed_company"])
        except: pass
    if d.get("company_profile"):
        try: d["company_profile"] = json.loads(d["company_profile"])
        except: pass
    if d.get("person_profile"):
        try: d["person_profile"] = json.loads(d["person_profile"])
        except: pass
    return d

def get_all_runs(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM runs ORDER BY started_time DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        if d.get("hints"):
            try: d["hints"] = json.loads(d["hints"])
            except: pass
        if d.get("confirmed_company"):
            try: d["confirmed_company"] = json.loads(d["confirmed_company"])
            except: pass
        if d.get("company_profile"):
            try: d["company_profile"] = json.loads(d["company_profile"])
            except: pass
        if d.get("person_profile"):
            try: d["person_profile"] = json.loads(d["person_profile"])
            except: pass
        res.append(d)
    return res

def insert_event(run_id: str, stage: str, event_type: str, message: str, payload: dict = None, duration: float = 0.0) -> int:
    conn = get_db()
    conn.execute(
        "INSERT INTO stage_events (run_id, stage, event_type, message, payload, timestamp, duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, stage, event_type, message, json.dumps(payload or {}), time.time(), duration)
    )
    event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return event_id

def record_llm_usage(run_id: Optional[str], stage: Optional[str], provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO llm_usage (run_id, stage, provider, model, input_tokens, output_tokens, created_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, stage, provider, model, max(0, int(input_tokens or 0)), max(0, int(output_tokens or 0)), time.time()),
    )
    conn.commit()
    conn.close()

def get_run_events(run_id: str, after_id: int = 0) -> List[Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM stage_events WHERE run_id = ? AND id > ? ORDER BY id ASC",
        (run_id, after_id),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        item = dict(r)
        if item.get("payload"):
            try: item["payload"] = json.loads(item["payload"])
            except: pass
        out.append(item)
    return out

def get_run_full_details(run_id: str) -> Dict[str, Any]:
    run = get_run(run_id)
    if not run:
        return {}
    conn = get_db()
    
    # Evidence
    ev_rows = conn.execute("SELECT * FROM evidence WHERE run_id = ?", (run_id,)).fetchall()
    evidence = [dict(r) for r in ev_rows]
    
    # Hypotheses
    hyp_rows = conn.execute("SELECT * FROM hypotheses WHERE run_id = ? ORDER BY final_score DESC", (run_id,)).fetchall()
    hypotheses = []
    for r in hyp_rows:
        h = dict(r)
        if h.get("evidence_ids"):
            try: h["evidence_ids"] = json.loads(h["evidence_ids"])
            except: pass
        if h.get("scores"):
            try: h["scores"] = json.loads(h["scores"])
            except: pass
        if h.get("score_breakdown"):
            try: h["score_breakdown"] = json.loads(h["score_breakdown"])
            except: pass
        hypotheses.append(h)
        
    # Solution: prefer solution for selected_hypothesis_id if available
    selected_hyp = run.get("selected_hypothesis_id")
    final_draft = run.get("final_draft_id")
    sol_row = None
    if selected_hyp:
        sol_row = conn.execute(
            "SELECT * FROM solutions WHERE run_id = ? AND hypothesis_id = ? ORDER BY created_time DESC LIMIT 1",
            (run_id, selected_hyp)
        ).fetchone()
    if not sol_row and run.get("status") not in ["drafting", "checking", "running"]:
        sol_row = conn.execute("SELECT * FROM solutions WHERE run_id = ? ORDER BY created_time DESC LIMIT 1", (run_id,)).fetchone()

    solution = None
    if sol_row:
        sol_d = dict(sol_row)
        if sol_d.get("payload"):
            try: solution = json.loads(sol_d["payload"])
            except: pass
            
    # Draft: prefer final_draft_id or draft for selected_hypothesis_id
    draft_row = None
    if final_draft:
        draft_row = conn.execute("SELECT * FROM drafts WHERE id = ? AND run_id = ?", (final_draft, run_id)).fetchone()
    elif selected_hyp:
        # Check if drafts table has hypothesis_id column
        has_hypo_col = any(c[1] == "hypothesis_id" for c in conn.execute("PRAGMA table_info(drafts)").fetchall())
        if has_hypo_col:
            draft_row = conn.execute(
                "SELECT * FROM drafts WHERE run_id = ? AND hypothesis_id = ? ORDER BY created_time DESC LIMIT 1",
                (run_id, selected_hyp)
            ).fetchone()

    # If run is actively drafting/checking a new selection, do NOT leak the stale previous draft
    if not draft_row and run.get("status") not in ["drafting", "checking"]:
        draft_row = conn.execute("SELECT * FROM drafts WHERE run_id = ? ORDER BY created_time DESC LIMIT 1", (run_id,)).fetchone()

    draft = None
    if draft_row:
        draft = dict(draft_row)
        if draft.get("claim_map"):
            try: draft["claim_map"] = json.loads(draft["claim_map"])
            except: pass
        if draft.get("subject_alternatives"):
            try: draft["subject_alternatives"] = json.loads(draft["subject_alternatives"])
            except: pass
        if draft.get("quality_report"):
            try: draft["quality_report"] = json.loads(draft["quality_report"])
            except: pass
            
    # Reviews
    rev_rows = conn.execute("SELECT * FROM reviews WHERE run_id = ? ORDER BY timestamp DESC", (run_id,)).fetchall()
    reviews = [dict(r) for r in rev_rows]

    usage_rows = conn.execute(
        "SELECT stage, provider, model, input_tokens, output_tokens, created_time FROM llm_usage WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    llm_usage = [dict(r) for r in usage_rows]

    research_rows = conn.execute(
        "SELECT payload FROM stage_events WHERE run_id = ? AND event_type = 'researcher_activity' ORDER BY id",
        (run_id,),
    ).fetchall()
    research_activity = []
    for row in research_rows:
        try:
            research_activity.append(json.loads(row["payload"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue

    # SDR Context (Tier 2)
    ctx_rows = conn.execute("SELECT * FROM sdr_context WHERE run_id = ? ORDER BY created_time ASC", (run_id,)).fetchall()
    sdr_context = []
    for r in ctx_rows:
        c = dict(r)
        if c.get("sensitivity_flags"):
            try: c["sensitivity_flags"] = json.loads(c["sensitivity_flags"])
            except: pass
        sdr_context.append(c)
    
    max_ev = conn.execute("SELECT MAX(id) FROM stage_events WHERE run_id = ?", (run_id,)).fetchone()
    last_event_id = int(max_ev[0]) if (max_ev and max_ev[0] is not None) else 0

    conn.close()
    
    return {
        "run": run,
        "evidence": evidence,
        "hypotheses": hypotheses,
        "solution": solution,
        "draft": draft,
        "reviews": reviews,
        "llm_usage": llm_usage,
        "research_activity": research_activity,
        "sdr_context": sdr_context,
        "last_event_id": last_event_id
    }

def insert_sdr_context(
    ctx_id: str,
    run_id: str,
    label: str,
    text: str,
    source_url: Optional[str] = None,
    provided_date: Optional[str] = None,
    sensitivity_flags: Optional[List[str]] = None,
    entity_warning: Optional[str] = None
):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO sdr_context
           (id, run_id, label, text, source_url, provided_date, sensitivity_flags, entity_warning, created_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ctx_id, run_id, label, text, source_url, provided_date, json.dumps(sensitivity_flags or []), entity_warning, time.time())
    )
    conn.commit()
    conn.close()

def get_sdr_contexts_for_run(run_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sdr_context WHERE run_id = ? ORDER BY created_time ASC", (run_id,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("sensitivity_flags"):
            try: d["sensitivity_flags"] = json.loads(d["sensitivity_flags"])
            except: pass
        out.append(d)
    return out
