import time
import json
import asyncio
import logging
import re
from typing import Dict, Any, Optional

from app.db import (
    get_run, update_run_status, get_db
)
from app.events import emit_event
from app.models import (
    CompanyIdentity, CompanyCandidate, EvidenceItem,
    ProblemHypothesis, SolutionSketch, OutreachDraft,
    PersonProfile, PersonCandidate
)
from app.roles import normalize_recipient_role, canonical_lens, suggest_roles_for_lens, normalize_person_role
from app.stages.sdr_context import sanitize_and_validate_context_snippets, extract_evidence_from_snippets
from app.stages.s0_person import resolve_person, score_person_candidates, discover_person_candidates
from app.stages.s1_resolve import resolve_company
from app.stages.s2_research import execute_research_fanout, build_company_profile
from app.stages.s3_discovery import discover_problems, apply_role_filtered_discovery
from app.stages.s4_score import score_and_select_hypothesis
from app.stages.s5_solution import design_solution
from app.stages.s6_draft import generate_draft
from app.stages.s7_check import verify_grounding

logger = logging.getLogger(__name__)


def _add_person_context_to_company_resolution(profile: PersonProfile, hints: Dict[str, Any]) -> None:
    """Carry the selected person's employer evidence into company disambiguation."""
    company = (profile.company_raw or "").strip()
    matching_roles = [
        candidate for candidate in profile.alternatives
        if (candidate.company_raw or "").strip().casefold() == company.casefold()
        and (candidate.name or "").strip().casefold() == (profile.name or "").strip().casefold()
    ]
    evidence_lines = []
    for candidate in matching_roles[:3]:
        snippet = (candidate.snippet_text or "").strip()
        source = (candidate.source_url or "").strip()
        evidence_lines.append(
            f"Current employer claim: {candidate.name} — {candidate.title_raw} at "
            f"{candidate.company_raw}; source type: {candidate.source_type}; "
            f"source URL: {source or 'not provided'}; corroborating sources: "
            f"{candidate.independent_sources_count}. Evidence: {snippet[:500] or 'no excerpt available'}"
        )

    hints["s0_person_name"] = profile.name
    hints["s0_person_company"] = company
    hints["s0_person_title"] = profile.title_normalized or profile.title_raw
    hints["s0_person_confidence"] = profile.confidence
    hints["s0_person_context"] = "\n".join(evidence_lines)
    hints["s0_evidence_urls"] = list(dict.fromkeys(
        url for candidate in matching_roles for url in candidate.evidence_urls if url
    )) or profile.evidence_urls
    evidence_url_count = len(hints["s0_evidence_urls"])
    hints["s0_employment_corroboration"] = (
        1.0 if evidence_url_count >= 2 else 0.85
    ) if profile.confidence >= 0.70 else 0.0

    # Preserve a sector qualifier when the resolved employer is labeled, e.g. "Mercury (Finance)".
    qualifiers = re.findall(r"\(([^)]+)\)", company)
    if qualifiers and not hints.get("industry_hint"):
        hints["s0_company_sector"] = " ".join(qualifiers)

async def start_run(run_id: str, company_input: str, hints: Dict[str, Any], mode: str = "fast", person_profile: Optional[PersonProfile] = None):
    """Starts a new outreach synthesis pipeline run (supports both Company-First and Person-First)."""
    start_time = time.time()
    person_name = (hints.get("person_name") or "").strip()

    # --- S0: PERSON RESOLUTION (Tier 3 Person-First Flow) ---
    if person_name and not person_profile:
        t_s0 = time.time()
        await emit_event(run_id, "s0_person", "run_started", f"Starting person-first synthesis pipeline for '{person_name}'")
        await emit_event(run_id, "s0_person", "s0_started", f"Step 0: Resolving prospect identity and employer for '{person_name}'...")
        update_run_status(run_id, "resolving_person")

        try:
            profile, s0_confirmed = await resolve_person(person_name, hints)
            person_profile = profile
            s0_dur = time.time() - t_s0

            if not s0_confirmed:
                # Pause and ask for person clarification
                update_run_status(
                    run_id,
                    "awaiting_person_clarification",
                    confidence=profile.confidence,
                    person_confidence=profile.confidence,
                    person_profile=profile.model_dump()
                )
                await emit_event(
                    run_id,
                    "s0_person",
                    "s0_clarification_needed",
                    f"Person confidence {profile.confidence:.2f} is below 0.80. Clarification required.",
                    payload={
                        "confidence": profile.confidence,
                        "person_name": person_name,
                        "candidates": [c.model_dump() for c in profile.alternatives],
                        "questions": profile.clarification_questions
                    },
                    duration=s0_dur
                )
                return

            # S0 Confirmed
            update_run_status(
                run_id,
                "person_confirmed",
                confidence=profile.confidence,
                person_confidence=profile.confidence,
                person_name=profile.name,
                person_company=profile.company_raw,
                person_title=profile.title_normalized,
                person_function=profile.function,
                person_seniority=profile.seniority,
                person_profile=profile.model_dump()
            )
            await emit_event(
                run_id,
                "s0_person",
                "s0_resolved",
                f"Resolved prospect: {profile.name} — {profile.title_normalized} at {profile.company_raw} (confidence {profile.confidence:.2f})",
                payload={"person_profile": profile.model_dump()},
                duration=s0_dur
            )
            await emit_event(
                run_id,
                "s0_person",
                "role_normalized",
                f"Role normalized: {profile.title_normalized} -> Function: {profile.function}, Seniority: {profile.seniority}",
                payload={
                    "title": profile.title_normalized,
                    "function": profile.function,
                    "seniority": profile.seniority
                }
            )

            # Seed S1 with S0 resolution & Joint-Confidence bonus
            company_input = profile.company_raw
            hints["recipient_name"] = profile.name
            hints["recipient_title"] = profile.title_normalized
            hints["recipient_role"] = profile.title_normalized
            hints["recipient_lens"] = profile.function
            hints["seniority"] = profile.seniority
            _add_person_context_to_company_resolution(profile, hints)

        except Exception as e:
            logger.exception(f"Pipeline error in S0 for run {run_id}: {e}")
            update_run_status(run_id, "failed", error_message=f"S0 failed: {e}")
            await emit_event(run_id, "s0_person", "stage_failed", f"Failed to resolve person: {e}")
            return

    # S1 Resolve & Confirm (Seeded by S0 or direct company input)
    t0 = time.time()
    await emit_event(run_id, "s1_resolve", "run_started", f"Starting company verification for '{company_input}'")
    await emit_event(run_id, "s1_resolve", "stage_started", f"Resolving and verifying company identity for '{company_input}'...")
    update_run_status(run_id, "resolving")

    try:
        identity, is_confirmed = await resolve_company(company_input, hints)
        s1_dur = time.time() - t0

        if not is_confirmed:
            # Pause and ask for clarification
            update_run_status(
                run_id,
                "awaiting_clarification",
                confidence=identity.confidence,
                confirmed_company=identity.model_dump()
            )
            await emit_event(
                run_id,
                "s1_resolve",
                "clarification_needed",
                f"Confidence {identity.confidence:.2f} is below 0.80. Clarification required.",
                payload={
                    "confidence": identity.confidence,
                    "candidates": [c.model_dump() for c in identity.alternatives],
                    "questions": identity.clarification_questions
                },
                duration=s1_dur
            )
            return

        # Auto-confirmed
        update_run_status(
            run_id,
            "confirmed",
            confidence=identity.confidence,
            confirmation_method="auto",
            confirmed_company=identity.model_dump()
        )
        await emit_event(
            run_id,
            "s1_resolve",
            "identity_confirmed",
            f"Confirmed identity: {identity.name} ({identity.domain}) with confidence {identity.confidence:.2f}",
            payload={"identity": identity.model_dump()},
            duration=s1_dur
        )

        # Proceed to S2 ... S8
        await run_stages_s2_to_s8(run_id, identity, hints, start_time, person_profile=person_profile, mode=mode)

    except Exception as e:
        logger.exception(f"Pipeline error in S1 for run {run_id}: {e}")
        update_run_status(run_id, "failed", error_message=str(e))
        await emit_event(run_id, "s1_resolve", "stage_failed", f"Failed to resolve company: {e}")

