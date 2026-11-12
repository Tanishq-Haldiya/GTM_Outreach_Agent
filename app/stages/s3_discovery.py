import json
import uuid
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.config import AGGREGATOR_BRANDS
from app.models import ProblemHypothesis, EvidenceItem, CompanyIdentity, CompanyProfile
from app.llm.router import call_llm
from app.llm.prompts import S3_DISCOVERY_SYSTEM, S3_DISCOVERY_USER_TEMPLATE
from app.stages.s2_research import _is_evidence_claim_valid, _is_inferred_only_url

logger = logging.getLogger(__name__)

def _enforce_deterministic_tier_guard(hyp: ProblemHypothesis, evidence_map: Dict[str, EvidenceItem]) -> None:
    """
    Last-resort deterministic Tier Guard — narrow and precise.

    Only demotes a 'Direct / Stated' hypothesis in the specific case where every
    single cited evidence item's excerpt is *nothing but* a bare phone number or
    short numeric/whitespace string (i.e. the excerpt carries zero complaint signal).

    URL-based heuristics are intentionally NOT used here because:
    - Boilerplate pages are already blocked upstream in S2 (_is_evidence_claim_valid + _is_result_relevant_to_entity).
    - URL path patterns are fragile and produce false positives against legitimate complaint/incident pages.

    If S2 is working correctly, this guard should rarely fire.
    """
    if hyp.category_label != "Direct / Stated (Explicit)" and hyp.layer != "stated":
        return

    cited_items = [evidence_map[eid] for eid in hyp.evidence_ids if eid in evidence_map]
    if not cited_items:
        hyp.category_label = "Inferred / Assumed (Hypothesized)"
        hyp.layer = "inferred"
        hyp.grounding_critique = "Inferred: No cited evidence items found in pool."
        return

    DIRECT_SOURCES = {"reviews", "reddit", "community", "statuspage", "incident_report", "play_store", "app_store"}
    DIRECT_SIGNALS = {"complaint", "outage_downtime", "status_incident", "user_complaint", "bug_report", "dissatisfaction"}

    has_real_signal = False
    for ev in cited_items:
        src = (ev.source_type or "").lower()
        sig = (ev.signal_type or "").lower()
        excerpt = (ev.excerpt or "").strip()

        # Allow if the source type or signal type is an authentic complaint channel
        if any(ds in src for ds in DIRECT_SOURCES) or any(ds in sig for ds in DIRECT_SIGNALS):
            has_real_signal = True
            break

        # Only narrow demotion: excerpt is PURELY a phone number / short numeric string
        # e.g. "6366967218" or "9766881735 " — no actual textual complaint content
        is_bare_phone = (
            len(excerpt) < 30 and
            bool(re.fullmatch(r'[\d\s\-+().]+', excerpt))
        )
        if not is_bare_phone:
            # Excerpt has real textual content — treat as potentially valid
            has_real_signal = True
            break

    if not has_real_signal:
        logger.info(
            f"Narrow Tier Guard demoting '{hyp.id}': all cited excerpts are bare numeric strings "
            f"with no authentic complaint signal (sources: {[e.source_type for e in cited_items]})."
        )
        hyp.category_label = "Inferred / Assumed (Hypothesized)"
        hyp.layer = "inferred"
        hyp.grounding_critique = (
            "Inferred operational friction: Cited evidence contains only bare contact identifiers "
            "(phone numbers or codes) with no customer complaint text. Reclassified as Inferred."
        )

def _is_hypothesis_grounded_and_realistic(hyp: ProblemHypothesis, company: CompanyIdentity) -> bool:
    """
    Guardrail: Discards hypotheses contaminated by third-party aggregators or 
    proposing wildly unrealistic software/digital problems for physical/industrial firms.
    """
    text = f"{hyp.problem} {hyp.root_cause} {hyp.workflow_burden} {hyp.automation_fit}".lower()
    comp_name_lower = company.name.lower()

    # 1. Reject if hypothesis references third-party lead-gen/aggregator brands
    for brand in AGGREGATOR_BRANDS:
        if brand in text and brand not in comp_name_lower:
            logger.info(f"Guardrail rejected hypothesis mentioning aggregator '{brand}': {hyp.problem}")
            return False

    # 2. Industry realism check
    ind = (company.industry or "").lower()
    is_industrial = any(w in ind for w in ["bearing", "manufactur", "automotive", "machinery", "industrial", "hardware", "engineering", "metals", "steel"])
    if is_industrial:
        unrealistic_for_industrial = [
            "ai email writer", "outreach messages", "digital streaming",
            "content licensing rights", "saas subscription churn", "app store reviews",
            "podcast royalties", "digital rights management", "music catalog"
        ]
        if any(unr in text for unr in unrealistic_for_industrial):
            logger.info(f"Guardrail rejected unrealistic software hypothesis for industrial firm: {hyp.problem}")
            return False

    return True


