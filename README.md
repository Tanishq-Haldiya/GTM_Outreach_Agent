# Grounded GTM Outreach Engine
> Autonomous, evidence-grounded B2B operational intelligence and outreach engine with strict anti-hallucination guardrails, multi-channel researcher fan-out, rate-limit safe demo replay, and interactive human-in-the-loop review.

![Test Suite](https://img.shields.io/badge/tests-pytest-lightgrey)
[![Live UI](https://img.shields.io/badge/dashboard-http%3A%2F%2Flocalhost%3A8000-blue)](http://localhost:8000)
[![Approach Page](https://img.shields.io/badge/approach-playbook-purple)](http://localhost:8000/static/approach.html)
[![Agent Architecture](https://img.shields.io/badge/agent-map-green)](http://localhost:8000/static/agent-architecture.html)
[![Documentation](https://img.shields.io/badge/docs-DOCUMENTATION.md-orange)](./DOCUMENTATION.md)

---

## ⚡ Quickstart & Live Run

### 1. Prerequisites
Ensure Python 3.10+ is installed:
```bash
pip install -r requirements.txt
```
*(Or install directly: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `groq`, `google-genai`, `python-dotenv`, `rapidfuzz`, `beautifulsoup4`, `pyyaml`, `pytest`)*

### 2. Environment Setup
Create or verify your `.env` file in the project root:
```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
TAVILY_API_KEY=your_tavily_key
SERPER_API_KEY=your_serper_key  # Optional fallback
NVIDIA_API_KEY=your_nvidia_key  # Optional NIM reasoning fallback
```

Both Groq and Gemini support comma-separated keys (`GROQ_API_KEY="key1,key2"`) for automated round-robin rotation upon provider rate limits.

### 3. Launch the Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser to: **`http://localhost:8000`**

### 4. Run the Test Suite
```bash
python -m pytest tests/ -v
```

---

### Cached vs. Fresh Run Toggle Checkbox

Right on the launch form at `http://localhost:8000`, a dedicated toggle switch allows you to choose execution mode:
- **`[x] Use cached demo results & processes` (Checked / Default)**:
  - Replays all streaming SSE stage events, researcher activity cards, token metrics, problem hypotheses, and outreach drafts with a natural ~8–12s cadence.
  - Pauses realistically on ambiguity scenarios (Mercury, Alex Smith) and immediately resumes when the SDR confirms a candidate.
  - **100% rate-limit safe** — zero external model API quota consumed.
- **`[ ] Use cached demo results & processes` (Unchecked)**:
  - Executes a fresh, live end-to-end LLM and search pipeline query against live APIs.

> **Operational Note on Live Runs & Upstream LLM Surges**: Free/standard tier LLM APIs (such as Google Gemini Flash) occasionally experience high-demand surges or capacity throttles (HTTP 503/429). During an upstream surge, if deep review extraction degrades, our **Grounding Guard** conservatively withholds ungrounded direct complaints and falls back to inferred hypotheses rather than risking hallucinated pain points. For guaranteed evaluation fidelity without external provider congestion, we recommend testing with the pre-seeded Playbook scenarios (`[x] Use cached demo results`).

---

## 🏛 Pipeline Architecture at a Glance

The engine executes an 8-stage state machine designed to eliminate wrong-company outreach, hallucinated pain points, and generic bot-spam:

```
[Target Input] ──► [S0: Person Resolution] ──► [S1: Company Resolution & Gate]
                         │ (if person provided)           │ (clarify if conf < 0.80)
                         ▼                                ▼
[S4: Scoring & Rank] ◄── [S3: Problem Discovery] ◄── [S2: Grounded Research Fan-out]
        │                     ▲ (Grounding Guard)           (6 Parallel Source Lanes)
        ▼                     │
[S5: Solution Design] ──► [S6: Grounded Outreach] ──► [S7: Swap Test & QA] ──► [S8: Human Review]
```

1. **S0 (Person Resolution & Employer Discovery)**: Resolves executive identity, normalizes role function and seniority, and discovers employer context before company resolution.
2. **S1 (Entity Resolution & Ambiguity Gate)**: Discovers candidate entities, validates canonical domains, and calculates a deterministic 4-factor confidence score. If confidence $< 0.80$, halts and requests interactive SDR clarification.
3. **S2 (Two-Phase Grounded Research Fan-out)**:
   - **Phase 2A**: Builds an authoritative Company Profile directly from official sources.
   - **Phase 2B**: Fans out across 6 parallel channels (official site, hiring, mobile reviews, Reddit community, press, tech changelogs) protected by a **Relevance Guard Agent**.
4. **S3 (Two-Tier Problem Discovery & Grounding Guard)**:
   - **Tier 1 (Direct Friction)**: Authenticated customer complaints from Reddit, Glassdoor, and App Stores.
   - **Tier 2 (Inferred Friction)**: Systemic operational bottlenecks deduced strictly from verified operational facts.
   - **Grounding Guard Agent**: Verifies citations, strips ungrounded claims, and de-biases seasonal noise into evergreen workflows.
5. **S4 (Deterministic Scoring & Freshness Multiplier)**: Ranks hypotheses using a weighted mathematical formula with penalties for stale seasonal incidents.
6. **S5 (Workflow Solution Architecture)**: Synthesizes concrete ingestion formats, processing steps, automated actions, and human-in-the-loop checkpoints.
7. **S6 (Grounded Outreach Drafting)**: Generates a 90–130 word email, 2–4 word peer subject line, $< 300$ character LinkedIn note, and internal SDR why-this-hook rationale.
8. **S7 (QA Gate & Adversarial Swap-The-Name Test)**: Programmatic verification of numbers, word counts, and banned buzzwords, followed by an adversarial LLM swap-the-name test and 1-pass auto-repair.
9. **S8 (Interactive SDR Review Cockpit)**: Real-time SSE streaming, dynamic evidence filter chips, one-click problem re-selection, and in-place human editing.

---

## 🚀 Deploy for a Submission Demo

This repository includes a Render Blueprint in `render.yaml`. To deploy:
1. Create a Blueprint in Render from this repository (`main` branch).
2. Configure environment variables in Render:
   - `GROQ_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY`
3. The deployed app is publicly accessible.
4. Because `app/demo_cache.json` is packaged in git, demo replays work immediately out of the box even before any external API calls are made.

---

## 🛠 Directory Structure

```
├── app/
│   ├── main.py              # FastAPI server, endpoints, SSE event stream
│   ├── orchestrator.py      # Pipeline state machine & lifecycle controller
│   ├── config.py            # Scoring weights, domain blacklists, timeouts
│   ├── models.py            # Pydantic models (RunCreate with use_cache support)
│   ├── db.py                # SQLite persistence (runs, events, evidence, drafts)
│   ├── events.py            # In-memory event bus with SSE fan-out
│   ├── demo_cache.py        # Replay engine for cached demo results & processes
│   ├── demo_cache.json      # Pre-cached data for all 8 Approach page scenarios
│   ├── stages/
│   │   ├── s0_person.py     # Prospect resolution, employer discovery & role normalization
│   │   ├── s1_resolve.py    # Entity disambiguation, confidence gate & domain lock
│   │   ├── s2_research.py   # Two-phase profiler, throttled fan-out, Reddit & employee agent
│   │   ├── s3_discovery.py  # Two-tier problem discovery & Grounding Guard
│   │   ├── s4_score.py      # Deterministic scoring formula & freshness penalty
│   │   ├── s5_solution.py   # AI workflow solution architecture generator
│   │   ├── s6_draft.py      # Grounded email & LinkedIn note synthesis
│   │   └── s7_check.py      # Adversarial swap-test, numeric check & auto-repair
│   ├── llm/
│   │   ├── router.py        # Multi-model router with active cooldowns & zero-sleep failover
│   │   └── prompts.py       # Production prompt templates & JSON schemas
│   ├── tools/
│   │   ├── search.py        # Tavily search + Serper fallback + SQLite cache
│   │   ├── fetch.py         # Jina Reader web extractor
│   │   └── wikidata.py      # Wikidata entity disambiguation
│   └── web/
│       ├── index.html       # SDR review cockpit with cached/fresh toggle switch
│       ├── approach.html    # Approach playbook & 8 interactive scenario cards
│       ├── agent-architecture.html # Visual interactive pipeline agent map
│       ├── style.css        # Responsive, high-contrast theme & toggle styling
│       └── app.js           # Real-time SSE listener & state management
├── tests/
│   ├── test_demo_cache.py   # Verification of demo cache, scenario matching & replay
│   ├── test_scoring.py      # S4 scoring formula unit tests
│   ├── test_router.py       # LLM JSON parsing & router fallback tests
│   ├── test_domain_filter.py# Aggregator quarantine tests
│   ├── test_clarification_loop.py # S1 disambiguation tests
│   ├── test_structured_profile_and_guards.py # S2 profiler & Relevance Guard tests
│   ├── test_anti_hallucination_guardrails.py # S3 & S7 anti-hallucination tests
│   └── test_interactive_problem_selection.py # S8 dynamic re-synthesis tests
├── DOCUMENTATION.md         # Exhaustive architecture & engineering rationale
├── requirements.txt         # Project dependencies
└── README.md
```