async def resume_with_clarification(
    run_id: str,
    selected_domain: Optional[str] = None,
    answers: Optional[Dict[str, str]] = None,
    none_of_these: bool = False
):
    """
    Resumes a paused run after user clarifies the entity.
    Keeps asking questions until the confidence score strictly crosses the 0.80 threshold.
    Supports dynamic candidate re-discovery when user target is not in the initial candidate pool.
    """
    run = get_run(run_id)
    if not run:
        raise ValueError("Run not found")

    start_time = run["started_time"]
    identity_data = run.get("confirmed_company") or {}
    candidates_raw = identity_data.get("alternatives", [])
    
    # Reconstruct candidate objects
    candidates = [CompanyCandidate(**c) for c in candidates_raw]
    current_round = identity_data.get("clarification_round", 1)

    # 1. Direct user candidate selection (100% explicit confirmation)
    if selected_domain:
        chosen_candidate = None
        for c in candidates:
            if c.domain == selected_domain:
                chosen_candidate = c
                break
        if not chosen_candidate:
            chosen_candidate = CompanyCandidate(
                name=run["company_input"],
                domain=selected_domain,
                description=f"Confirmed domain {selected_domain}"
            )

        identity = CompanyIdentity(
            name=chosen_candidate.name,
            domain=chosen_candidate.domain,
            industry=chosen_candidate.industry,
            hq=chosen_candidate.hq,
            confidence=1.0,
            confirmation_method="user_selected",
            alternatives=candidates
        )
        update_run_status(
            run_id,
            "confirmed",
            confidence=1.0,
            confirmation_method="user_selected",
            confirmed_company=identity.model_dump()
        )
        await emit_event(
            run_id,
            "s1_resolve",
            "identity_confirmed",
            f"User confirmed entity: {identity.name} ({identity.domain}) with 100% confidence.",
            payload={"identity": identity.model_dump()}
        )
        hints = run.get("hints") or {}
        await run_stages_s2_to_s8(run_id, identity, hints, start_time, mode=run.get("mode") or "fast")
        return

    # 2. Answer-based re-scoring loop
    from app.stages.s1_resolve import score_candidates_pool, generate_clarifying_question, discover_candidates

    conn = get_db()
    # Fetch historical answers
    history_rows = conn.execute("SELECT answer FROM clarifications WHERE run_id = ?", (run_id,)).fetchall()
    all_answers = [r["answer"] for r in history_rows if r["answer"]]
    
    new_answer_str = " ".join(answers.values()) if answers else ""
    if new_answer_str:
        all_answers.append(new_answer_str)
        conn.execute(
            "INSERT INTO clarifications (run_id, round, questions, candidates_shown, answer, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, current_round, json.dumps(identity_data.get("clarification_questions", [])), json.dumps([c.model_dump() for c in candidates]), new_answer_str, time.time())
        )
        conn.commit()
    conn.close()

    hints = run.get("hints") or {}
    scored_candidates, best, confidence, is_confirmed = score_candidates_pool(
        candidates, run["company_input"], hints, answers_history=all_answers
    )

    # Dynamic Candidate Re-Discovery:
    # If the original candidates pool failed to cross 0.80 and the user provided an answer or clicked none_of_these,
    # re-search the web for the refined entity (e.g. "Mahalaxmi Travels", "travels", "bus operator")
    if not is_confirmed and (new_answer_str or none_of_these):
        # 1. Check if user typed an explicit URL or domain in their answer
        domain_match = re.search(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.(?:com|in|org|net|co|io|app|ai|travel|biz)(?:/[^\s]*)?)', new_answer_str)
        if domain_match:
            raw_matched_domain = domain_match.group(1).split('/')[0].lower()
            matching = [c for c in candidates if c.domain.lower() == raw_matched_domain]
            if matching:
                selected_domain = raw_matched_domain
            else:
                discovered_pool = await discover_candidates(raw_matched_domain)
                if not discovered_pool:
                    discovered_pool = [CompanyCandidate(
                        name=run["company_input"],
                        domain=raw_matched_domain,
                        description=f"Direct domain {raw_matched_domain} provided by user"
                    )]
                seen_domains = set()
                merged_pool = []
                for c in discovered_pool + candidates:
                    d = (c.domain or "").lower().strip()
                    if d and d in seen_domains:
                        continue
                    if d:
                        seen_domains.add(d)
                    merged_pool.append(c)
                scored_candidates, best, confidence, is_confirmed = score_candidates_pool(
                    merged_pool, run["company_input"], hints, answers_history=[raw_matched_domain]
                )

        if not is_confirmed:
            cleaned_answer = re.sub(
                r'\b(?:none\s+of\s+these|not\s+these|different\s+company|neither|none|no|i\s+want|looking\s+for|target\s+is|it\s+is|it\'s|please\s+find|find)\b',
                '',
                new_answer_str,
                flags=re.IGNORECASE
            ).strip(' .:,;?!')
            input_lower = run["company_input"].lower()
            if cleaned_answer and input_lower in cleaned_answer.lower():
                refined_target = cleaned_answer
            elif cleaned_answer:
                refined_target = f"{run['company_input']} {cleaned_answer}"
            else:
                refined_target = run["company_input"]

            if refined_target.lower() != run["company_input"].lower():
                await emit_event(
                    run_id,
                    "s1_resolve",
                    "discovering_candidates",
                    f"Candidate refinement triggered. Searching web for refined entity: '{refined_target}'...",
                    payload={"refined_query": refined_target}
                )
                discovered_pool = await discover_candidates(refined_target)
                if discovered_pool:
                    seen_domains = set()
                    merged_candidates = []
                    for c in discovered_pool + candidates:
                        if c.domain not in seen_domains:
                            seen_domains.add(c.domain)
                            merged_candidates.append(c)

                    scored_candidates, best, confidence, is_confirmed = score_candidates_pool(
                        merged_candidates, refined_target, hints, answers_history=all_answers
                    )

    if is_confirmed:
        # Crosses threshold!
        identity = CompanyIdentity(
            name=best.name,
            domain=best.domain,
            industry=best.industry,
            hq=best.hq,
            confidence=confidence,
            confirmation_method="user_clarified",
            alternatives=scored_candidates,
            clarification_round=current_round
        )
        update_run_status(
            run_id,
            "confirmed",
            confidence=confidence,
            confirmation_method="user_clarified",
            confirmed_company=identity.model_dump()
        )
        await emit_event(
            run_id,
            "s1_resolve",
            "identity_confirmed",
            f"Confidence reached {confidence:.2f} (>= 0.80)! Confirmed target: {identity.name} ({identity.domain}).",
            payload={"identity": identity.model_dump()}
        )
        await run_stages_s2_to_s8(run_id, identity, hints, start_time, mode=run.get("mode") or "fast")
    else:
        # Still below threshold: Keep asking questions!
        next_round = current_round + 1
        next_question = generate_clarifying_question(scored_candidates, round_num=next_round)
        
        identity = CompanyIdentity(
            name=best.name,
            domain=best.domain,
            industry=best.industry,
            hq=best.hq,
            confidence=confidence,
            confirmation_method="pending",
            alternatives=scored_candidates,
            clarification_questions=[next_question],
            clarification_round=next_round
        )
        update_run_status(
            run_id,
            "awaiting_clarification",
            confidence=confidence,
            confirmed_company=identity.model_dump()
        )
        await emit_event(
            run_id,
            "s1_resolve",
            "clarification_needed",
            f"Score updated to {confidence:.2f} but still below 0.80. Round {next_round} question asked.",
            payload={
                "confidence": confidence,
                "round": next_round,
                "candidates": [c.model_dump() for c in scored_candidates],
                "questions": [next_question]
            }
        )