def _build_inferred_signal_fallback(
    company: CompanyIdentity,
    evidence: List[EvidenceItem],
) -> Optional[ProblemHypothesis]:
    """Create one explicitly provisional inference from a verified growth signal.

    This is only used when S3's model/audit path leaves no inferred candidate.
    The claim stays tied to a real evidence ID and is marked for human review.
    """
    signal_patterns = [
        (
            "funding",
            ("funding", "fundraise", "fund-raise", "capital raise", "series a", "series b", "series c", "raised $", "secured investment"),
            "Recent funding may lead to more hiring and onboarding activity, adding coordination work for recruiting and people operations. Validate whether those workflows are scaling smoothly.",
            "hr_ops",
            "Potential recruiting and onboarding load if the company uses the funding to grow its team.",
        ),
        (
            "hiring",
            ("hiring", "open roles", "job openings", "recruiting", "headcount growth", "staff expansion"),
            "Active hiring may increase candidate review, onboarding, and team handoffs. Validate where recruiting workflows rely on manual coordination.",
            "hr_ops",
            "Potential increase in candidate review and onboarding volume from the reported hiring activity.",
        ),
        (
            "expansion",
            ("expanded into", "expanding into", "new market", "new region", "new location", "market expansion", "geographic expansion"),
            "Expansion into new markets may add cross-team handoffs and local operational work. Validate whether existing workflows can support that complexity without more manual coordination.",
            "operations",
            "Potentially more cross-team handoffs as the reported expansion adds markets or locations.",
        ),
        (
            "growth",
            ("rapid growth", "scaling quickly", "scale up", "volume increase", "orders grew", "customer growth"),
            "Reported growth may increase cross-functional handoffs and reconciliation workload. Validate which workflows, if any, are becoming harder to manage manually.",
            "operations",
            "Potential additional coordination and reconciliation load as reported volumes grow.",
        ),
    ]

    matches = []
    for item in evidence:
        source_text = f"{item.claim or ''} {item.excerpt or ''}".lower()
        for kind, terms, problem, lens, burden in signal_patterns:
            if any(term in source_text for term in terms):
                authority = float(getattr(item, "authority_score", 0.65) or 0.65)
                matches.append((authority, item, kind, problem, lens, burden))
                break

    if not matches:
        return None

    _, item, kind, problem, lens, burden = max(matches, key=lambda match: match[0])
    source_fact = (item.claim or item.excerpt or "").strip()
    return ProblemHypothesis(
        id=f"hyp_inferred_review_{uuid.uuid4().hex[:8]}",
        problem=problem,
        lens=lens,
        lens_explanation=f"A possible {kind}-related workflow pressure inferred from a verified company signal.",
        layer="inferred",
        category_label="Inferred / Assumed (Hypothesized)",
        evidence_ids=[item.id],
        evidence_strength=0.55,
        business_impact=0.65,
        automatability=0.65,
        timeliness=0.65,
        buyer_credibility=round(min(0.75, max(0.4, float(getattr(item, "authority_score", 0.65) or 0.65) * 0.75)), 2),
        root_cause=f"Observed source signal: {source_fact}",
        workflow_burden=burden,
        automation_fit="If confirmed, explore workflow automation that reduces manual coordination while keeping a human review step.",
        rationale=f"Provisional inference from cited evidence: {source_fact}",
        grounding_status="pending_review",
        grounding_critique="The cited source confirms the growth signal; the downstream workflow pressure is a hypothesis to validate with the buyer, not a reported fact.",
    )

