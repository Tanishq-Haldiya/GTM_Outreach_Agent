from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

class CompanyCandidate(BaseModel):
    name: str
    domain: str
    description: str = ""
    industry: str = ""
    hq: str = ""
    size_band: str = ""
    distinguishing_fact: str = ""
    corroboration_score: float = 0.0
    name_match_score: float = 0.0
    hint_match_score: float = 0.0
    liveness_score: float = 0.0
    final_score: float = 0.0
    sources: List[str] = []

class CompanyIdentity(BaseModel):
    name: str
    domain: str
    aliases: List[str] = []
    industry: str = ""
    size_band: str = ""
    stage: str = ""
    hq: str = ""
    confidence: float
    confirmation_method: str = "auto" # auto, user_selected, user_clarified
    alternatives: List[CompanyCandidate] = []
    clarification_questions: List[str] = []
    clarification_round: int = 1

class CompanyProfile(BaseModel):
    summary: str = ""
    what_it_does: str = ""
    target_consumers: str = "" # Who its consumers/ICP are (B2B, B2C, students, enterprise, etc.)
    business_model: str = ""   # How it monetizes and key operating model flows
    trajectory: str = ""       # Scale, hiring velocity, funding rounds, valuation
    sources: List[str] = []

class EvidenceItem(BaseModel):
    id: str
    researcher: str # profile, hiring, customer_voice, news, content, filings, employee_voice, status, changelog, exec_voice, compliance, sender_context
    source_type: str # website, careers, news, review, sec_filing, blog, community, status_incident, changelog, exec_voice, compliance, sdr_provided
    url: str
    title: str
    claim: str # normalized one-sentence claim
    excerpt: str # short supporting excerpt
    signal_type: str # operational_strain, manual_process, tool_stack, expansion, friction, outage_downtime, migration_sunset, leadership_priority, compliance_risk
    reliability_tier: str # A (1st-party/filing), B (reputable press), C (user reviews/community), S (sdr_provided)
    authority_score: Optional[float] = 0.85 # 0.0 to 1.0 quantitative source authority (None/unverified for sdr_provided)
    published_date: Optional[str] = None
    recency_days: Optional[int] = None
    relevance_status: str = "verified" # verified, filtered
    relevance_reason: Optional[str] = None
    # Tier 2 additions
    sdr_context_id: Optional[str] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    about: str = "company" # "person" or "company"
    sensitivity: str = "none" # "none", "personal", "sensitive"

class SDRContextSnippet(BaseModel):
    id: str
    run_id: str
    label: str # e.g. LinkedIn bio, recent post, interview quote, notes
    text: str # verbatim pasted text up to 2,000 characters
    source_url: Optional[str] = None
    provided_date: Optional[str] = None
    sensitivity_flags: List[str] = []
    entity_warning: Optional[str] = None
    created_time: float = 0.0

class ProblemHypothesis(BaseModel):
    id: str
    problem: str # clear operational problem statement
    lens: str # finance_ops, procurement, customer_support, sales_ops, compliance_kyc, supply_chain, hr, etc.
    lens_explanation: Optional[str] = None # why this lens fits this company
    layer: str # stated, implied, inferred
    category_label: str = "Direct / Stated (Explicit)" # "Direct / Stated (Explicit)" vs "Inferred / Assumed (Hypothesized)"
    evidence_ids: List[str] = []
    evidence_strength: float = 0.0
    business_impact: float = 0.0
    automatability: float = 0.0
    timeliness: float = 0.0
    buyer_credibility: float = 0.0
    final_score: float = 0.0 # Role-adjusted score when role is provided, otherwise base score
    base_score: Optional[float] = None # Unadjusted company-level score
    role_fit: float = 1.0 # 1.0 primary/broad, 0.85 adjacent, 0.60 other
    role_fit_badge: str = "broad" # primary, adjacent, other, broad
    adjusted_score: Optional[float] = None
    score_breakdown: Optional[Dict[str, Any]] = None # Full deterministic formula components
    rank: Optional[int] = None
    rationale: str = ""
    root_cause: Optional[str] = None # operational root cause / volume driver
    workflow_burden: Optional[str] = None # manual steps and internal friction
    automation_fit: Optional[str] = None # how automation and human checkpoints solve it
    grounding_status: str = "pending_review" # verified only after an explicit grounding guard acceptance
    grounding_critique: Optional[str] = None
    fallback_info: Optional[Dict[str, Any]] = None
    owner_function: Optional[str] = None # Functional department owner (e.g. Customer Support/CX, Finance/Accounting, Operations)