async def run_stages_s2_to_s8(
    run_id: str,
    identity: CompanyIdentity,
    hints: Dict[str, Any],
    pipeline_start_time: float,
    person_profile: Optional[PersonProfile] = None,
    mode: str = "fast",
):
    """Executes S2 through S8 sequentially with real-time SSE progress."""
    conn = get_db()

    # --- TIER 1 & TIER 2 PRE-PROCESSING (IN PARALLEL WITH S2) ---
    raw_title = hints.get("recipient_title") or hints.get("recipient_role") or (person_profile.title_raw if person_profile else None)
    role_norm_task = asyncio.create_task(normalize_recipient_role(raw_title))
    raw_snippets = hints.get("context") or hints.get("sdr_context") or []

    # --- S2: PROFILE & RESEARCH FAN-OUT ---
    t_s2 = time.time()
    update_run_status(run_id, "researching")
    await emit_event(run_id, "s2_research", "stage_started", f"Step 1: Building comprehensive company profile for {identity.name}...")

    # Step 1: Build structured Company Profile
    t_prof = time.time()
    profile = await build_company_profile(identity)
    prof_dur = time.time() - t_prof
    update_run_status(run_id, "researching", company_profile=profile.model_dump())
    await emit_event(
        run_id,
        "s2_research",
        "profile_built",
        f"Profile built: {profile.summary}",
        payload={"profile": profile.model_dump()},
        duration=prof_dur
    )

    # Step 2: Parallel Research Fan-out with Evidence Relevance Guard Agent
    await emit_event(run_id, "s2_research", "research_started", "Step 2: Dispatching multi-channel operational researchers with Relevance Guard Agent...")

    async def on_ev_found(ev: EvidenceItem):
        # Keep the live evidence panel responsive. Final audited evidence is
        # persisted in one batch below, avoiding a write for every candidate.
        await emit_event(
            run_id,
            "s2_research",
            "evidence_found",
            f"[{ev.researcher}] {ev.claim[:80]}...",
            payload={"evidence": ev.model_dump()}
        )

    async def process_sender_context():
        if not raw_snippets:
            return []
        from app.db import insert_sdr_context
        validated_snippets, entity_warnings, validation_notes = sanitize_and_validate_context_snippets(
            raw_snippets, identity.name, identity.aliases
        )
        for snippet in validated_snippets:
            insert_sdr_context(
                snippet["id"], run_id, snippet["label"], snippet["text"],
                snippet.get("source_url"), snippet.get("provided_date"),
                snippet.get("sensitivity_flags"), snippet.get("entity_warning")
            )
        await emit_event(
            run_id,
            "sdr_context",
            "context_validated",
            f"Validated {len(validated_snippets)} context snippets ({len(entity_warnings)} entity warnings)",
            payload={
                "count": len(validated_snippets),
                "entity_warnings": entity_warnings,
                "validation_notes": validation_notes
            }
        )
        extracted = await extract_evidence_from_snippets(validated_snippets, run_id, identity.name)
        if extracted:
            await emit_event(
                run_id,
                "sdr_context",
                "context_evidence_extracted",
                f"Extracted {len(extracted)} verified evidence items from sender context.",
                payload={"count": len(extracted), "items": [e.model_dump() for e in extracted]}
            )
        return extracted

    # Sender context is independent of public web research. Start it now so
    # its extraction latency overlaps the S2 fan-out.
    context_task = asyncio.create_task(process_sender_context())
    evidence_list = await execute_research_fanout(
        identity,
        profile=profile,
        on_evidence_found=on_ev_found,
        person_profile=person_profile,
        mode=mode,
    )
    sdr_evidence = await context_task
    evidence_list.extend(sdr_evidence)

    # Await Role Normalization
    role_info = await role_norm_task
    update_run_status(
        run_id,
        "researching",
        recipient_lens=role_info["lens"],
        seniority=role_info["seniority"],
        role_fit_applied=1 if role_info.get("role_fit_applied") else 0
    )
    await emit_event(
        run_id,
        "recipient_lens",
        "recipient_normalised",
        f"Role '{role_info['title']}' normalised to lens '{role_info['lens']}' ({role_info['seniority']})" if role_info.get("title") else "No recipient role specified; neutral weights used.",
        payload=role_info
    )

    # Sync final audited evidence list in DB (Relevance Guard filtered items + valid SDR items)
    conn.execute("DELETE FROM evidence WHERE run_id = ?", (run_id,))
    for ev in evidence_list:
        conn.execute(
            """INSERT OR REPLACE INTO evidence 
               (id, run_id, researcher, source_type, url, title, claim, excerpt, signal_type, reliability_tier, published_date, created_time, relevance_status, relevance_reason, authority_score, sdr_context_id, span_start, span_end, about, sensitivity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ev.id, run_id, ev.researcher, ev.source_type, ev.url, ev.title, ev.claim, ev.excerpt, ev.signal_type, ev.reliability_tier, ev.published_date, time.time(), getattr(ev, "relevance_status", "verified"), getattr(ev, "relevance_reason", None), getattr(ev, "authority_score", 0.85), getattr(ev, "sdr_context_id", None), getattr(ev, "span_start", None), getattr(ev, "span_end", None), getattr(ev, "about", "company"), getattr(ev, "sensitivity", "none"))
        )
    conn.commit()

    s2_dur = time.time() - t_s2
    await emit_event(
        run_id,
        "s2_research",
        "stage_completed",
        f"Research fan-out completed: verified {len(evidence_list)} evidence items matching profile.",
        payload={"count": len(evidence_list)},
        duration=s2_dur
    )

    # --- S3: PROBLEM DISCOVERY (2-TIER WITH GROUNDING GUARD) ---
    t_s3 = time.time()
    update_run_status(run_id, "discovering")
    await emit_event(run_id, "s3_discovery", "stage_started", "Step 3: Discovering problems (Tier 1 Direct user complaints first, then Tier 2 Inferred operational risks with Grounding Guard)...")

    hypotheses = await discover_problems(identity, evidence_list, profile=profile)
    if person_profile:
        hypotheses = apply_role_filtered_discovery(hypotheses, person_profile)

    s3_dur = time.time() - t_s3
    await emit_event(
        run_id,
        "s3_discovery",
        "stage_completed",
        f"Discovered {len(hypotheses)} candidate problem hypotheses (audited by Grounding Guard).",
        payload={"hypotheses": [h.model_dump() for h in hypotheses]},
        duration=s3_dur
    )

    if not hypotheses:
        # An explicit no-signal outcome is safer than generating synthetic
        # operational problems from generic fallback templates.
        total_duration = time.time() - pipeline_start_time
        conn.close()
        update_run_status(
            run_id,
            "insufficient_evidence",
            finished_time=time.time(),
            duration=round(total_duration, 2),
        )
        await emit_event(
            run_id,
            "s3_discovery",
            "run_completed",
            "Research did not produce a sufficiently grounded problem. Add a prospect hint or more context and try again.",
            payload={"reason": "insufficient_evidence"},
            duration=total_duration,
        )
        return

    # --- S4: SCORE & SELECT (WITH TIER 1 ROLE-FIT & TIER 2 HOOK) ---
    t_s4 = time.time()
    base_ranking = [h.id for h in sorted(hypotheses, key=lambda x: x.final_score, reverse=True)]

    active_lens = role_info.get("lens") or (person_profile.function if person_profile else None)
    active_title = role_info.get("title") or (person_profile.title_normalized if person_profile else None)
    active_seniority = role_info.get("seniority") or (person_profile.seniority if person_profile else None)
    active_name = hints.get("recipient_name") or (person_profile.name if person_profile else None)

    ranked_hypotheses, winning_hyp, hook_ev, fallback_info = score_and_select_hypothesis(
        hypotheses,
        evidence_list,
        recipient_lens=active_lens,
        adjacent_lenses=role_info.get("adjacent_lenses"),
        person_profile=person_profile,
        return_fallback_info=True
    )
    s4_dur = time.time() - t_s4

    if role_info.get("role_fit_applied") or (person_profile and getattr(person_profile, "function", None)):
        await emit_event(
            run_id,
            "s4_score",
            "role_fit_applied",
            f"Applied role-fit weights for {active_lens or 'target role'}",
            payload={
                "lens": active_lens,
                "ranking_before": base_ranking,
                "ranking_after": [h.id for h in ranked_hypotheses]
            }
        )

    # Persist hypotheses with structured fields, rank, guard tags, base_score, role_fit, adjusted_score, owner_function
    for h in ranked_hypotheses:
        conn.execute(
            """INSERT OR REPLACE INTO hypotheses
               (id, run_id, problem, lens, layer, evidence_ids, scores, final_score, rank, rationale, lens_explanation, root_cause, workflow_burden, automation_fit, category_label, grounding_status, grounding_critique, score_breakdown, base_score, role_fit, role_fit_badge, adjusted_score, owner_function)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (h.id, run_id, h.problem, h.lens, h.layer, json.dumps(h.evidence_ids), json.dumps({
                "strength": h.evidence_strength, "impact": h.business_impact, "auto": h.automatability,
                "timeliness": h.timeliness, "credibility": h.buyer_credibility
            }), h.final_score, h.rank, h.rationale, h.lens_explanation, h.root_cause, h.workflow_burden, h.automation_fit,
            getattr(h, "category_label", "Direct / Stated (Explicit)"),
            getattr(h, "grounding_status", "pending_review"),
            getattr(h, "grounding_critique", ""),
            json.dumps(getattr(h, "score_breakdown", {}) or {}),
            getattr(h, "base_score", h.final_score),
            getattr(h, "role_fit", 1.0),
            getattr(h, "role_fit_badge", "broad"),
            getattr(h, "adjusted_score", h.final_score),
            getattr(h, "owner_function", None))
        )
    conn.commit()

    update_run_status(
        run_id,
        "drafting",
        selected_hypothesis_id=winning_hyp.id,
        fallback_banner_used=1 if fallback_info.get("fallback_banner_used") else 0,
        fallback_suggestions=fallback_info.get("suggested_roles")
    )

    await emit_event(
        run_id,
        "s4_score",
        "stage_completed",
        f"Ranked {len(ranked_hypotheses)} hypotheses. Auto-selected #1: {winning_hyp.problem}",
        payload={
            "winner": winning_hyp.model_dump(),
            "ranked_hypotheses": [h.model_dump() for h in ranked_hypotheses],
            "hook_evidence": hook_ev.model_dump() if hook_ev else None,
            "fallback_info": fallback_info
        },
        duration=s4_dur
    )

    # --- S5: SOLUTION DESIGN ---
    t_s5 = time.time()
    await emit_event(run_id, "s5_solution", "stage_started", "Designing targeted AI/automation workflow architecture...")
    solution = await design_solution(
        identity.name,
        winning_hyp,
        hook_ev,
        recipient_title=active_title,
        recipient_lens=active_lens,
        seniority=active_seniority,
        framing_guidance=role_info.get("framing_guidance")
    )
    s5_dur = time.time() - t_s5

    conn.execute(
        "INSERT OR REPLACE INTO solutions (id, run_id, hypothesis_id, payload, created_time) VALUES (?, ?, ?, ?, ?)",
        (solution.id, run_id, winning_hyp.id, json.dumps(solution.model_dump()), time.time())
    )
    conn.commit()

    await emit_event(
        run_id,
        "s5_solution",
        "stage_completed",
        f"Solution designed: {solution.process_name}",
        payload={"solution": solution.model_dump()},
        duration=s5_dur
    )

    # --- S6: DRAFTING ---
    t_s6 = time.time()
    await emit_event(run_id, "s6_draft", "stage_started", "Drafting evidence-grounded outreach email and LinkedIn note...")
    draft = await generate_draft(
        identity.name,
        winning_hyp,
        hook_ev,
        solution,
        recipient_name=active_name,
        recipient_role=active_title,
        recipient_lens=active_lens,
        seniority=active_seniority,
        framing_guidance=role_info.get("framing_guidance")
    )
    s6_dur = time.time() - t_s6
    await emit_event(
        run_id,
        "s6_draft",
        "stage_completed",
        f"Draft created ({len(draft.body.split())} words) with 1 grounded hook and SDR rationale.",
        payload={"draft": draft.model_dump()},
        duration=s6_dur
    )

    # --- S7: GROUNDING CHECK ---
    t_s7 = time.time()
    update_run_status(run_id, "checking")
    await emit_event(run_id, "s7_check", "stage_started", "Running automated Swap-The-Name test and claim verification...")

    verified_draft, quality_report = await verify_grounding(draft, identity.name, evidence_list)
    s7_dur = time.time() - t_s7
    swap_test_unavailable = any(
        "swap test unavailable" in note.lower() or "no valid verdict" in note.lower()
        for note in quality_report.notes
    )
    swap_test_status = "PASSED" if quality_report.passed_swap_test else ("UNAVAILABLE" if swap_test_unavailable else "FAILED")

    # Persist draft
    conn.execute(
        """INSERT OR REPLACE INTO drafts 
           (id, run_id, subject, subject_alternatives, body, linkedin_note, claim_map, why_this_hook, quality_report, version, created_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (verified_draft.id, run_id, verified_draft.subject, json.dumps(verified_draft.subject_alternatives),
         verified_draft.body, verified_draft.linkedin_note, json.dumps(verified_draft.claim_map),
         verified_draft.why_this_hook, json.dumps(quality_report.model_dump()),
         verified_draft.version, time.time())
    )
    conn.commit()
    conn.close()

    await emit_event(
        run_id,
        "s7_check",
        "stage_completed",
        f"Quality checks completed (Verdict: {quality_report.verdict}, Swap Test: {swap_test_status}).",
        payload={"report": quality_report.model_dump(), "draft": verified_draft.model_dump()},
        duration=s7_dur
    )

    # --- S8: FINISHED / PENDING REVIEW ---
    total_duration = time.time() - pipeline_start_time
    update_run_status(
        run_id,
        "pending_review",
        final_draft_id=verified_draft.id,
        finished_time=time.time(),
        duration=round(total_duration, 2)
    )

    await emit_event(
        run_id,
        "s8_persist",
        "run_completed",
        f"Pipeline complete in {total_duration:.1f}s. Awaiting human review.",
        payload={"total_duration": round(total_duration, 2)},
        duration=total_duration
    )

async def generate_pipeline_for_hypothesis(run_id: str, hypothesis_id: str):
    """
    Enables interactive manual problem selection (Human-in-the-Loop):
    Takes the user-selected problem hypothesis from the scored list and regenerates
    Solution Design (S5), Outreach Drafting (S6), and Grounding Verification (S7).
    """
    run = get_run(run_id)
    if not run:
        raise ValueError("Run not found")

    identity_data = run.get("confirmed_company") or {}
    company_name = identity_data.get("name", run["company_input"])
    hints = run.get("hints") or {}

    conn = get_db()
    hyp_row = conn.execute(
        "SELECT * FROM hypotheses WHERE id = ? AND run_id = ?",
        (hypothesis_id, run_id)
    ).fetchone()
    if not hyp_row:
        conn.close()
        raise ValueError(f"Hypothesis {hypothesis_id} not found for run {run_id}")

    h_dict = dict(hyp_row)
    ev_ids = json.loads(h_dict.get("evidence_ids") or "[]")
    scores = json.loads(h_dict.get("scores") or "{}")

    hyp = ProblemHypothesis(
        id=h_dict["id"],
        problem=h_dict["problem"],
        lens=h_dict["lens"],
        lens_explanation=h_dict.get("lens_explanation"),
        layer=h_dict["layer"],
        evidence_ids=ev_ids,
        evidence_strength=scores.get("strength", 0.7),
        business_impact=scores.get("impact", 0.7),
        automatability=scores.get("auto", 0.75),
        timeliness=scores.get("timeliness", 0.6),
        buyer_credibility=scores.get("credibility", 0.7),
        final_score=h_dict.get("final_score", 0.0),
        rank=h_dict.get("rank"),
        rationale=h_dict.get("rationale") or "",
        root_cause=h_dict.get("root_cause"),
        workflow_burden=h_dict.get("workflow_burden"),
        automation_fit=h_dict.get("automation_fit"),
        category_label=h_dict.get("category_label") or "Direct / Stated (Explicit)",
        grounding_status=h_dict.get("grounding_status") or "pending_review",
        grounding_critique=h_dict.get("grounding_critique")
    )

    # Fetch evidence items
    ev_rows = conn.execute("SELECT * FROM evidence WHERE run_id = ?", (run_id,)).fetchall()
    evidence_list = [EvidenceItem(**dict(r)) for r in ev_rows]
    evidence_map = {e.id: e for e in evidence_list}

    # Hook evidence
    hook_ev = None
    for eid in hyp.evidence_ids:
        if eid in evidence_map:
            candidate = evidence_map[eid]
            if not hook_ev or candidate.reliability_tier < hook_ev.reliability_tier:
                hook_ev = candidate
    if not hook_ev and evidence_list:
        hook_ev = evidence_list[0]

    update_run_status(run_id, "drafting", selected_hypothesis_id=hyp.id)
    await emit_event(
        run_id,
        "s4_score",
        "hypothesis_selected",
        f"Active hypothesis switched to #{hyp.rank or 1} [{hyp.layer.upper()} | Score: {hyp.final_score}]: {hyp.problem}",
        payload={
            "selected_hypothesis": hyp.model_dump(),
            "hook_evidence": hook_ev.model_dump() if hook_ev else None
        }
    )

    # Load recipient info for consistent role-fit framing during interactive re-selection
    recip_title = run.get("recipient_title") or hints.get("recipient_title") or hints.get("recipient_role")
    recip_name = run.get("recipient_name") or hints.get("recipient_name")
    role_info = await normalize_recipient_role(recip_title)

    # --- S5: SOLUTION DESIGN ---
    t_s5 = time.time()
    await emit_event(run_id, "s5_solution", "stage_started", f"Designing targeted architecture for: {hyp.problem[:60]}...")
    solution = await design_solution(
        company_name,
        hyp,
        hook_ev,
        recipient_title=role_info.get("title"),
        recipient_lens=role_info.get("lens"),
        seniority=role_info.get("seniority"),
        framing_guidance=role_info.get("framing_guidance")
    )
    s5_dur = time.time() - t_s5

    conn.execute(
        "INSERT OR REPLACE INTO solutions (id, run_id, hypothesis_id, payload, created_time) VALUES (?, ?, ?, ?, ?)",
        (solution.id, run_id, hyp.id, json.dumps(solution.model_dump()), time.time())
    )
    conn.commit()

    await emit_event(
        run_id,
        "s5_solution",
        "stage_completed",
        f"Solution designed: {solution.process_name}",
        payload={"solution": solution.model_dump()},
        duration=s5_dur
    )

    # --- S6: DRAFTING ---
    t_s6 = time.time()
    await emit_event(run_id, "s6_draft", "stage_started", "Drafting evidence-grounded outreach email and LinkedIn note...")
    draft = await generate_draft(
        company_name,
        hyp,
        hook_ev,
        solution,
        recipient_name=recip_name,
        recipient_role=role_info.get("title"),
        recipient_lens=role_info.get("lens"),
        seniority=role_info.get("seniority"),
        framing_guidance=role_info.get("framing_guidance")
    )
    s6_dur = time.time() - t_s6
    await emit_event(
        run_id,
        "s6_draft",
        "stage_completed",
        f"Draft created ({len(draft.body.split())} words) with 1 grounded hook.",
        payload={"draft": draft.model_dump()},
        duration=s6_dur
    )

    # --- S7: GROUNDING CHECK ---
    t_s7 = time.time()
    update_run_status(run_id, "checking")
    await emit_event(run_id, "s7_check", "stage_started", "Running automated Swap-The-Name test and claim verification...")

    verified_draft, quality_report = await verify_grounding(draft, company_name, evidence_list)
    swap_test_unavailable = any(
        "swap test unavailable" in note.lower() or "no valid verdict" in note.lower()
        for note in quality_report.notes
    )
    swap_test_status = "PASSED" if quality_report.passed_swap_test else ("UNAVAILABLE" if swap_test_unavailable else "FAILED")
    s7_dur = time.time() - t_s7

    conn.execute(
        """INSERT OR REPLACE INTO drafts 
           (id, run_id, subject, subject_alternatives, body, linkedin_note, claim_map, why_this_hook, quality_report, version, created_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (verified_draft.id, run_id, verified_draft.subject, json.dumps(verified_draft.subject_alternatives),
         verified_draft.body, verified_draft.linkedin_note, json.dumps(verified_draft.claim_map),
         verified_draft.why_this_hook, json.dumps(quality_report.model_dump()),
         verified_draft.version, time.time())
    )
    conn.commit()
    conn.close()

    await emit_event(
        run_id,
        "s7_check",
        "stage_completed",
        f"Quality checks completed (Verdict: {quality_report.verdict}, Swap Test: {swap_test_status}).",
        payload={"report": quality_report.model_dump(), "draft": verified_draft.model_dump()},
        duration=s7_dur
    )

    update_run_status(run_id, "pending_review", final_draft_id=verified_draft.id)
    await emit_event(
        run_id,
        "s8_persist",
        "run_completed",
        f"Outreach draft updated for selected problem #{hyp.rank or 1}. Awaiting human review.",
        payload={"final_draft_id": verified_draft.id}
    )

async def resume_person_clarification(
    run_id: str,
    selected_person_name: Optional[str] = None,
    selected_company: Optional[str] = None,
    selected_title: Optional[str] = None,
    refinement_text: Optional[str] = None,
    manual_company: Optional[str] = None,
    manual_role: Optional[str] = None,
    none_of_these: bool = False
):
    """
    Resumes a paused Person-First run after SDR clarifies or refines the prospect.
    """
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    hints = run.get("hints") or {}
    start_time = run.get("started_time", time.time())
    person_name = run.get("person_name") or run.get("company_input") or "Prospect"
    profile_data = run.get("person_profile") or {}
    if isinstance(profile_data, str):
        try:
            profile_data = json.loads(profile_data)
        except Exception:
            profile_data = {}
    if isinstance(profile_data, str):
        try:
            profile_data = json.loads(profile_data)
        except Exception:
            profile_data = {}
    alternatives = profile_data.get("alternatives", [])

    # Case 1: SDR entered manual company and role
    if manual_company and manual_role:
        norm = await normalize_person_role(manual_role)
        first_n = person_name.split()[0] if person_name else "there"
        profile = PersonProfile(
            name=person_name,
            first_name=first_n,
            company_raw=manual_company.strip(),
            title_raw=manual_role.strip(),
            title_normalized=norm["title_normalized"],
            function=norm["function"],
            seniority=norm["seniority"],
            evidence_urls=[],
            confidence=1.0,
            role_source="manual",
            role_confidence=1.0
        )
        update_run_status(
            run_id,
            "person_confirmed",
            confidence=1.0,
            person_confidence=1.0,
            person_name=profile.name,
            person_company=profile.company_raw,
            person_title=profile.title_normalized,
            person_function=profile.function,
            person_seniority=profile.seniority,
            role_source="manual",
            person_profile=profile.model_dump()
        )
        await emit_event(
            run_id,
            "s0_person",
            "s0_resolved",
            f"Manually confirmed prospect: {profile.name} — {profile.title_normalized} at {profile.company_raw} (manual entry)",
            payload={"person_profile": profile.model_dump()}
        )
        # Proceed with S1 -> S8
        await _continue_from_s0_to_pipeline(run_id, profile, hints, start_time)
        return

    # Case 2: SDR selected a specific candidate card
    if selected_person_name and selected_company:
        chosen = None
        for alt in alternatives:
            if (alt.get("name", "").lower() == selected_person_name.lower() or
                alt.get("company_raw", "").lower() == selected_company.lower()):
                chosen = alt
                break
        
        c_title = selected_title or (chosen.get("title_raw") if chosen else "Executive")
        norm = await normalize_person_role(c_title)
        first_n = selected_person_name.split()[0] if selected_person_name else "there"
        ev_urls = chosen.get("evidence_urls", []) if chosen else []
        if chosen and chosen.get("source_url") and chosen.get("source_url") not in ev_urls:
            ev_urls.append(chosen.get("source_url"))

        profile = PersonProfile(
            name=selected_person_name,
            first_name=first_n,
            company_raw=selected_company,
            title_raw=c_title,
            title_normalized=norm["title_normalized"],
            function=norm["function"],
            seniority=norm["seniority"],
            evidence_urls=ev_urls,
            confidence=1.0,
            role_source="web",
            role_confidence=1.0,
            alternatives=[PersonCandidate(**a) for a in alternatives] if alternatives else []
        )
        update_run_status(
            run_id,
            "person_confirmed",
            confidence=1.0,
            person_confidence=1.0,
            person_name=profile.name,
            person_company=profile.company_raw,
            person_title=profile.title_normalized,
            person_function=profile.function,
            person_seniority=profile.seniority,
            role_source="web",
            person_profile=profile.model_dump()
        )
        await emit_event(
            run_id,
            "s0_person",
            "s0_resolved",
            f"Prospect confirmed by SDR: {profile.name} — {profile.title_normalized} at {profile.company_raw}",
            payload={"person_profile": profile.model_dump()}
        )
        await _continue_from_s0_to_pipeline(run_id, profile, hints, start_time)
        return

    # Case 3: SDR provided refinement text or clicked none of these
    query = f"{person_name} {refinement_text or ''}".strip()
    await emit_event(
        run_id,
        "s0_person",
        "s0_refinement",
        f"Refining prospect search for: '{query}'...",
        payload={"query": query}
    )
    new_candidates = await discover_person_candidates(person_name, hint_query=refinement_text)
    merged = list(alternatives)
    existing_keys = {(a.get("name", "").lower(), a.get("company_raw", "").lower()) for a in alternatives}
    for c in new_candidates:
        k = (c.name.lower(), c.company_raw.lower())
        if k not in existing_keys:
            existing_keys.add(k)
            merged.append(c.model_dump())

    candidate_objs = [PersonCandidate(**c) if isinstance(c, dict) else c for c in merged]
    scored, best, conf, is_confirmed = score_person_candidates(candidate_objs, person_name, hints={"company_hint": refinement_text})

    if is_confirmed and best:
        first_n = best.first_name or (best.name.split()[0] if best.name else "")
        profile = PersonProfile(
            name=best.name,
            first_name=first_n,
            company_raw=best.company_raw,
            title_raw=best.title_raw,
            title_normalized=best.title_normalized,
            function=best.function,
            seniority=best.seniority,
            location=best.location,
            evidence_urls=best.evidence_urls,
            confidence=conf,
            role_source="web",
            role_confidence=conf,
            alternatives=scored
        )
        update_run_status(
            run_id,
            "person_confirmed",
            confidence=conf,
            person_confidence=conf,
            person_name=profile.name,
            person_company=profile.company_raw,
            person_title=profile.title_normalized,
            person_function=profile.function,
            person_seniority=profile.seniority,
            person_profile=profile.model_dump()
        )
        await emit_event(
            run_id,
            "s0_person",
            "s0_resolved",
            f"Resolved prospect after refinement: {profile.name} — {profile.title_normalized} at {profile.company_raw} (confidence {conf:.2f})",
            payload={"person_profile": profile.model_dump()}
        )
        await _continue_from_s0_to_pipeline(run_id, profile, hints, start_time)
    else:
        # Still ambiguous
        questions = [f"Which company does {person_name} currently work at? (e.g. Ramp, Brex, Alchemy)"]
        update_run_status(
            run_id,
            "awaiting_person_clarification",
            confidence=conf,
            person_confidence=conf,
            person_profile={
                "name": person_name,
                "confidence": conf,
                "alternatives": [c.model_dump() for c in scored],
                "clarification_questions": questions
            }
        )
        await emit_event(
            run_id,
            "s0_person",
            "s0_clarification_needed",
            f"Person confidence {conf:.2f} is still below 0.80 after refinement. Please select a candidate or enter details manually.",
            payload={
                "confidence": conf,
                "person_name": person_name,
                "candidates": [c.model_dump() for c in scored],
                "questions": questions
            }
        )

async def _continue_from_s0_to_pipeline(run_id: str, profile: PersonProfile, hints: Dict[str, Any], start_time: float):
    """Helper to seed S1 with S0 profile and run S1 through S8."""
    run = get_run(run_id) or {}
    mode = run.get("mode") or "fast"
    company_input = profile.company_raw
    hints["recipient_name"] = profile.name
    hints["recipient_title"] = profile.title_normalized
    hints["recipient_role"] = profile.title_normalized
    hints["recipient_lens"] = profile.function
    hints["seniority"] = profile.seniority
    _add_person_context_to_company_resolution(profile, hints)

    t0 = time.time()
    await emit_event(run_id, "s1_resolve", "run_started", f"Starting company verification for '{company_input}'")
    await emit_event(run_id, "s1_resolve", "stage_started", f"Resolving and verifying company identity for '{company_input}'...")
    update_run_status(run_id, "resolving")

    try:
        identity, is_confirmed = await resolve_company(company_input, hints)
        s1_dur = time.time() - t0

        if not is_confirmed:
            update_run_status(
                run_id,
                "awaiting_clarification",
                confidence=identity.confidence,
                confirmed_company=identity.model_dump()
            )
            await emit_event(
                run_id,
                "s1_resolve",
                "clarification_needed",
                f"Confidence {identity.confidence:.2f} is below 0.80. Clarification required.",
                payload={
                    "confidence": identity.confidence,
                    "candidates": [c.model_dump() for c in identity.alternatives],
                    "questions": identity.clarification_questions
                },
                duration=s1_dur
            )
            return

        update_run_status(
            run_id,
            "confirmed",
            confidence=identity.confidence,
            confirmation_method="auto",
            confirmed_company=identity.model_dump()
        )
        await emit_event(
            run_id,
            "s1_resolve",
            "identity_confirmed",
            f"Confirmed identity: {identity.name} ({identity.domain}) with confidence {identity.confidence:.2f}",
            payload={"identity": identity.model_dump()},
            duration=s1_dur
        )
        await run_stages_s2_to_s8(run_id, identity, hints, start_time, person_profile=profile, mode=mode)
    except Exception as e:
        logger.exception(f"Pipeline error continuing from S0 for run {run_id}: {e}")
        update_run_status(run_id, "failed", error_message=str(e))
        await emit_event(run_id, "s1_resolve", "stage_failed", f"Failed to resolve company: {e}")

async def override_prospect(
    run_id: str,
    company_override: Optional[str] = None,
    role_override: Optional[str] = None,
    title_override: Optional[str] = None,
    name_override: Optional[str] = None
):
    """
    Handles editable Resolved Prospect panel in S8:
    - Changing company re-runs from S1.
    - Changing role re-runs from S3 (re-tags and re-scores existing evidence).
    - Changing only name updates the draft in S6/S7.
    """
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    profile_data = run.get("person_profile") or {}
    if isinstance(profile_data, str):
        try:
            profile_data = json.loads(profile_data)
        except Exception:
            profile_data = {}
    name = name_override.strip() if name_override else (run.get("person_name") or profile_data.get("name") or "Prospect")
    old_company = run.get("person_company") or profile_data.get("company_raw") or run.get("company_input") or ""
    new_company = company_override.strip() if company_override else old_company
    raw_role = (title_override or role_override or run.get("person_title") or profile_data.get("title_raw") or "Executive").strip()
    
    norm = await normalize_person_role(raw_role)
    first_n = name.split()[0] if name else "there"

    profile = PersonProfile(
        name=name,
        first_name=first_n,
        company_raw=new_company,
        title_raw=raw_role,
        title_normalized=norm["title_normalized"],
        function=norm["function"],
        seniority=norm["seniority"],
        evidence_urls=profile_data.get("evidence_urls", []),
        confidence=1.0,
        role_source="manual",
        role_confidence=1.0
    )

    update_run_status(
        run_id,
        "person_confirmed",
        person_name=profile.name,
        person_company=profile.company_raw,
        person_title=profile.title_normalized,
        person_function=profile.function,
        person_seniority=profile.seniority,
        role_source="manual",
        person_profile=profile.model_dump()
    )

    await emit_event(
        run_id,
        "s0_person",
        "s0_resolved",
        f"Prospect updated by SDR: {profile.name} — {profile.title_normalized} at {profile.company_raw}",
        payload={"person_profile": profile.model_dump()}
    )

    hints = run.get("hints") or {}
    start_time = run.get("started_time", time.time())

    # Branch 1: Company changed -> Re-run from S1
    if company_override and company_override.lower() != old_company.lower():
        await emit_event(
            run_id,
            "s1_resolve",
            "company_overridden",
            f"Employer changed to '{new_company}'. Re-running company verification and research fan-out...",
            payload={"new_company": new_company}
        )
        await _continue_from_s0_to_pipeline(run_id, profile, hints, start_time)
        return

    # Branch 2: Role changed (company stayed the same) -> Re-run from S3 using cached/persisted evidence
    conn = get_db()
    ev_rows = conn.execute("SELECT * FROM evidence WHERE run_id = ?", (run_id,)).fetchall()
    evidence_list = [EvidenceItem(**dict(r)) for r in ev_rows]
    identity_data = run.get("confirmed_company") or {}
    identity = CompanyIdentity(**identity_data) if identity_data else CompanyIdentity(name=new_company, domain="")

    if role_override or title_override:
        await emit_event(
            run_id,
            "s3_discovery",
            "role_overridden",
            f"Prospect role changed to '{profile.title_normalized}' ({profile.function}). Re-filtering problems and re-scoring...",
            payload={"new_role": profile.model_dump()}
        )
        # Fetch company profile if available
        prof_dict = run.get("company_profile") or {}
        from app.models import CompanyProfile
        company_prof = CompanyProfile(**prof_dict) if prof_dict else None

        # Re-run S3
        hypotheses = await discover_problems(identity, evidence_list, profile=company_prof)
        hypotheses = apply_role_filtered_discovery(hypotheses, profile)

        # Re-run S4
        ranked_hypotheses, winning_hyp, hook_ev, fallback_info = score_and_select_hypothesis(
            hypotheses,
            evidence_list,
            recipient_lens=profile.function,
            person_profile=profile,
            return_fallback_info=True
        )

        for h in ranked_hypotheses:
            conn.execute(
                """INSERT OR REPLACE INTO hypotheses
                   (id, run_id, problem, lens, layer, evidence_ids, scores, final_score, rank, rationale, lens_explanation, root_cause, workflow_burden, automation_fit, category_label, grounding_status, grounding_critique, score_breakdown, base_score, role_fit, role_fit_badge, adjusted_score, owner_function)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (h.id, run_id, h.problem, h.lens, h.layer, json.dumps(h.evidence_ids), json.dumps({
                    "strength": h.evidence_strength, "impact": h.business_impact, "auto": h.automatability,
                    "timeliness": h.timeliness, "credibility": h.buyer_credibility
                }), h.final_score, h.rank, h.rationale, h.lens_explanation, h.root_cause, h.workflow_burden, h.automation_fit,
                getattr(h, "category_label", "Direct / Stated (Explicit)"),
                getattr(h, "grounding_status", "pending_review"),
                getattr(h, "grounding_critique", ""),
                json.dumps(getattr(h, "score_breakdown", {}) or {}),
                getattr(h, "base_score", h.final_score),
                getattr(h, "role_fit", 1.0),
                getattr(h, "role_fit_badge", "broad"),
                getattr(h, "adjusted_score", h.final_score),
                getattr(h, "owner_function", None))
            )
        conn.commit()

        # Re-run S5 Solution
        solution = await design_solution(
            identity.name,
            winning_hyp,
            hook_ev,
            recipient_title=profile.title_normalized,
            recipient_lens=profile.function,
            seniority=profile.seniority
        )
        conn.execute(
            "INSERT OR REPLACE INTO solutions (id, run_id, hypothesis_id, payload, created_time) VALUES (?, ?, ?, ?, ?)",
            (solution.id, run_id, winning_hyp.id, json.dumps(solution.model_dump()), time.time())
        )
        conn.commit()

        # Re-run S6 Draft
        draft = await generate_draft(
            identity.name,
            winning_hyp,
            hook_ev,
            solution,
            recipient_name=profile.name,
            recipient_role=profile.title_normalized,
            recipient_lens=profile.function,
            seniority=profile.seniority
        )

        # Re-run S7 Grounding
        verified_draft, quality_report = await verify_grounding(draft, identity.name, evidence_list)
        conn.execute(
            """INSERT OR REPLACE INTO drafts 
               (id, run_id, subject, subject_alternatives, body, linkedin_note, claim_map, why_this_hook, quality_report, version, created_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (verified_draft.id, run_id, verified_draft.subject, json.dumps(verified_draft.subject_alternatives),
             verified_draft.body, verified_draft.linkedin_note, json.dumps(verified_draft.claim_map),
             verified_draft.why_this_hook, json.dumps(quality_report.model_dump()),
             verified_draft.version, time.time())
        )
        conn.commit()
        conn.close()

        update_run_status(run_id, "pending_review", final_draft_id=verified_draft.id, selected_hypothesis_id=winning_hyp.id)
        await emit_event(
            run_id,
            "s8_persist",
            "run_completed",
            f"Pipeline updated for new prospect role '{profile.title_normalized}'. Awaiting review.",
            payload={"final_draft_id": verified_draft.id}
        )
        return

    # Branch 3: Only name changed -> Re-run S6/S7
    selected_hyp_id = run.get("selected_hypothesis_id")
    hyp_row = conn.execute("SELECT * FROM hypotheses WHERE id = ? AND run_id = ?", (selected_hyp_id, run_id)).fetchone()
    if hyp_row:
        h_dict = dict(hyp_row)
        ev_ids = json.loads(h_dict.get("evidence_ids") or "[]")
        scores = json.loads(h_dict.get("scores") or "{}")
        hyp = ProblemHypothesis(
            id=h_dict["id"], problem=h_dict["problem"], lens=h_dict["lens"], layer=h_dict["layer"],
            evidence_ids=ev_ids, final_score=h_dict.get("final_score", 0.0), rank=h_dict.get("rank"),
            rationale=h_dict.get("rationale") or "", evidence_strength=scores.get("strength", 0.7),
            business_impact=scores.get("impact", 0.7), automatability=scores.get("auto", 0.75),
            timeliness=scores.get("timeliness", 0.6), buyer_credibility=scores.get("credibility", 0.7)
        )
        sol_row = conn.execute("SELECT * FROM solutions WHERE hypothesis_id = ? AND run_id = ?", (hyp.id, run_id)).fetchone()
        sol_dict = json.loads(dict(sol_row)["payload"]) if sol_row else {}
        solution = SolutionSketch(**sol_dict) if sol_dict else None
        hook_ev = evidence_list[0] if evidence_list else None

        if solution:
            draft = await generate_draft(
                identity.name, hyp, hook_ev, solution,
                recipient_name=profile.name,
                recipient_role=profile.title_normalized,
                recipient_lens=profile.function,
                seniority=profile.seniority
            )
            verified_draft, quality_report = await verify_grounding(draft, identity.name, evidence_list)
            conn.execute(
                """INSERT OR REPLACE INTO drafts 
                   (id, run_id, subject, subject_alternatives, body, linkedin_note, claim_map, why_this_hook, quality_report, version, created_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (verified_draft.id, run_id, verified_draft.subject, json.dumps(verified_draft.subject_alternatives),
                 verified_draft.body, verified_draft.linkedin_note, json.dumps(verified_draft.claim_map),
                 verified_draft.why_this_hook, json.dumps(quality_report.model_dump()),
                 verified_draft.version, time.time())
            )
            conn.commit()
            update_run_status(run_id, "pending_review", final_draft_id=verified_draft.id)
            await emit_event(
                run_id,
                "s8_persist",
                "run_completed",
                f"Draft updated with new prospect name '{profile.name}'.",
                payload={"final_draft_id": verified_draft.id}
            )
    conn.close()
