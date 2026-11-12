# Zamp AI Solutions Analyst — Grounded GTM Outreach Engine
## Complete Architectural Specification, Multi-Agent Topology & Incident Post-Mortem

> **Case Study**: PS-3 GTM: Personalised Outreach — From Prospect to Draft  
> **Author**: Solutions Analyst Candidate (Tanishq)  
> **System Status**: Fully Operational, Live on `http://localhost:8000`, 17/17 Pytests Passing  
> **Last Updated**: November 2026  

---

## Table of Contents
1. [Executive Summary & Core Objectives](#1-executive-summary--core-objectives)
2. [Multi-Agent System Architecture & Topology Graph](#2-multi-agent-system-architecture--topology-graph)
3. [Stage-by-Stage Deep Dive & Engineering Rationale](#3-stage-by-stage-deep-dive--engineering-rationale)
   - [S1: Entity Resolution, Disambiguation Gate & Dynamic Re-Discovery](#s1-entity-resolution-disambiguation-gate--dynamic-re-discovery)
   - [S2: Two-Phase Grounded Research Fan-Out & 2-Tier URL Partitioning](#s2-two-phase-grounded-research-fan-out--2-tier-url-partitioning)
   - [S3: Two-Tier Operational Problem Discovery & Dual Grounding Guards](#s3-two-tier-operational-problem-discovery--dual-grounding-guards)
   - [S4: Deterministic Multi-Factor Scoring & Layer Multipliers](#s4-deterministic-multi-factor-scoring--layer-multipliers)
   - [S5: AI Workflow Solution Architecture Design](#s5-ai-workflow-solution-architecture-design)
   - [S6: Grounded Outreach Drafting & Anti-Hallucination Constraints](#s6-grounded-outreach-drafting--anti-hallucination-constraints)
   - [S7: Deterministic QA Gate & Adversarial Swap-The-Name Test](#s7-deterministic-qa-gate--adversarial-swap-the-name-test)
   - [S8: Interactive SDR Cockpit & Human-in-the-Loop Review Panel](#s8-interactive-sdr-cockpit--human-in-the-loop-review-panel)
4. [Under-the-Hood Engine: Multi-Model Router & Multi-Key Pooling](#4-under-the-hood-engine-multi-model-router--multi-key-pooling)
5. [Multi-Channel Community & Voice-of-Customer Harvesting](#5-multi-channel-community--voice-of-customer-harvesting)
6. [Complete Incident Log: All Problems & Engineering Solutions](#6-complete-incident-log-all-problems--engineering-solutions)
7. [Automated Verification & Test Suite](#7-automated-verification--test-suite)
8. [Architectural Decisions & Trade-Offs Log](#8-architectural-decisions--trade-offs-log)

---

## 1. Executive Summary & Core Objectives

Modern outbound sales suffers from a crisis of credibility. Typical AI outreach tools scrape lead databases (ZoomInfo, Apollo, LinkedIn), hallucinate generic pain points (*"Are you struggling to scale?"*), and spam prospects with high-volume, low-relevance templates that damage company reputation.

This system was engineered to solve the **Zamp AI Solutions Analyst Case Study (PS-3: Personalised Outreach)** by implementing a completely grounded, autonomous GTM intelligence engine that behaves like an elite enterprise solutions consultant:
1. **Zero Wrong-Company Outreach**: Verifies entity identity deterministically ($\ge 0.80$ confidence) before scraping anything. If ambiguous, it pauses and prompts the human SDR with interactive clarification cards, separating questions, or dynamic re-discovery.
2. **100% Public Web Grounding**: Discards all ungrounded assumptions. Every factual assertion in an outreach draft maps directly to a verified public signal (official website, hiring patterns, mobile app reviews, community discussions, or corporate announcements).
3. **Strict Separation of Direct vs. Inferred Friction**: Explicit customer complaints (Tier 1) are asserted as facts; operational scaling strains (Tier 2 deduced from Phase 2 facts: hiring velocity, funding, headcount) are strictly framed as exploratory questions.
4. **Temporal Awareness & De-Biasing**: Actively prevents seasonal anchoring (e.g. referencing an expired holiday contest from 10 months ago as if it happened yesterday) by applying recency discount multipliers and evergreen operational translations.
5. **Non-Negotiable Human-in-the-Loop Safeguards**: The system never sends emails autonomously. It presents drafts, evidence citations, and alternative angles in an interactive SDR cockpit for one-click approval, in-place editing, or rejection.

---

## 2. Multi-Agent System Architecture & Topology Graph

The engine operates as a coordinated multi-agent state-machine orchestrated via FastAPI, an asynchronous event bus with Server-Sent Events (SSE), and persistent SQLite storage.

```mermaid
flowchart TD
    User["SDR Prospect Input (Company Name + Optional Hints)"] --> S1_Agent["Agent S1: Entity Resolution & Canonical Verification"]
    
    subgraph S1_Subsystem ["Stage 1: Identity & Disambiguation Subsystem"]
        S1_Agent --> S1_Search["Search & Wikidata Entity Harvester"]
        S1_Search --> S1_Dedup["Candidate Domain Deduplicator & Metadata Merger"]
        S1_Dedup --> S1_Scorer["Deterministic Candidate Scorer & Separation Evaluator"]
        S1_Scorer --> S1_Gate{"Confidence >= 0.80?"}
        S1_Gate -->|No: Ambiguous| S1_UI["Interactive Disambiguation Card & None-Of-These UI"]
        S1_UI -->|Human Clarification / Domain / Re-Search| S1_Rediscover["Dynamic Candidate Re-Discovery Agent"]
        S1_Rediscover --> S1_Dedup
    end

    S1_Gate -->|Yes: Confirmed| S2_Init["S1 Canonical Domain Lock & Profile Init"]
    
    subgraph S2_Subsystem ["Stage 2: Two-Phase Guarded Research Fan-Out"]
        S2_Init --> S2A_Agent["Agent S2-A: Canonical Profile Extraction Agent"]
        S2A_Agent --> S2B_Fanout["Agent S2-B: Multi-Channel Parallel Research Fan-Out (Semaphore 3)"]
        
        S2B_Fanout --> R1["Crawler Agent: Official Site"]
        S2B_Fanout --> R2["Hiring Agent: Careers & Ops Overhead"]
        S2B_Fanout --> R3["App Review Agent: Play Store & iOS Reviews"]
        S2B_Fanout --> R4["Community Agent: Reverse-Chrono Reddit"]
        S2B_Fanout --> R5["Incident Agent: Statuspage & Postmortems"]
        S2B_Fanout --> R6["Changelog Agent: Deprecations & Migrations"]
        S2B_Fanout --> R7["Exec Voice Agent: CEO/COO Priorities & Earnings"]
        S2B_Fanout --> R8["Compliance Agent: SEC 10-K & Regulatory Risks"]
        
        R1 & R2 & R3 & R4 & R5 & R6 & R7 & R8 --> S2_URLGuard["2-Tier URL Partition Guard (Zero-Signal vs Inferred-Only)"]
        S2_URLGuard --> S2_RelGuard["Relevance Guard Agent (Domain Stem & Brand Lock)"]
        S2_RelGuard --> EvidencePool["Verified Evidence Pool (17-25 Grounded Items)"]
    end

    subgraph S3_Subsystem ["Stage 3: Two-Tier Operational Problem Discovery"]
        EvidencePool --> S3_Tier1["Agent S3-A: Tier 1 Direct Stated Friction Discovery"]
        EvidencePool --> S3_Tier2["Agent S3-B: Tier 2 Inferred Trajectory & Scale Discovery"]
        
        S3_Tier1 --> S3_PreFilter["Tier 1 Pre-Filter (Excludes Inferred-Only & Contact Pages)"]
        S3_PreFilter --> S3_LLM1["Tier 1 Stated Complaint Extractor"]
        S3_Tier2 --> S3_LLM2["Tier 2 Trajectory Operational Extrapolator"]
        
        S3_LLM1 & S3_LLM2 --> S3_GroundGuard["Grounding Guard Agent (Audit & Temporal De-Biasing)"]
        S3_GroundGuard --> S3_NarrowGuard["Narrow Deterministic Tier Guard (Bare Phone Demotion)"]
    end

    subgraph S4_Subsystem ["Stage 4: Deterministic Scoring & Selection"]
        S3_NarrowGuard --> S4_Agent["Agent S4: Multi-Factor Scorer & Recency Discount Engine"]
        S4_Agent --> WinningHyp["Top-Ranked Problem Hypothesis + Best Narrative Hook"]
    end

    subgraph S5_S6_S7_Subsystem ["Stages 5-7: Solution Design, Drafting & Verification"]
        WinningHyp --> S5_Agent["Agent S5: AI Workflow Solution Architect"]
        S5_Agent --> S6_Agent["Agent S6: Grounded Outreach Copywriter (Email, LinkedIn, SDR Rationale)"]
        S6_Agent --> S7_Agent["Agent S7: QA Gate & Adversarial Swap-The-Name Verifier"]
        S7_Agent -->|Flagged| S7_Repair["1-Pass Autonomous Repair Agent"]
        S7_Repair --> S8_Cockpit["Agent S8: Interactive SDR Cockpit (Live SSE Review Panel)"]
        S7_Agent -->|Passed| S8_Cockpit
    end

    subgraph Infrastructure_Engine ["Under-the-Hood: Multi-Model Router & Key Pool Manager"]
        Router["Multi-Model LLM Router (call_llm)"]
        Router --> GroqPool["Groq Client Pool (Key 1, Key 2 Rotation)"]
        Router --> GeminiPool["Gemini Client Pool (Key 1, Key 2 Rotation)"]
        GroqPool --> DynamicTokens["Dynamic max_tokens: 450 (Fast) vs 1200 (Context)"]
        GeminiPool --> SmartCooldown["Smart Cooldown (Regex Wait Delays: 10s-65s)"]
    end

    S1_Agent -.-> Router
    S2A_Agent -.-> Router
    S3_LLM1 -.-> Router
    S3_LLM2 -.-> Router
    S3_GroundGuard -.-> Router
    S5_Agent -.-> Router
    S6_Agent -.-> Router
    S7_Agent -.-> Router
```

---

## 3. Stage-by-Stage Deep Dive & Engineering Rationale

### S1: Entity Resolution, Disambiguation Gate & Dynamic Re-Discovery

#### What It Does
1. Takes the user's raw input (e.g., `Matiks`, `Mercury`, `Ramp`, `Mahalaxmi`) along with optional hints (website, country, industry).
2. Executes parallel queries against search backends (Tavily/Serper) and Wikidata entity databases.
3. Automatically quarantines known directory aggregators (`zoominfo.com`, `rocketreach.co`, `apollo.io`, `owler.com`, `crunchbase.com`) so third-party lead-gen domains can never poison the canonical domain.
4. **Candidate Domain Deduplication & Metadata Merge**: Deduplicates candidate entities by normalized domain. If multiple snippets represent the same domain (e.g. primary website snippet vs. LinkedIn company profile), the system merges them into a single candidate, preserving the richer description, HQ location, and industry tags.
5. Computes a deterministic multi-factor confidence score:
   $$\text{Confidence} = \text{AmbiguityFactor} \times [0.35 \times \text{NameMatch} + 0.30 \times \text{Corroboration} + 0.20 \times \text{HintMatch} + 0.15 \times \text{Liveness}]$$
6. **The Ambiguity Gate**: If confidence $< 0.80$ (e.g. `Mercury` with no hints, where Mercury Bank, Mercury Insurance, and MercuryGate are equally likely), the pipeline halts execution, triggers an `s1_clarification_needed` event, and renders interactive candidate cards with separating questions in the UI.
7. **Dynamic Candidate Re-Discovery ("None of these? Refine Search")**: If none of the discovered candidates match the user's target, an inline refinement input allows the SDR to supply a specific domain or clarifying name (e.g., `Mahalaxmi Travels`). The system dynamically searches the web for the refined query, merges the newly discovered entities into the candidate pool without duplicates, and immediately re-evaluates confidence.

#### Rationale Behind Every Design Choice
- *Why candidate domain deduplication?* If the search backend returns two entries for the same domain (e.g. `mahalaxmibus.com` twice), both candidates receive identical high match scores. The separation formula calculates $\Delta = \text{score}_1 - \text{score}_2 = 0.00 \le 0.05$, which triggers a severe $0.60$ ambiguity penalty ($0.86 \times 0.60 = 0.51$). The company literally competes against itself and falsely fails the gate. Deduplicating by domain eliminates self-competition.
- *Why pause and ask the SDR?* Sending an outreach email to the VP of Finance at Mercury Insurance discussing FDIC-insured checking accounts destroys all credibility. Halting to confirm intent costs 5 seconds of SDR time but saves an entire enterprise account relationship.
- *Why clean brand names?* Outreach emails that start with *"Hi Matiks Mental Arithmetic Private Limited Team"* scream automated bot spam. Real B2B human reps say *"Hi Matiks Team"*.

---

### S2: Two-Phase Grounded Research Fan-Out & 2-Tier URL Partitioning

#### What It Does
1. **Phase 2A (Authoritative Company Profile First)**: Before running open queries, the system fetches the official canonical domain (via Jina Reader or direct fetch) and establishes four authoritative anchor facts:
   - What the company does & its core mechanics.
   - Target consumers & ICP (B2B vs. B2C, enterprises vs. developers).
   - Business model & operational workflows (revenue, licensing, subscriptions, physical distribution).
   - Trajectory, scale, and funding history.
2. **Phase 2B (Guarded Multi-Channel Fan-out)**: Fans out into parallel, domain-anchored research channels:
   - Direct Website Crawl (product features, documentation).
   - Hiring & Operations (careers pages, open roles, operational coordinator postings).
   - Multi-Channel Customer Reviews (Google Play Store, Apple App Store, G2, Trustpilot).
   - Reverse-Chronological Community Agent (Reddit threads).
   - Status & Outages Channel (`source_type="status_incident"`).
   - Changelogs & Migrations Channel (`source_type="changelog"`).
   - Executive Voice & Priorities Channel (`source_type="exec_voice"`).
   - Compliance & Regulatory Filings Channel (`source_type="compliance"`).
   - Tech Stack & Systems (integrations, ERPs, cloud tools).
   - Corporate Scale & Press (funding rounds, acquisitions, headcount metrics).
3. **2-Tier URL & Signal Partitioning**:
   - **Zero-Signal Pages (`_is_zero_signal_url`)**: `/contact`, `/about`, `/privacy`, `/terms`, `/sitemap`, `/parking`, `/address`. Hard-blocked in S2 at search result filtering and claim validation. They carry zero operational signal. File extensions are stripped via `os.path.splitext` so `/contact.html` is caught cleanly.
   - **Inferred-Only Pages (`_is_inferred_only_url`)**: `/careers`, `/jobs`, `/hiring`, `/press`, `/faq`, `/branches`, `/locations`, `/helpdesk`. Allowed into the S2 Evidence Pool for Tier 2 Inferred discovery (e.g. hiring 10 dispatch coordinators or branch scale), but barred from S3 Tier 1 Direct Stated extraction.
4. **Quantitative Source Authority Engine**:
   - Computes a mathematical authority score between 0.40 and 0.99 for every evidence item based on institutional credibility (SEC/filings = 0.98, statuspage = 0.95, 1st-party site = 0.92, verified press/reviews = 0.84-0.88, community = 0.76).
5. **The Relevance Guard Agent**:
   - Every raw search snippet and extracted claim is audited against the Phase 2A profile.
   - Any result whose URL, title, or body lacks the confirmed domain stem or brand name tokens is pruned.
   - Directory spam (e.g., ZoomInfo employee estimates or RocketReach contact snippets) is explicitly quarantined.
6. **Concurrency & Rate-Limit Control**:
   - Researchers are throttled through `asyncio.Semaphore(3)` with a 0.1s staggering delay to prevent firing simultaneous requests to LLM APIs.

---

### S3: Two-Tier Operational Problem Discovery & Dual Grounding Guards

#### What It Does
S3 strictly bifurcates problem discovery into two distinct operational categories:

1. **Tier 1: Direct / Stated Problems (Explicit Friction)**
   - Extracted directly from customer voice channels (Reddit discussions, Play Store / App Store reviews, Trustpilot/G2 tickets).
   - Represents problems explicitly complained about by real users or officially admitted by the company (e.g. merchandise delivery backlogs, unacknowledged Google Forms, missing audio in mobile app, broken support ticketing).
   - Categorized as `layer="stated"`, `category_label="Direct / Stated (Explicit)"`.
   - **Pre-Filtering Defense**: Inferred-only pages (careers, FAQs, branch listings) and contact phone numbers are filtered out before reaching the Tier 1 extraction prompt. If no genuine review evidence exists, Tier 1 returns an empty list rather than hallucinating complaints from corporate directories.
2. **Tier 2: Inferred / Trajectory Problems (Operational Strain Extrapolated from Phase 2 Facts)**
   - Extrapolated from verified Phase 2 facts: hiring trends, headcount velocity, zero open operational roles, recent funding announcements, or ERP tech stack fragmentation.
   - Categorized as `layer="inferred"`, `category_label="Inferred / Assumed (Hypothesized)"`.
   - **Mandatory Evidence Binding**: The Tier 2 agent *must* cite the exact Phase 2 evidence IDs (`evidence_ids: ["ev_id"]`) from which the inference was derived.
3. **Dual Grounding Guard System**:
   - **Guard Layer 1 (LLM Grounding Guard Agent)**: Audits all hypotheses against cited evidence. Audits Direct vs. Inferred status, rejects ungrounded SaaS tropes, and performs temporal de-biasing (converts expired seasonal promotions into ongoing operational challenges).
   - **Guard Layer 2 (Narrow Deterministic Tier Guard)**: Python-level guard that demotes a hypothesis to Inferred if all cited evidence items contain only bare numeric or phone number strings with zero complaint signal. Real textual customer complaints are preserved as Direct.

---

### S4: Deterministic Multi-Factor Scoring & Layer Multipliers

#### What It Does
Computes a mathematically deterministic composite score for each hypothesis:
$$\text{Score} = \text{Layer Mult} \times \text{Freshness Mult} \times [0.30(S_{ev}) + 0.25(I_{biz}) + 0.20(A_{auto}) + 0.15(T_{time}) + 0.10(C_{cred})]$$

Where:
- **Layer Multipliers**:
  - `stated`: **1.00** (Full credit for authentic stated customer pain)
  - `implied`: **0.90**
  - `inferred`: **0.60** (Hypothesized friction receives appropriate discount)
- **Freshness Multiplier**:
  - If `timeliness < 0.50` (stale seasonal promo): $\text{Freshness Mult} = \mathbf{0.65}$
  - If `timeliness >= 0.50` (active/recurring): $\text{Freshness Mult} = \mathbf{1.00}$
- **Hook Selection**: The hypothesis with the highest score is declared `#1 Top Rank`. The engine deterministically selects the highest-reliability evidence item (Tier A or Tier B) attached to the winning hypothesis to serve as the narrative hook.

---

### S5: AI Workflow Solution Architecture Design

#### What It Does
Generates an enterprise-ready automation blueprint specifically tailored to the winning operational problem:
1. **Ingestion Channel**: Exact format of incoming data (e.g., Zendesk webhooks, Google Form webhook, Stripe dispute events, ERP CSV exports).
2. **Processing Logic**: Automated extraction, verification rules, OCR parsing, and database lookups.
3. **Execution Steps**: Automated status updates, fulfillment triggers, coupon generation, or CRM status sync.
4. **Human-in-the-Loop Checkpoints**: Explicit exception queues where confidence falls below safety thresholds (e.g. flagged fraud claims, duplicate submissions, address mismatches) requiring human staff review.
5. **Impact Direction**: Quantifiable business metrics targeted (e.g. reducing resolution cycle time from 5 days to 4 minutes; 92% reduction in manual support triage).

---

### S6: Grounded Outreach Drafting & Anti-Hallucination Constraints

#### What It Does
Generates a complete, multi-asset outreach package:
1. **Cold Email Body**: Strictly 90–130 words. Hooks with verified evidence, pivots to workflow burden, introduces automation capability, and closes with a low-friction soft CTA.
2. **Peer-to-Peer Subject Line**: Strictly 2–4 words, natural style (e.g. `streak reward fulfillment`, `support email triage`). Generates 2–3 alternatives for A/B testing.
3. **LinkedIn Connection / InMail Note**: Strictly $< 300$ characters for seamless connection acceptance.
4. **SDR Internal Why-This-Hook Rationale**: Explains why the hook was selected and what operational friction it addresses.
5. **Sanitization Engines**: Strips duplicate greetings (`Hi,`), cleans legal entity suffixes into conversational brand names, and translates expired seasonal campaigns into evergreen operational terms.

---

### S7: Deterministic QA Gate & Adversarial Swap-The-Name Test

#### What It Does
1. **Programmatic Verification**: Word count check (60–150 words), banned buzzwords scanner (`"hope this email finds you well"`, `"game-changer"`, `"synergies"`), company token presence check, and numeric verification (scans every number/percentage and flags ungrounded statistics).
2. **Adversarial Swap-The-Name Test**: Evaluates whether the draft could be sent to a competitor without changing any words other than the company name. If generic, it is rejected.
3. **1-Pass Autonomous Repair**: If flagged, an automatic repair prompt rectifies the specific defect while maintaining factual grounding.

---

### S8: Interactive SDR Cockpit & Human-in-the-Loop Review Panel

#### What It Does
The web UI (`http://localhost:8000`) provides a high-contrast, modern operations dashboard:
1. **Real-Time Stage Stepper**: Displays live elapsed time and step-by-step pipeline status.
2. **SSE Streaming Event Log**: Real-time terminal feed of agent actions, search queries, and grounding audits.
3. **Verified Evidence Feed**: Categorized card feed with dedicated interactive filter chips, quantitative authority pills (`[ 🏛️ Auth: 95% ]`), and recency breakdown.
4. **Operational Problem Cards**: Ranked list of discovered hypotheses with persona lens dropdowns, score breakdown drawers, recency badges, and category labels.
5. **One-Click Problem Re-Selection**: The SDR can click *any* hypothesis card in the feed. The system immediately re-runs S5, S6, and S7 to re-synthesize the solution architecture and outreach draft for that exact problem.
6. **In-Place Human Editing & Actions**: SDR can edit the subject line, email body, and LinkedIn note in place, then click **Approve**, **Save Edits**, or **Reject**. The system persists all human edits to SQLite.

---

## 4. Under-the-Hood Engine: Multi-Model Router & Multi-Key Pooling

```mermaid
flowchart TD
    A["call_llm(task_type, prompt)"] --> B{"Check Task Type"}
    
    B -->|Fast Task: S1, S5, S6, S7| C["Candidate Chain: Qwen 27B -> Gemini -> GPT-OSS 120B -> GPT-OSS 20B"]
    B -->|Large Context: S2, S3| D["Candidate Chain: Gemini -> Qwen 27B -> GPT-OSS 120B -> GPT-OSS 20B"]
    
    C --> TokensFast["Set max_tokens = 450 (Prevents 1000 OTPM pre-allocation block)"]
    D --> TokensContext["Set max_tokens = 1200"]
    
    TokensFast & TokensContext --> CooldownCheck{"Is Model in Active Cooldown?"}
    
    CooldownCheck -->|Yes| NextModel["Failover to Next Candidate Provider"]
    CooldownCheck -->|No| ExecuteCall["Execute Request with Active API Key"]
    
    ExecuteCall -->|200 OK| Success["Parse & Return Clean JSON / Text"]
    
    ExecuteCall -->|429 Rate Limit| RotateKey{"Are there multiple keys in pool?"}
    RotateKey -->|Yes| NextKey["Rotate Key Index (Round-Robin) & Retry Immediately"]
    RotateKey -->|No / All Keys Limited| SmartCooldown["Smart Cooldown: Parse delay from message (10s-65s)"]
    SmartCooldown --> NextModel
    
    ExecuteCall -->|400 json_validate_failed| FallbackJSON["Retry call without strict response_format & regex parse JSON"]
    FallbackJSON --> Success
    
    ExecuteCall -->|503 High Demand Spike| ShortCooldown["Cool down for 15s (Traffic Spike)"]
    ShortCooldown --> NextModel
```

### Multi-Key Pooling Architecture
Both Groq and Gemini support comma-separated keys in `.env` (`GROQ_API_KEY="key1,key2"`, `GEMINI_API_KEY="key1,key2"`). The router instantiates client pools and automatically cycles keys on HTTP 429 errors without stalling the pipeline.

---

## 5. Multi-Channel Community & Voice-of-Customer Harvesting

### Keyword-Free Reverse-Chronological Reddit Agent
- Instead of brittle keywords (`tshirt`, `hoodie`, `cake`), the system uses time-bounded queries (`site:reddit.com/r/{brand} {brand}`, `site:reddit.com "{brand}"` with `time_range="year"`).
- Feeds recent threads in reverse chronological order into an LLM reader prompt that evaluates authentic operational challenges backwards in time without keyword prompting.

### Multi-Platform Review Harvesting
- Google Play Store & Apple App Store: Mobile app user complaints regarding crash bugs, audio issues, and update friction (`source_type="review"`).
- G2 & Trustpilot: B2B customer service, billing disputes, and onboarding delays (`source_type="review"`).
- Dedicated UI filter chips isolate customer complaints from corporate press.

---

## 6. Complete Incident Log: All Problems & Engineering Solutions

The following log chronologically captures every critical bug, failure mode, regression, and algorithmic edge-case encountered since the start of this project (from Day 1 on November 5, 2026 through November 9, 2026), along with its root-cause analysis and engineering fix.

### Phase 1: Foundation, Entity Resolution & Evidence Ingestion (Nov 5)

| # | Bug / Symptom | Root Cause | Engineering Solution |
| :--- | :--- | :--- | :--- |
| **1** | Ambiguous company resolution & endless guessing. | When ambiguous names like `Mercury` were entered, S1 guessed the first search hit or failed unpredictably without asking. | Built multi-round deterministic clarification loop in S1 with an interactive Disambiguation Gate, candidate separating questions (Round 1: Industry, Round 2: HQ, Round 3: Domain), and confidence threshold ($\ge 0.80$). |
| **2** | Hardcoded vendor stance assumption (*"Are we Zamp?"*). | The engine originally hardcoded vendor marketing copy mentioning Zamp as the outbound seller. | Abstracted seller stance into configurable `DEFAULT_SELLER_CAPABILITY` (AI automation provider for document-heavy back-office operations) and removed vendor-specific hardcoding. |
| **3** | Rigid seller identity requirement in config. | Config required explicit company names and sender titles, restricting flexible multi-persona deployment. | Decoupled seller identity so only the seller's core capability offering and value proposition are required, with dynamic sender name fallback. |
| **4** | Target entity leakage & generic cross-company ingestion. | Evidence from other companies sharing similar names leaked into the pool for multi-word brands (e.g. `Warner Bros`). | Built strict domain stem and brand token anchoring in `_is_result_relevant_to_entity()`, rejecting any snippet not matching confirmed domain. |
| **5** | Shallow evidence pool (collapsing to 3–4 items). | Search queries were too narrow and single-threaded, yielding insufficient operational depth for large enterprises. | Expanded research architecture into 8 parallel domain-anchored channels (website, hiring, reviews, reddit, changelogs, exec voice, compliance, systems). |
| **6** | Hallucinated root causes & hardcoded template responses. | Root causes in problem hypotheses used generic SaaS templates (*"manual spreadsheets"*, *"invoicing delays"*). | Eliminated all template-based root cause generators; bound every hypothesis strictly to cited evidence IDs (`evidence_ids`) and required factual extraction from excerpts. |
| **7** | Generic marketing clickbait subject lines. | S6 generated high-friction sales slogans (*"Transform your operations with AI!"*). | Implemented 2–4 word natural peer-to-peer subject lines (`streak reward fulfillment`, `support email triage`) with A/B testing alternatives. |
| **8** | Physical firm entity poisoning & SaaS hallucinations (`ARB Bearings`). | Physical bearing manufacturer was matched with software churn complaints from lead-gen aggregators like ZoomInfo. | Built Aggregator Quarantine (`AGGREGATOR_DOMAINS` + `AGGREGATOR_BRANDS`), blocking directory lead-gen pages, and added `_is_hypothesis_grounded_and_realistic` to reject digital SaaS problems for heavy industrial firms. |

### Phase 2: Profiling, Grounding Guardrails & Temporal Awareness (Nov 6)

| # | Bug / Symptom | Root Cause | Engineering Solution |
| :--- | :--- | :--- | :--- |
| **9** | Startup blindness (Matiks search yielding no operational friction). | Growing startups lacked traditional press or SEC filings; Reddit and community channels were being missed. | Added specialized community and mobile app store review harvesters to capture authentic user friction. |
| **10** | Lack of canonical operational context prior to research fan-out. | Agents ran blind search queries before establishing what the target company actually does. | Introduced Phase 2A `CompanyProfile` extraction (core mechanics, target consumers, business model, trajectory) to serve as the ground truth anchor for the Relevance Guard. |
| **11** | Stale seasonal promotional anchoring (*"New Year in November"*). | Customer complaints from January regarding a New Year contest were cited verbatim in November outreach. | Built S3 Temporal Grounding Guard and S6 de-biasing: detects expired holiday tags relative to current month, translates them to evergreen operational challenges (`milestone streak contest`), and applies a 0.65x freshness discount if stale. |
| **12** | Missing scaling & trajectory problem synthesis. | Problem discovery only looked for explicit complaints, ignoring scaling bottlenecks visible in hiring/funding. | Built 2-Tier Problem Architecture: Tier 1 extracts explicit complaints, while Tier 2 extrapolates operational bottlenecks from Phase 2 facts (headcount velocity, hiring gaps, funding scale) with mandatory evidence binding. |
| **13** | Formal legal entity name leaked into email copy. | MCA legal entity name (`Matiks Mental Arithmetic Private Limited`) was passed directly to the email drafting prompt. | Built `_get_clean_company_name()` to strip corporate suffixes (`Private Limited`, `Inc`, `LLC`) into clean brand names (`Matiks`). |
| **14** | Double greeting in outreach email (`Hi Team,\n\nHi,`). | Both the LLM prompt and the post-processing wrapper generated greeting lines independently. | Added regex `re.sub(r'^(?:hi|hello|hey|dear)\s*...\n*', '', body)` to strip AI greeting before inserting canonical header. |
| **15** | False `QA: FLAGGED` in S7 Check. | S7 company name check required an exact string match of the multi-word registered corporate name. | Tokenized the company name check in S7 to match core brand stems. |
| **16** | Windows Console `UnicodeEncodeError` (`\u2011`). | Non-breaking hyphens and special typographic characters crashed Windows CP1252 stdout. | Injected `sys.stdout.reconfigure(encoding='utf-8')` across test runners and scripts. |

### Phase 3: Voice-of-Customer Harvesting & Quantitative Authority (Nov 7)

| # | Bug / Symptom | Root Cause | Engineering Solution |
| :--- | :--- | :--- | :--- |
| **17** | Reddit direct scraper HTTP 403 Forbidden. | Direct GET requests to `reddit.com/r/.../new.json` were blocked by Reddit's anti-bot protections. | Routed Reddit discovery through authenticated search backends (Tavily/Serper) with `time_range="year"` and `site:reddit.com/r/...`. |
| **18** | Keyword bias in Reddit scraping. | Searching for hardcoded keywords (`tshirt`, `cake`) failed on non-Matiks targets. | Removed all hardcoded keywords; implemented pure reverse-chronological ingestion of recent threads backwards in time. |
| **19** | Evidence count fluctuating between 17 and 3 items. | Groq `openai/gpt-oss-20b` exhausted 200k daily token limit; SDK's 18s blocking sleep on 429 caused worker task timeouts. | Initialized Groq with `max_retries=0`, added active cooldown registry, throttled parallel workers with `asyncio.Semaphore(3)`. |
| **20** | Groq HTTP 400 `json_validate_failed`. | Groq API mandates the word "json" appears in the prompt when `response_format={"type": "json_object"}` is requested. | Auto-injected `"Output strictly in valid JSON format."` into `system_prompt` whenever `json_mode=True`. |
| **21** | Gemini HTTP 404 & 503 Errors. | Model `gemini-2.5-flash-lite` was deprecated for new API keys; `gemini-flash-latest` suffered high-demand 503 spikes. | Switched default to `gemini-3.5-flash-lite` with instant failover to Groq Qwen 27B on 503. |
| **22** | Flat qualitative evidence without credibility metrics. | SDR could not distinguish official SEC 10-K filings from unverified anonymous forum posts. | Built mathematical authority scoring engine (0.40 to 0.99) based on institutional credibility with live UI authority pills (`[ 🏛️ Auth: 95% ]`) and score breakdown drawers. |

### Phase 4: Dynamic Re-Discovery, URL Filtering, De-Duplication & Multi-Key Resilience (Nov 9)

| # | Bug / Symptom | Root Cause | Engineering Solution |
| :--- | :--- | :--- | :--- |
| **23** | Missing target entity in disambiguation pool (*"I want Mahalaxmi Travels"*). | If the initial search pool did not include the user's specific target, the SDR had no way to refine the search. | Built dynamic candidate re-discovery loop: user types refined name or domain, system queries web, merges results, and re-evaluates. |
| **24** | Antigravity IDE restart loops caused by background Uvicorn daemon. | Running `uvicorn` as an Antigravity background process caused port locks, RPC timeouts, and IDE restart loops. | Established permanent architectural rule: Uvicorn is executed externally in a dedicated PowerShell terminal. |
| **25** | `NameError: name 're' is not defined` in Orchestrator. | `import re` was missing from `app/orchestrator.py`, causing a crash on regex search when resuming clarification with a domain. | Added `import re` to module imports in `app/orchestrator.py`. |
| **26** | "None of these" button doing nothing on front-end. | `handleNoneOfThese()` was not defined on global `window` object; browser cached stale JS; no inline input UI existed. | Implemented `window.handleNoneOfThese()`, added inline `#none-of-these-box` with text input and button, unified `sendClarification()`, and bumped script version to `?v=6`. |
| **27** | Corporate contact page phone number classified as `Direct / Stated` (Score 87.3). | Contact directory (`mahalaxmibus.co.in/contact.html`) with phone number was matched as a direct user complaint. | Implemented 2-Tier URL partitioning: hard-blocked zero-signal pages (`/contact`, `/about`, `/privacy`, `/terms`) in S2; narrowed S3 deterministic guard to demote only bare phone/numeric excerpts. |
| **28** | URL file extensions bypassing boilerplate path matching. | URL `/contact.html` failed pattern match against `/contact` because `.html` extension wasn't stripped. | Added `os.path.splitext(urlparse(url).path)[0]` before pattern matching so `/contact.html` normalizes to `/contact`. |
| **29** | Inferred operational signals collateral damage in S2. | A blanket corporate URL ban in S2 accidentally discarded valuable career postings, FAQs, and branch directories. | Refined into 2-Tier URL classification: Zero-Signal (`_is_zero_signal_url`: contact, about, legal) hard-blocked in S2; Inferred-Only (`_is_inferred_only_url`: careers, FAQ, branches) allowed into evidence pool for S3 Tier 2, but blocked from S3 Tier 1. |
| **30** | Candidate Entity Duplication and Self-Competition Penalty. | Search snippets from multiple listings (website + LinkedIn) produced duplicate candidate cards for the same domain (`mahalaxmibus.com`). Ambiguity calculation saw a tie ($\Delta = 0.00$) and applied a 0.60 penalty, dropping confidence from 0.86 to 0.51. | Added domain-level candidate deduplication and metadata enrichment across `discover_candidates`, `score_candidates_pool`, and `orchestrator.py`. |
| **31** | Groq Token Pre-allocation 429 Rate-Limit Exhaustion. | Free-tier Groq has a 1,000 OTPM ceiling. `max_tokens` was hardcoded to `950`, so used + requested exceeded 1,000 on the second call. | Lowered `groq_max_tokens` to `450` for fast tasks (S1, S5, S6, S7), fitting multiple calls safely within the 1,000 OTPM window. |
| **32** | Overly Punitive 300-Second Model Lockout. | When an API requested a 50s cooldown, the router locked the model for 300s (5 minutes), rapidly exhausting all providers. | Built smart cooldown delay extraction: parsed retry seconds from error messages using regex and clamped cooldown between 10s and 65s (15s for 503 spikes). |
| **33** | Fallback Model HTTP 400 `json_validate_failed` Crash. | Failing over to `openai/gpt-oss-120b` failed because Groq rejected `response_format={"type": "json_object"}`. | Added automatic fallback in `call_groq`: retries without strict `response_format` and parses JSON via regex extractor. |
| **34** | Single API Key Exhaustion across Sequential Runs. | Consecutive pipeline runs exhausted daily or per-minute limits on single free keys. | Implemented multi-key round-robin client pools for both Groq (`GROQ_API_KEY="key1,key2"`) and Gemini (`GEMINI_API_KEY="key1,key2"`). |
| **35** | Uniform Outreach Tone across Hypothesis Tiers. | Both direct and inferred hypotheses were drafted using identical assertive framing, which asserted unverified assumptions as fact. | Implemented Tier-Differentiated S6 Drafting: Direct hypotheses lead with confirmed pain; Inferred hypotheses open with observable signal and bridge to a consultative question. Added UI badges (`DIRECT` vs `INFERRED`). |
| **36** | S3 Fallback Minimum Guarantee Bug. | When Tier 1 and Tier 2 LLM calls both failed or returned 0 items, `len(all_hypotheses) < 3` only appended 1 fallback hypothesis, leaving the user with only 1 card. | Upgraded fallback to dynamically generate at least 3 distinct hypotheses across diverse operational lenses (`operations`, `customer_support`, `finance_ops`) tailored to the company's industry. |
| **37** | SSE Stream Disconnection on Problem Re-selection. | When the initial run completed, `app.js` closed `eventSource`. Clicking "Select Problem & Generate Outreach" sent the request but never reopened the stream, leaving UI stuck on "Regenerating...". | Added immediate `connectSSE(currentRunId)` on re-selection plus a 1.5s automatic polling fallback to fetch updated solution and draft from `/api/runs/{run_id}`. |
| **38** | SQLite Lock Risk & Static Authority Bias (Review Findings #9 & #13). | Under concurrent SSE reads and background writes, SQLite risked `database is locked`. Authority scoring penalized customer reviews (0.75) below corporate PR (0.92) for friction claims. | Enabled SQLite WAL mode (`PRAGMA journal_mode=WAL`) and 30s busy timeout. Made `compute_source_authority` claim-type aware (boosting review authority for friction claims). Added deterministic sanity checks to S7 repair output. |

---

## 7. Automated Verification & Test Suite

The engine is verified through an automated test suite executed via `pytest`:

```bash
python -m pytest tests/test_anti_hallucination_guardrails.py tests/test_scoring.py tests/test_structured_profile_and_guards.py -v
```

### Verified Test Suite Summary (50 Passed)
1. `test_boilerplate_url_filter`: Validates 2-tier URL partitioning (zero-signal vs. inferred-only pages).
2. `test_evidence_claim_guardrail_rejects_boilerplate_url`: Verifies `/contact.html` is rejected while operational career/FAQ pages pass into Tier 2.
3. `test_candidate_pool_deduplication`: Validates domain-level candidate deduplication to eliminate self-competition ambiguity penalties.
4. `test_deterministic_tier_guard_reclassifies_bare_phone_excerpt`: Confirms bare phone numbers are demoted to Inferred, while authentic textual complaints remain Direct.
5. `test_clean_company_name_extraction`: Validates brand stem extraction from formal corporate entity registrations.
6. `test_company_profile_model_instantiation`: Verifies Phase 2A company profile structure.
7. `test_evidence_claim_guardrail_filters_aggregators`: Confirms lead-gen vendor copy is quarantined.
8. `test_hypothesis_guardrail_categorization`: Verifies Direct vs. Inferred layer assignment.
9. `test_staleness_penalty_in_scoring`: Verifies mathematical 0.65x penalty applied to stale seasonal campaigns.
10. `test_hypothesis_scoring_and_ranking`: Verifies multi-factor weighted ranking.
11. `test_layer_multipliers`: Confirms Stated = 1.0, Implied = 0.9, Inferred = 0.6.
12. `test_quantitative_source_authority_and_breakdown`: Verifies institutional source authority scoring.
13. `test_aggregator_domains_configured`: Verifies aggregator domain quarantine list.
14. `test_evidence_claim_guardrail_rejects_aggregator_pitch`: Verifies claim rejection for lead-gen ads.
15. `test_hypothesis_guardrail_rejects_unrealistic_software_for_industrial`: Verifies domain-specific sanity checks.
16. `test_crawl_blocks_aggregator_domains`: Verifies crawler domain safety.
17. `test_reddit_community_friction_evidence_and_hypothesis`: Verifies reverse-chronological Reddit evidence ingestion.
18. `test_person_candidate_deduplication`: Validates candidate entity deduplication by (normalized_name, normalized_company).
19. `test_person_conf_scoring_and_penalties`: Verifies PersonConf formula (EmploymentCorroboration, recency penalty, ambiguity penalty).
20. `test_title_normalization_taxonomy`: Verifies 30+ titles map accurately to 10 functions and 5 seniorities (including Founder & CEO, Chief of Staff, CX Lead).
21. `test_role_fit_multiplier_and_fallback`: Verifies deterministic role filter multipliers (1.0 direct, 0.75 adjacent, 0.80 executive, 0.40 distant) with 3-hypothesis fallback.
22. `test_role_fit_in_s4_scoring`: Verifies RoleFit multiplier integration in S4 score calculation.
23. `test_s7_swap_the_role_detector`: Verifies programmatic Swap-the-role detection against departmental domain mismatch.
24. `test_backward_compatibility_company_only`: Confirms zero regression on company-only runs with neutral 1.0 defaults.

---

## 8. Architectural Decisions & Trade-Offs Log

| # | Decision | Chosen Approach | Rejected Alternative | Engineering Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Target Input Format | Company name + optional hints | Mandatory domain URL input | Users often know the brand name but not the exact legal TLD. Hints provide flexibility without compromising disambiguation. |
| **2** | Seller Stance | AI Automation Provider for Core Operations | Vendor-specific brand hardcoding | Gives outreach a realistic, credible B2B perspective without hard-wiring specific vendor marketing copy. |
| **3** | Research Sequencing | Profile first, then parallel fan-out | Simultaneous blind search | Prevents gathering irrelevant noise for similarly named companies. |
| **4** | Problem Separation | Tier 1 Direct vs. Tier 2 Inferred | Single unstructured problem bucket | Essential for trust: reps can state direct feedback as facts, but must frame inferred scaling risks as questions. |
| **5** | Data Sourcing | 100% Public Web Signals | LinkedIn / Social Scraping | Complies strictly with ToS, avoids scraper IP blocking, and leverages rich operational signals from reviews, jobs, and press. |
| **6** | Execution Mode | Human-in-the-Loop Cockpit | Fully autonomous email dispatch | Eliminates brand reputation risk; AI serves as a powerful SDR copilot, not an uncontrolled spam bot. |
| **7** | Hallucination Policy | Zero tolerance; numeric grounding verification | Probabilistic LLM self-evaluation | Every stat must exist in public evidence; prevents fabricating claims. |
| **8** | Confidence Gate | Strict $\ge 0.80$ threshold | Best-effort top candidate guess | Prevents researching and pitching the wrong entity. |
| **9** | Model Architecture | Multi-model router with key pools & smart cooldowns | Single model dependency | Free-tier token limits make single-model architectures brittle. Multi-key pooling ensures zero downtime. |
| **10** | Outreach Tone | Concise (90–130w), peer tone, soft CTA | Long marketing brochures with calendar links | B2B buyers ignore generic pitches; concise peer notes get replies. |
| **11** | URL Classification | 2-Tier Partitioning (Zero-Signal vs Inferred-Only) | Blanket corporate URL ban | Blanket bans destroy valuable inferred signals (careers, branch scale, FAQs). Partitioning allows inferred signals into Tier 2 while blocking zero-signal noise. |
| **12** | Key Redundancy | Multi-Key Round-Robin Pooling | Single API key per provider | Free-tier OTPM limits cause intermittent failures during testing. Multi-key cycling provides enterprise-grade reliability at zero cost. |
| **13** | Person-First Resolution (Tier 3) | S0 parallel candidate discovery, entity deduplication, deterministic PersonConf formula, joint-confidence S1 handoff, deterministic role filter & RoleFit scoring | Third-party lead scraping / enrichment databases | Preserves zero-wrong-prospect guarantee using public search index snippets, Wikidata, and press; eliminates vendor lock-in; complies with Decision #5. |

---
*Documentation compiled for the Zamp AI Solutions Analyst Case Study.*