async def audit_problem_grounding(
    hypotheses: List[ProblemHypothesis],
    evidence: List[EvidenceItem],
    company: CompanyIdentity,
    profile: Optional[CompanyProfile] = None
) -> List[ProblemHypothesis]:
    """
    Step 3 Guard Agent: Audits discovered problems against the evidence pool.
    1. Direct vs Inferred Check: Ensures items marked 'Direct / Stated (Explicit)' have actual explicit testimony in cited evidence;
       reclassifies to 'Inferred / Assumed (Hypothesized)' if only inferred from scale.
    2. Grounding Check: Rejects ungrounded or hallucinated claims.
    3. Attaches grounding_status and grounding_critique.
    """
    if not hypotheses:
        return []

    evidence_map = {e.id: e for e in evidence}
    # A hypothesis without a valid source cannot be audited or responsibly
    # presented as evidence-grounded. Drop it before prompting the auditor.
    grounded_hypotheses = []
    for hypothesis in hypotheses:
        hypothesis.evidence_ids = [eid for eid in hypothesis.evidence_ids if eid in evidence_map]
        if hypothesis.evidence_ids:
            grounded_hypotheses.append(hypothesis)
    hypotheses = grounded_hypotheses
    if not hypotheses:
        return []
    ev_summary = [{"id": e.id, "claim": e.claim, "excerpt": e.excerpt, "source": e.source_type} for e in evidence]

    hypo_summary = [
        {
            "id": h.id,
            "problem": h.problem,
            "category_label": h.category_label,
            "layer": h.layer,
            "evidence_ids": h.evidence_ids,
            "root_cause": h.root_cause
        }
        for h in hypotheses
    ]

    current_date_str = datetime.now().strftime("%B %Y")
    prompt = f"""Target Company: {company.name} ({company.domain})
Industry Context: {company.industry or 'Technology'}
Current Time Anchor: {current_date_str}
{f'Company Profile: What it does: {profile.what_it_does} | ICP: {profile.target_consumers} | Model: {profile.business_model}' if profile else ''}

Verified Evidence Pool:
{json.dumps(ev_summary, indent=2)}

Discovered Problem Hypotheses to Audit:
{json.dumps(hypo_summary, indent=2)}

TASK FOR HYPOTHESIS GROUNDING GUARD AGENT:
1. Verify if each problem statement is genuinely grounded in the cited evidence.
2. DIRECT VS INFERRED AUDIT (NON-NEGOTIABLE GROUNDING RULE):
   - A problem is "Direct / Stated (Explicit)" ONLY if the cited evidence ACTUALLY contains authentic direct customer complaints, user reviews (e.g. Reddit, Play Store, App Store, Trustpilot), bug reports, or official company outage postmortems.
   - If the cited evidence is merely a customer service contact number, phone directory, support email, branch location, FAQ desk, hiring posting, funding round, or general corporate announcement (e.g. listing a phone number for "E-Payment related issues: 6366967218" or branch addresses), IT IS STRICTLY AN INFERRED HYPOTHESIS, NOT A DIRECT PROBLEM!
   - In all such cases, you MUST reclassify:
     * category_label: "Inferred / Assumed (Hypothesized)"
     * layer: "inferred"
     * grounding_critique: State clearly that manual exception handling is inferred from operational support indicators (e.g. dedicated phone line) rather than an explicit customer complaint.
   - For an explicitly labeled inferred hypothesis, the cited evidence must support the underlying signal, but it does not need to state the downstream workflow problem as a fact. A plausible second-order inference (for example, funding may lead to hiring and onboarding load) should be accepted as a hypothesis, with a critique that tells the SDR to validate it. Reject it only when the cited evidence is irrelevant, contradicts the inference, or points to a different company.
3. RECENCY & TEMPORAL VALIDITY AUDIT (CRITICAL):
   - Current Date Anchor: {current_date_str}.
   - Check if any problem statement is narrowly anchored to an expired seasonal promotion or holiday campaign from months ago (e.g. 'New Year streak', 'Valentine promo', 'Black Friday').
   - If the problem references an expired seasonal event:
     * If the underlying issue is an ONGOING, SYSTEMIC operational challenge across the company's workflows (e.g. physical reward/milestone merchandise delivery delays), REVISE the 'problem' field to state the ongoing systemic operational bottleneck (NOT the expired seasonal holiday), and keep timeliness high (0.80 - 0.90).
     * If it was merely an isolated, one-off seasonal promotion that has concluded, set timeliness <= 0.35 and note in grounding_critique that it is a stale seasonal incident.
4. VERDICT:
   - "accept": Problem is grounded in the cited evidence.
   - "reject": Problem is completely hallucinated or contradicts the company's real business.
5. Provide a crisp 1-sentence grounding_critique explaining the evidence anchor and timeliness.

Output strictly in JSON:
{{
  "evaluations": [
    {{
      "id": "hyp_id",
      "verdict": "accept | reject",
      "problem": "Revised problem statement if seasonal terms needed de-biasing, or original problem",
      "category_label": "Direct / Stated (Explicit) | Inferred / Assumed (Hypothesized)",
      "layer": "stated | implied | inferred",
      "timeliness": 0.85,
      "grounding_critique": "Crisp 1-sentence explanation of evidence grounding and timeliness"
    }}
  ]
}}"""

    try:
        audit_res = await call_llm(
            prompt,
            system_prompt="You are a strict Operational Quality and Evidence Grounding Auditor.",
            task_type="fast",
            json_mode=True
        )
        if isinstance(audit_res, dict) and "evaluations" in audit_res:
            eval_map = {ev["id"]: ev for ev in audit_res["evaluations"] if "id" in ev}
            audited_hypotheses = []
            for h in hypotheses:
                audit = eval_map.get(h.id)
                if audit and audit.get("verdict", "").lower() == "reject":
                    logger.info(f"Grounding Guard Agent rejected ungrounded hypothesis {h.id}: {h.problem}")
                    continue
                if audit:
                    if audit.get("problem") and len(audit["problem"]) > 10:
                        h.problem = audit["problem"]
                    h.category_label = audit.get("category_label", h.category_label)
                    h.layer = audit.get("layer", h.layer)
                    if audit.get("timeliness") is not None:
                        try:
                            h.timeliness = float(audit["timeliness"])
                        except (ValueError, TypeError):
                            pass
                    h.grounding_status = "verified"
                    h.grounding_critique = audit.get("grounding_critique", "Verified against cited evidence.")
                else:
                    h.grounding_status = "pending_review"

                # Enforce deterministic Python tier check
                _enforce_deterministic_tier_guard(h, evidence_map)
                audited_hypotheses.append(h)

            return audited_hypotheses
    except Exception as e:
        logger.warning(f"Hypothesis grounding audit warning: {e}")

    # If the audit model is unavailable, retain only source-linked hypotheses
    # and clearly label them for human review instead of claiming verification.
    for h in hypotheses:
        h.grounding_status = "pending_review"
        if not h.grounding_critique:
            h.grounding_critique = "Automated grounding audit unavailable; verify cited evidence before use."
        _enforce_deterministic_tier_guard(h, evidence_map)
    return hypotheses