class SolutionSketch(BaseModel):
    id: str
    hypothesis_id: str
    process_name: str
    what_it_automates: str
    input_consumed: str
    key_steps: List[str]
    human_checkpoints: List[str]
    systems_touched: List[str]
    impact_direction: str # qualitative or cited estimate
    buyer_credibility_hook: str

class OutreachDraft(BaseModel):
    id: str
    subject: str
    subject_alternatives: List[str] = []
    body: str # 90-130 words email
    linkedin_note: str # < 300 chars connection request
    why_this_hook: str # explanation for the SDR/reviewer
    selected_hook_id: str
    claim_map: Dict[str, List[str]] = {} # sentence -> list of evidence_ids
    quality_verdict: str = "pending" # pass, pass_with_repair, flagged
    quality_notes: List[str] = []
    version: int = 1
    draft_style: str = "direct"  # "direct" | "inferred" — controls which S6 template was used
    recipient_fields_used: Optional[Dict[str, Any]] = None
    person_hook_cited: bool = False

class QualityReport(BaseModel):
    passed_swap_test: bool = True
    unsupported_claims: List[str] = []
    word_count: int = 0
    invented_numbers_detected: bool = False
    verdict: str = "pass"
    repaired: bool = False
    notes: List[str] = []

class PersonCandidate(BaseModel):
    name: str
    first_name: Optional[str] = None
    title_raw: str = ""
    company_raw: str = ""
    source_url: str = ""
    source_type: str = "web"
    date_seen: Optional[str] = None
    location: Optional[str] = None
    title_normalized: str = ""
    function: str = ""
    seniority: str = ""
    is_current: bool = True
    snippet_text: str = ""
    name_match_score: float = 0.0
    employment_corroboration: float = 0.0
    hint_match_score: float = 0.0
    recency_score: float = 0.0
    final_score: float = 0.0
    evidence_urls: List[str] = []
    independent_sources_count: int = 1
    ambiguity_factor: float = 1.0

class PersonProfile(BaseModel):
    name: str
    first_name: str = ""
    company_raw: str = ""
    title_raw: str = ""
    title_normalized: str = ""
    function: str = "Executive/GM"
    seniority: str = "C-level"
    location: Optional[str] = None
    evidence_urls: List[str] = []
    confidence: float = 1.0
    role_source: str = "web"  # "web" | "manual"
    role_confidence: float = 1.0
    as_of_date: Optional[str] = None
    alternatives: List[PersonCandidate] = []
    clarification_questions: List[str] = []

class PersonClarifyRequest(BaseModel):
    selected_person_name: Optional[str] = None
    selected_company: Optional[str] = None
    selected_title: Optional[str] = None
    none_of_these: bool = False
    refinement_text: Optional[str] = None
    manual_company: Optional[str] = None
    manual_role: Optional[str] = None

class ProspectOverrideRequest(BaseModel):
    company_override: Optional[str] = None
    role_override: Optional[str] = None
    title_override: Optional[str] = None
    name_override: Optional[str] = None

class RunCreate(BaseModel):
    company_name: Optional[str] = ""
    person_name: Optional[str] = None
    company_hint: Optional[str] = None
    city_hint: Optional[str] = None
    role_hint: Optional[str] = None
    linkedin_hint: Optional[str] = None
    person_hints: Optional[Dict[str, Any]] = None
    company_override: Optional[str] = None
    role_override: Optional[str] = None
    title_override: Optional[str] = None
    website_hint: Optional[str] = None
    country_hint: Optional[str] = None
    industry_hint: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_role: Optional[str] = None
    recipient_title: Optional[str] = None # Alias for recipient_role
    recipient: Optional[Dict[str, Any]] = None # Optional {"name": "...", "title": "..."}
    context: Optional[List[Dict[str, Any]]] = None # Optional pasted snippets
    sdr_context: Optional[List[Dict[str, Any]]] = None # Alias for context
    mode: str = "fast" # fast or deep; other legacy values follow fast behavior
    use_cache: bool = True # replay cached results & processes for rate-limit safe demos
    demo_case: Optional[str] = None # explicit scenario identifier (e.g. ramp_company)

class ClarifyRequest(BaseModel):
    selected_domain: Optional[str] = None # if user picks a candidate card
    none_of_these: bool = False
    answers: Optional[Dict[str, str]] = None # answers to clarifying questions

class ReviewRequest(BaseModel):
    status: Literal["approved", "edited", "rejected"]
    reviewer_edits: Optional[str] = None
    reason: Optional[str] = None

class SelectProblemRequest(BaseModel):
    hypothesis_id: str

class StageEvent(BaseModel):
    run_id: str
    stage: str
    event_type: str
    message: str
    payload: Dict[str, Any] = {}
    timestamp: float
    duration: float = 0.0
