# Zamp AI Solutions Analyst — Grounded GTM Outreach Engine
> **PS-3: Personalised Outreach (From Prospect to Draft)**  
> Autonomous, evidence-grounded B2B operational intelligence and outreach engine with strict anti-hallucination guardrails and interactive human-in-the-loop review.

![Test Suite](https://img.shields.io/badge/tests-pytest-lightgrey)
[![Live UI](https://img.shields.io/badge/dashboard-http%3A%2F%2Flocalhost%3A8000-blue)](http://localhost:8000)
[![Documentation](https://img.shields.io/badge/docs-DOCUMENTATION.md-orange)](./DOCUMENTATION.md)

---

## ⚡ Quickstart & Live Run

### 1. Prerequisites
Ensure Python 3.10+ is installed:
```bash
pip install fastapi uvicorn pydantic httpx requests groq google-genai python-dotenv rapidfuzz beautifulsoup4 pyyaml pytest
```

### 2. Environment Setup
Create or verify your `.env` file in the project root:
```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
TAVILY_API_KEY=your_tavily_key
SERPER_API_KEY=your_serper_key  # Optional fallback
```

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

## 🏛 Pipeline Architecture at a Glance

The engine executes an 8-stage state machine designed to eliminate wrong-company outreach, hallucinated pain points, and generic bot-spam:

1. **S1 (Entity Resolution & Ambiguity Gate)**: Discovers candidate entities, validates canonical domains, and calculates a deterministic 4-factor confidence score. If confidence $< 0.80$, the engine halts and presents interactive clarification cards to the SDR.
2. **S2 (Two-Phase Grounded Research Fan-out)**:
   - **Phase 2A**: Builds an authoritative Company Profile (what it does, ICP, business model, trajectory) directly from official sources.
   - **Phase 2B**: Fans out across 6 parallel channels (official site, hiring, mobile app reviews, reverse-chronological Reddit community, press, tech stack) protected by a **Relevance Guard Agent**.
3. **S3 (Two-Tier Problem Discovery & Grounding Guard)**:
   - **Tier 1 (Direct / Stated Friction)**: Direct customer complaints from Reddit and App Stores.
   - **Tier 2 (Inferred / Trajectory Friction)**: Systemic scaling bottlenecks deduced strictly from Phase 2 facts (headcount velocity, hiring gaps, funding rounds).
   - **Grounding Guard Agent**: Verifies evidence citations, demotes ungrounded claims, and de-biases expired seasonal promotions into evergreen operational workflows.
4. **S4 (Deterministic Scoring & Freshness Multiplier)**: Ranks hypotheses using a weighted mathematical formula with a $0.65\times$ penalty for stale seasonal incidents.
5. **S5 (Workflow Solution Architecture)**: Outlines concrete ingestion formats, processing steps, automated actions, and human-in-the-loop checkpoints.
6. **S6 (Grounded Outreach Drafting)**: Generates 90–130 word email, 2–4 word peer subject line, $< 300$ character LinkedIn note, and internal SDR why-this-hook explanation.
7. **S7 (QA Gate & Adversarial Swap-The-Name Test)**: Programmatic verification of numbers, word counts, and banned buzzwords, followed by an adversarial LLM swap-the-name test and 1-pass auto-repair.
8. **S8 (Interactive SDR Review Cockpit)**: Real-time SSE streaming, dynamic evidence filter chips, one-click problem re-selection, and in-place human editing.

---

## 📖 Complete Documentation & Rationale

For the exhaustive engineering specification, design rationale behind every single stage, rate-limit resilience mechanisms, and bug post-mortems, see:
👉 **[DOCUMENTATION.md](./DOCUMENTATION.md)**

## Deploy for a Submission Demo

This repository includes a Render Blueprint in `render.yaml`. Create a Blueprint from this repository and branch `main`, then set `DEMO_ACCESS_CODE`, `GROQ_API_KEY`, `GEMINI_API_KEY`, and `TAVILY_API_KEY` as secret environment variables in Render. Use a strong access code of at least 20 characters and share it with reviewers separately from the public URL. The app prompts for the code and protects its API with an HTTP-only session cookie.

The Blueprint uses Render's free web service in Singapore. Free services spin down after 15 minutes without traffic, and their filesystem is ephemeral; SQLite run history can reset after a restart. This setup is intended for a submission demo, not production storage.

---

## 🛠 Directory Structure

```
├── app/
│   ├── main.py              # FastAPI server, endpoints, SSE event stream
│   ├── orchestrator.py      # Pipeline state machine & lifecycle controller
│   ├── config.py            # Scoring weights, domain blacklists, timeouts
│   ├── models.py            # Pydantic domain models
│   ├── db.py                # SQLite persistence (runs, events, evidence, drafts)
│   ├── events.py            # In-memory event bus with SSE fan-out
│   ├── stages/
│   │   ├── s1_resolve.py    # Entity disambiguation, confidence gate & domain lock
│   │   ├── s2_research.py   # Two-phase profiler, throttled fan-out, Reddit agent
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
│       ├── index.html       # SDR review cockpit (Live View, Evidence, Decisions)
│       ├── style.css        # Responsive, high-contrast dark theme
│       └── app.js           # Real-time SSE listener & state management
├── tests/
│   ├── test_scoring.py      # S4 scoring formula unit tests
│   ├── test_router.py       # LLM JSON parsing & router fallback tests
│   ├── test_domain_filter.py# Aggregator quarantine tests
│   ├── test_clarification_loop.py # S1 disambiguation tests
│   ├── test_structured_profile_and_guards.py # S2 profiler & Relevance Guard tests
│   ├── test_anti_hallucination_guardrails.py # S3 & S7 anti-hallucination tests
│   └── test_interactive_problem_selection.py # S8 dynamic re-synthesis tests
├── DOCUMENTATION.md         # Exhaustive architecture & engineering rationale
├── outreach.db              # SQLite persistence database
└── README.md
```