async def discover_problems(
    company: CompanyIdentity,
    evidence: List[EvidenceItem],
    profile: Optional[CompanyProfile] = None
) -> List[ProblemHypothesis]:
    """
    S3 Problem Discovery (2-Tier Architecture):
    1. First finds Direct Problems explicitly mentioned in user reviews, Reddit, community complaints, or company posts.
    2. Then infers/assumes operational challenges the company 'might' face based on trajectory and scaling facts.
    3. Runs the result through the Hypothesis Grounding Guard Agent for rigorous verification.
    """
    source_verified_evidence = [
        e for e in evidence if _is_evidence_claim_valid(e.claim, e.excerpt, company)
    ]
    clean_evidence = source_verified_evidence
    if not clean_evidence:
        clean_evidence = evidence

    evidence_payload = [
        {
            "id": e.id,
            "researcher": e.researcher,
            "source_type": e.source_type,
            "claim": e.claim,
            "excerpt": e.excerpt,
            "tier": e.reliability_tier,
            "signal": e.signal_type,
            "url": e.url
        }
        for e in clean_evidence
    ]

    # --- TIER 1: DIRECT PROBLEMS DISCOVERY ---
    # Filter evidence strictly for authentic customer complaints, reviews, user feedback, or outages.
    # Inferred-only pages (careers, FAQ, press, branch listings) are explicitly excluded from Tier 1 —
    # they carry legitimate inferred signals but cannot support a Direct / Stated hypothesis.
    direct_candidates_payload = []
    for ep in evidence_payload:
        exc = (ep.get("excerpt") or "").lower()
        url = (ep.get("url") or "")
        src = (ep.get("source_type") or "").lower()
        sig = (ep.get("signal") or "").lower()

        # Structural exclusion: inferred-only pages (careers, FAQ, press, branch) → Tier 2 only
        if url and _is_inferred_only_url(url):
            continue

        # Content exclusion: bare phone numbers or contact-desk phrases in non-review sources
        has_phone = bool(re.search(r'\b\d{8,12}\b', exc))
        is_contact_phrase = any(w in exc for w in ["call us", "phone no", "parking no", "pin:"])
        if (has_phone or is_contact_phrase) and not any(ds in src for ds in ["review", "reddit", "community"]):
            continue

        if any(ds in src for ds in ["review", "reddit", "community", "statuspage", "incident_report", "play_store", "app_store"]):
            direct_candidates_payload.append(ep)
        elif any(ds in sig for ds in ["complaint", "outage_downtime", "status_incident", "user_complaint"]):
            direct_candidates_payload.append(ep)
        elif any(w in exc for w in ["worst", "poor service", "not working", "broken", "failed", "charged", "delay", "fraud", "cancelled", "terrible", "refund not"]):
            direct_candidates_payload.append(ep)

    all_hypotheses: List[ProblemHypothesis] = []
    valid_evidence_ids = {e.id for e in clean_evidence}
    evidence_lookup = {e.id: e for e in clean_evidence}

    if direct_candidates_payload:
        current_date_str = datetime.now().strftime("%B %Y")
        direct_prompt = f"""Target Company: {company.name} ({company.domain})
Industry: {company.industry or 'Technology'}
Current Time Anchor: {current_date_str}
{f'Company Profile: What it does: {profile.what_it_does} | Consumers: {profile.target_consumers} | Model: {profile.business_model}' if profile else ''}

Direct Evidence Pool (Reviews & Complaints):
{json.dumps(direct_candidates_payload, indent=2)}

TASK TIER 1: EXTRACT DIRECT / STATED PROBLEMS ONLY
Scan the evidence specifically for EXPLICIT operational friction, user complaints, or bottlenecks directly mentioned in customer reviews, Reddit forums, public customer feedback, or official outage posts.

CRITICAL NON-NEGOTIABLE GROUNDING RULES:
1. Customer support desk directories, phone numbers, contact listings (e.g. 'E-Payment related issues: 6366967218'), parking/branch addresses, or FAQ links ARE NOT DIRECT COMPLAINTS! They are corporate operational contact points. NEVER generate a 'Direct / Stated' problem from contact lines or corporate support directories.
2. CURRENT DATE: Today is {current_date_str}.
3. DO NOT anchor a problem to an expired seasonal holiday or past promotional campaign from months ago (e.g. "New Year streak", "Valentine promo").
4. If NO authentic direct customer complaints exist in the evidence, return an EMPTY array for hypotheses.

Output strictly in JSON:
{{
  "hypotheses": [
    {{
      "id": "hyp_dir_1",
      "problem": "Clear, specific 1-sentence operational problem directly stated by users/company",
      "lens": "customer_support | supply_chain_logistics | fulfillment_ops | finance_ops",
      "lens_explanation": "Why this lens applies",
      "layer": "stated",
      "category_label": "Direct / Stated (Explicit)",
      "evidence_ids": ["ev_id"],
      "evidence_strength": 0.9,
      "business_impact": 0.85,
      "automatability": 0.85,
      "timeliness": 0.85,
      "buyer_credibility": 0.9,
      "root_cause": "The specific operational bottleneck described in the evidence",
      "workflow_burden": "What users endure or what internal teams manually handle",
      "automation_fit": "Targeted workflow automation solution with human checkpoints",
      "rationale": "Directly mentioned by users in cited evidence"
    }}
  ]
}}"""
        try:
            dir_res = await call_llm(direct_prompt, system_prompt="You are a strict operational analyst identifying direct, explicit customer friction from evidence.", task_type="large_context", json_mode=True)
            if isinstance(dir_res, dict) and "hypotheses" in dir_res:
                for item in dir_res["hypotheses"]:
                    ev_ids = [eid for eid in item.get("evidence_ids", []) if eid in valid_evidence_ids]
                    if not ev_ids:
                        logger.info("Dropping direct hypothesis without valid cited evidence: %s", item.get("problem", ""))
                        continue

                    cited_auths = [getattr(evidence_lookup[eid], "authority_score", 0.85) for eid in ev_ids if eid in evidence_lookup]
                    avg_auth = sum(cited_auths) / len(cited_auths) if cited_auths else 0.85
                    base_cred = float(item.get("buyer_credibility", 0.9))
                    grounded_cred = round(0.5 * base_cred + 0.5 * avg_auth, 2)

                    hyp = ProblemHypothesis(
                        id=f"hyp_{uuid.uuid4().hex[:8]}",
                        problem=item.get("problem", "Operational workflow friction"),
                        lens=item.get("lens", "operations"),
                        lens_explanation=item.get("lens_explanation") or f"Pertains directly to {item.get('lens', 'operational')} workflows.",
                        layer="stated",
                        category_label="Direct / Stated (Explicit)",
                        evidence_ids=ev_ids,
                        evidence_strength=float(item.get("evidence_strength", 0.9)),
                        business_impact=float(item.get("business_impact", 0.85)),
                        automatability=float(item.get("automatability", 0.85)),
                        timeliness=float(item.get("timeliness", 0.85)),
                        buyer_credibility=grounded_cred,
                        root_cause=item.get("root_cause", ""),
                        workflow_burden=item.get("workflow_burden", ""),
                        automation_fit=item.get("automation_fit", ""),
                        rationale=item.get("rationale", "Directly stated in customer/community evidence.")
                    )
                    if _is_hypothesis_grounded_and_realistic(hyp, company):
                        all_hypotheses.append(hyp)
        except Exception as e:
            logger.warning(f"Tier 1 direct problem discovery warning: {e}")
    else:
        logger.info("No direct review/complaint evidence in pool; Tier 1 skipping directly to Tier 2 Inferred discovery.")

    # --- TIER 2: INFERRED / TRAJECTORY PROBLEMS DISCOVERY ---
    # Synthesizes Phase 2 outputs (hiring trends, headcount velocity, funding rounds, tools, operational indicators) with Company Profile
    trajectory_signals = [
        {
            "id": e.id,
            "researcher": e.researcher,
            "source_type": e.source_type,
            "claim": e.claim,
            "excerpt": e.excerpt,
            "signal": e.signal_type
        }
        for e in clean_evidence
        if e.researcher in [
            "operational_scale_strain", "hiring_and_operations", "news_and_scale", "systems_and_tools",
            "changelogs_and_migrations", "status_and_incidents", "executive_voice_and_priorities", "compliance_and_regulatory",
            "employee_voice_and_ops"
        ]
        or e.signal_type in [
            "operational_strain", "manual_process", "expansion", "tool_stack",
            "migration_sunset", "status_incident", "leadership_priority", "compliance_risk"
        ]
    ]

    existing_problems_summary = "\n".join([f"- {h.problem} (Category: {h.category_label})" for h in all_hypotheses])
    needed_inferred = max(2, 4 - len(all_hypotheses))

    inferred_prompt = f"""Target Company: {company.name} ({company.domain})
Industry: {company.industry or 'Technology'}
{f'Company Profile: What it does: {profile.what_it_does} | Consumers: {profile.target_consumers} | Model: {profile.business_model} | Trajectory: {profile.trajectory}' if profile else ''}

VERIFIED PHASE 2 TRAJECTORY, HIRING & OPERATIONAL SIGNALS:
{json.dumps(trajectory_signals, indent=2) if trajectory_signals else "Refer to general evidence pool below."}

Full Evidence Pool:
{json.dumps(evidence_payload, indent=2)}

Already Identified Direct Problems:
{existing_problems_summary or "None"}

TASK TIER 2: INFERRED / ASSUMED OPERATIONAL PROBLEMS
Deduce {needed_inferred} distinct operational problem hypotheses that {company.name} "might" face by directly synthesizing Phase 2 outputs:
1. Support Desks, Manual Verification & Contact Numbers (e.g. dedicated phone lines for e-payment errors, branch dispatch coordination) -> Deduces manual exception handling, reconciliation delays, or phone triage bottlenecks.
2. Hiring Trends & Manual Process Roles (e.g. hiring manual coordinators, operations analysts, customer support reps) -> Incurring manual review backlogs, ticket queues, or training lag.
3. Headcount Growth & Scale Metrics (e.g. rapid staff expansion, +129% yearly) -> Straining cross-functional handoffs, roadmap alignment, or sprint planning.
4. Funding Rounds, Expansions & Volume Spikes (e.g. recent capital raise, multi-state distribution) -> Triggering financial reconciliation bottlenecks, vendor contract compliance, or regulatory tax/audit lag.
5. Systems, Stack & Integrations -> Fragmented tools, manual spreadsheet exports, or reconciliation delays.

RULES FOR TIER 2 AGENT:
- DO NOT duplicate the direct customer complaints already identified above.
- ANCHOR TO PHASE 2 EVIDENCE: You MUST link each inferred hypothesis to the exact Phase 2 evidence IDs (e.g. evidence_ids: ["ev_id"]) from the Trajectory & Hiring Signals above that justify your operational inference.
- Clearly categorize as category_label: "Inferred / Assumed (Hypothesized)" and layer: "inferred".
- Score realistic metrics (evidence_strength: 0.6-0.75, business_impact: 0.7-0.85, automatability: 0.8-0.9, timeliness: 0.7-0.85).

Output strictly in JSON:
{{
  "hypotheses": [
    {{
      "id": "hyp_inf_1",
      "problem": "Clear operational problem the company might face deduced from Phase 2 hiring/trajectory facts",
      "lens": "operations | finance_ops | supply_chain_logistics | compliance_kyc | hr_ops",
      "lens_explanation": "Why this lens applies based on their business model and scaling facts",
      "layer": "inferred",
      "category_label": "Inferred / Assumed (Hypothesized)",
      "evidence_ids": ["ev_id_of_hiring_or_scale_fact"],
      "evidence_strength": 0.7,
      "business_impact": 0.8,
      "automatability": 0.85,
      "timeliness": 0.75,
      "buyer_credibility": 0.8,
      "root_cause": "The operational scaling bottleneck derived from Phase 2 facts",
      "workflow_burden": "Manual overhead internal teams likely endure as a result",
      "automation_fit": "Targeted automation solution with human audit checkpoints",
      "rationale": "Deduced from Phase 2 hiring trajectory and scaling facts"
    }}
  ]
}}"""

    try:
        inf_res = await call_llm(inferred_prompt, system_prompt="You are an enterprise operations consultant diagnosing structural scaling strain.", task_type="large_context", json_mode=True)
        if isinstance(inf_res, dict) and "hypotheses" in inf_res:
            for item in inf_res["hypotheses"]:
                ev_ids = [eid for eid in item.get("evidence_ids", []) if eid in valid_evidence_ids]
                if not ev_ids:
                    logger.info("Dropping inferred hypothesis without valid cited evidence: %s", item.get("problem", ""))
                    continue

                cited_auths = [getattr(evidence_lookup[eid], "authority_score", 0.85) for eid in ev_ids if eid in evidence_lookup]
                avg_auth = sum(cited_auths) / len(cited_auths) if cited_auths else 0.80
                base_cred = float(item.get("buyer_credibility", 0.75))
                grounded_cred = round(0.5 * base_cred + 0.5 * avg_auth, 2)

                hyp = ProblemHypothesis(
                    id=f"hyp_{uuid.uuid4().hex[:8]}",
                    problem=item.get("problem", "Operational workflow friction"),
                    lens=item.get("lens", "operations"),
                    lens_explanation=item.get("lens_explanation") or f"Pertains directly to {item.get('lens', 'operational')} workflows.",
                    layer=item.get("layer", "inferred").lower(),
                    category_label="Inferred / Assumed (Hypothesized)",
                    evidence_ids=ev_ids,
                    evidence_strength=float(item.get("evidence_strength", 0.6)),
                    business_impact=float(item.get("business_impact", 0.75)),
                    automatability=float(item.get("automatability", 0.8)),
                    timeliness=float(item.get("timeliness", 0.65)),
                    buyer_credibility=grounded_cred,
                    root_cause=item.get("root_cause", ""),
                    workflow_burden=item.get("workflow_burden", ""),
                    automation_fit=item.get("automation_fit", ""),
                    rationale=item.get("rationale", "Derived from scaling trajectory and operational facts.")
                )
                if _is_hypothesis_grounded_and_realistic(hyp, company):
                    all_hypotheses.append(hyp)
    except Exception as e:
        logger.warning(f"Tier 2 inferred problem discovery warning: {e}")

    # --- STEP 3 GUARD AGENT: AUDIT GROUNDING ---
    audited_hypotheses = await audit_problem_grounding(all_hypotheses, clean_evidence, company, profile)
    result_hypotheses = audited_hypotheses

    # Preserve a useful, clearly provisional inferred hypothesis when verified
    # growth evidence exists but model output or the strict audit removed every
    # inference. Never synthesize one without a matching source item.
    if not any(
        h.layer == "inferred" or "inferred" in (h.category_label or "").lower()
        for h in result_hypotheses
    ):
        fallback_hypothesis = _build_inferred_signal_fallback(company, source_verified_evidence)
        if fallback_hypothesis:
            logger.info("Adding source-linked inferred hypothesis for human review: %s", fallback_hypothesis.problem)
            result_hypotheses.append(fallback_hypothesis)

    # Tag owner_function on all hypotheses
    for h in result_hypotheses:
        if not h.owner_function:
            h.owner_function = map_lens_to_owner_function(h.lens, h.problem)

    return result_hypotheses


def map_lens_to_owner_function(lens: str, problem_text: str = "") -> str:
    """Maps operational lens to canonical function taxonomy."""
    l = (lens or "").lower()
    txt = (problem_text or "").lower()
    if any(k in l for k in ["support", "cx"]):
        return "Customer Support/CX"
    if any(k in l for k in ["finance", "billing", "accounting", "invoice"]) or any(k in txt for k in ["invoice", "reconciliation", "dso"]):
        return "Finance/Accounting"
    if any(k in l for k in ["supply", "logistics", "fulfillment", "warehouse"]) or any(k in txt for k in ["dispatch", "carrier", "fulfillment"]):
        return "Supply Chain/Logistics"
    if any(k in l for k in ["compliance", "kyc", "legal", "aml", "regulatory"]):
        return "Compliance/Legal"
    if any(k in l for k in ["it", "tech", "engineering", "system"]):
        return "Engineering/IT"
    if any(k in l for k in ["hr", "people", "recruiting", "talent"]):
        return "HR/People"
    if any(k in l for k in ["sales", "gtm", "revops", "revenue"]):
        return "Sales/Growth/Marketing"
    if any(k in l for k in ["product"]):
        return "Product"
    if any(k in l for k in ["executive", "founder"]):
        return "Executive/GM"
    return "Operations"


def apply_role_filtered_discovery(
    hypotheses: List[ProblemHypothesis],
    person_profile: Optional[Any] = None
) -> List[ProblemHypothesis]:
    """
    Section 6: Role-Filtered Discovery & Fallback
    1. Tags each hypothesis with owner_function and role_fit.
    2. Applies deterministic role filter:
       - Direct match: 1.0 ('HIGH')
       - Adjacent function: 0.75 ('ADJACENT')
       - Executive: 0.80 ('HIGH/ADJACENT' with scaling bonus up to 1.0)
       - Distant: 0.40 ('LOW')
    3. Fallback: if fewer than 3 hypotheses survive with role_fit >= 0.75,
       relax filter and keep the best distant ones, marked role_fit_badge="low".
    """
    from app.roles import get_person_role_fit_multiplier

    if not hypotheses:
        return hypotheses

    target_func = getattr(person_profile, "function", None) if person_profile else None

    for h in hypotheses:
        if not h.owner_function:
            h.owner_function = map_lens_to_owner_function(h.lens, h.problem)
        if target_func:
            mult, badge = get_person_role_fit_multiplier(h.owner_function, target_func, h.problem)
            h.role_fit = mult
            h.role_fit_badge = badge.lower()

    if not target_func or target_func in ["Executive/GM", "broad"]:
        return hypotheses

    # Separate matched/adjacent vs distant
    matched = [h for h in hypotheses if h.role_fit >= 0.75]
    distant = [h for h in hypotheses if h.role_fit < 0.75]

    if len(matched) >= 3:
        return matched

    # Fallback: keep best distant hypotheses to satisfy 3-minimum guarantee
    needed = 3 - len(matched)
    distant_sorted = sorted(distant, key=lambda x: getattr(x, "final_score", 0.0), reverse=True)
    for d in distant_sorted[:needed]:
        d.role_fit_badge = "low"
        matched.append(d)

    return matched
