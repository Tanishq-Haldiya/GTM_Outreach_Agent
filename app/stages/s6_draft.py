import uuid
import re
import logging
from typing import Dict, Any, Optional
from app.models import ProblemHypothesis, EvidenceItem, SolutionSketch, OutreachDraft
from app.config import DEFAULT_SELLER_CAPABILITY
from app.llm.router import call_llm
from app.llm.prompts import S6_DRAFT_SYSTEM, S6_DRAFT_USER_TEMPLATE_DIRECT, S6_DRAFT_USER_TEMPLATE_INFERRED
from app.stages.s2_research import _get_clean_company_name

logger = logging.getLogger(__name__)

def _build_observable_signal(hook_evidence: EvidenceItem, hypothesis: ProblemHypothesis) -> str:
    """
    For inferred drafts, extract the observable trigger sentence from the hook evidence
    rather than the full claim. The signal is what we CAN assert as fact.
    Returns the best short phrase we can confidently state.
    """
    # Prefer the evidence excerpt (verbatim quote) as the observable signal
    signal = hook_evidence.excerpt.strip()
    if len(signal) > 200:
        # Truncate to first 200 chars at a sentence boundary
        boundary = max(signal.rfind('. ', 0, 200), signal.rfind(', ', 0, 200))
        signal = signal[: boundary + 1].strip() if boundary > 50 else signal[:200].strip()
    if not signal:
        signal = hook_evidence.claim.strip()
    return signal

async def generate_draft(
    company_name: str,
    hypothesis: ProblemHypothesis,
    hook_evidence: EvidenceItem,
    solution: SolutionSketch,
    seller_capability: Dict[str, Any] = None,
    recipient_name: Optional[str] = None,
    recipient_role: Optional[str] = None,
    recipient_lens: Optional[str] = None,
    seniority: Optional[str] = None,
    framing_guidance: Optional[str] = None
) -> OutreachDraft:
    """
    S6 Drafting Stage:
    Drafts high-converting, evidence-anchored email, LinkedIn note, and SDR why-this-hook explanation.

    Routing:
    - layer == "inferred"         → S6_DRAFT_USER_TEMPLATE_INFERRED (signal-first, consultative)
    - layer == "stated"/"implied" → S6_DRAFT_USER_TEMPLATE_DIRECT   (problem-first, assertive)
    """
    seller = seller_capability or DEFAULT_SELLER_CAPABILITY
    clean_name = _get_clean_company_name(company_name)
    target_persona = recipient_role or "Head of Operations"
    title_display = recipient_role or "leadership"
    lens_display = recipient_lens or hypothesis.lens
    seniority_display = seniority or "director_or_head"
    framing_display = framing_guidance or "Process efficiency and team capacity."

    # Section 4.5 & Section 8: Greeting uses first name if given, otherwise placeholder
    if recipient_name and recipient_name.strip():
        # Address by first name
        first_token = recipient_name.strip().split()[0]
        # Strip honorifics
        if first_token.lower().rstrip('.') in ["mr", "ms", "mrs", "dr", "prof"] and len(recipient_name.strip().split()) > 1:
            first_token = recipient_name.strip().split()[1]
        greeting_name = first_token.capitalize()
        greeting_target = f"Hi {greeting_name},"
    else:
        greeting_name = "there"
        greeting_target = "Hi there,"

    sender_name = seller.get("sender_name", "Tanishq")

    # Determine draft style
    is_inferred = hypothesis.layer == "inferred"
    draft_style = "inferred" if is_inferred else "direct"
    is_person_hook = bool(
        getattr(hook_evidence, "about", "company") == "person" or
        getattr(hook_evidence, "source_type", "") == "sdr_provided"
    )

    # Sanitize expired seasonal phrases from hook evidence so drafting focuses on recurring workflows
    seasonal_patterns = [
        r'\bnew year(?:\'s)?\s*(?:7-day\s*)?(?:streak\s*)?',
        r'\bchristmas\s*(?:promo\s*)?',
        r'\bblack friday\s*(?:sale\s*)?',
        r'\bholiday\s*(?:campaign\s*)?'
    ]
    cleaned_claim = hook_evidence.claim
    cleaned_excerpt = hook_evidence.excerpt
    for pat in seasonal_patterns:
        cleaned_claim = re.sub(pat, "milestone streak ", cleaned_claim, flags=re.IGNORECASE).strip()
        cleaned_excerpt = re.sub(pat, "milestone streak ", cleaned_excerpt, flags=re.IGNORECASE).strip()

    hook_ev_text = f"Claim: '{cleaned_claim}' | Excerpt: '{cleaned_excerpt}' (Source: {hook_evidence.url})"
    solution_text = f"Process: {solution.process_name}. What it does: {solution.what_it_automates}. Impact: {solution.impact_direction}."

    if is_inferred:
        # Build the observable signal separately for the inferred template
        class _CleanedEvidence:
            excerpt = cleaned_excerpt
            claim = cleaned_claim
        observable_signal = _build_observable_signal(_CleanedEvidence(), hypothesis)

        prompt = S6_DRAFT_USER_TEMPLATE_INFERRED.format(
            company_name=clean_name,
            recipient_name=greeting_name,
            recipient_title=title_display,
            recipient_lens=lens_display,
            seniority=seniority_display,
            framing_guidance=framing_display,
            greeting_target=greeting_target,
            target_persona=target_persona,
            problem_statement=hypothesis.problem,
            observable_signal=observable_signal,
            hook_evidence=hook_ev_text,
            solution_sketch=solution_text,
            seller_offering=seller.get("offering", "workflow automation systems for document-heavy back-office operations"),
            seller_value_prop=seller.get("value_prop", "reducing manual bottleneck cycle times"),
            sender_name=sender_name
        )
    else:
        prompt = S6_DRAFT_USER_TEMPLATE_DIRECT.format(
            company_name=clean_name,
            recipient_name=greeting_name,
            recipient_title=title_display,
            recipient_lens=lens_display,
            seniority=seniority_display,
            framing_guidance=framing_display,
            greeting_target=greeting_target,
            target_persona=target_persona,
            problem_statement=hypothesis.problem,
            hook_evidence=hook_ev_text,
            solution_sketch=solution_text,
            seller_offering=seller.get("offering", "workflow automation systems for document-heavy back-office operations"),
            seller_value_prop=seller.get("value_prop", "reducing manual bottleneck cycle times"),
            sender_name=sender_name
        )

    try:
        res = await call_llm(prompt, system_prompt=S6_DRAFT_SYSTEM, task_type="fast", json_mode=True)
        if isinstance(res, dict) and "body" in res:
            # Map claims
            claim_map = res.get("claim_map", {})
            if not claim_map:
                # Do not imply one citation supports the entire email. An empty
                # map is explicit and can be reviewed without false attribution.
                claim_map = {}

            subj = res.get("subject", f"quick question re: {company_name} operations").strip()
            raw_alts = res.get("subject_alternatives", [])
            if not isinstance(raw_alts, list):
                raw_alts = []
            clean_alts = [a.strip() for a in raw_alts if isinstance(a, str) and a.strip() and a.strip().lower() != subj.lower()]

            # De-bias subject line if an expired seasonal tag leaked in
            seasonal_bad = ["new year", "new years", "holiday", "christmas", "black friday"]
            if any(bad in subj.lower() for bad in seasonal_bad):
                # Pick alternative angle without seasonal word if available
                clean_replacement = next((a for a in clean_alts if not any(b in a.lower() for b in seasonal_bad)), None)
                if clean_replacement:
                    clean_alts.append(subj)
                    subj = clean_replacement
                else:
                    subj = re.sub(r'\b(?:re:\s*)?(?:new year(?:\'s)?|holiday|christmas)\s*', '', subj, flags=re.IGNORECASE).strip()
                    if not subj or len(subj.split()) < 2:
                        subj = "streak reward fulfillment"

            body_text = res.get("body", "").strip()

            # De-bias body text if expired seasonal holidays were cited from the raw hook
            for bad_pat, repl in [
                (r'\bthe\s+New\s+Year(?:\'s)?\s*(?:7-day\s*)?(?:streak\s*)?(?:contest\s*)?', 'a milestone streak contest '),
                (r'\bNew\s+Year(?:\'s)?\s*(?:7-day\s*)?(?:streak\s*)?(?:contest\s*)?', 'milestone streak contest '),
                (r'\bNew\s+Year(?:\'s)?\b', 'milestone')
            ]:
                body_text = re.sub(bad_pat, repl, body_text, flags=re.IGNORECASE).strip()

            # Clean out full legal entity name occurrences from conversational body text
            if company_name != clean_name and company_name in body_text:
                body_text = body_text.replace(company_name, clean_name)

            # Prevent double greetings: cleanly strip any leading greeting line (Hi,, Hi [Name],, Dear...)
            body_text = re.sub(r'^(?:hi|hello|hey|dear)\s*(?:\[.*?\]|team|all|[a-zA-Z]+)?\s*[,!:]\s*\n*', '', body_text, flags=re.IGNORECASE).strip()
            body_text = f"Hi {greeting_name},\n\n{body_text}"

            # Prevent duplicate sign-offs: cleanly strip existing signoff before adding standard closing
            body_text = re.sub(r'\n*(?:best|regards|thanks|cheers|sincerely)\s*,\s*\n*.*$', '', body_text, flags=re.IGNORECASE).strip()
            body_text = f"{body_text}\n\nBest,\n{sender_name}"

            recipient_meta = {
                "recipient_name": recipient_name,
                "recipient_title": title_display,
                "recipient_lens": lens_display,
                "seniority": seniority_display
            }

            return OutreachDraft(
                id=f"draft_{uuid.uuid4().hex[:8]}",
                subject=subj,
                subject_alternatives=clean_alts,
                body=body_text,
                linkedin_note=res.get("linkedin_note", f"Hi {greeting_name}, noticed your recent team growth at {clean_name}. Would love to connect!").strip(),
                why_this_hook=res.get("why_this_hook", f"Grounded in verified signal: {hook_evidence.claim}").strip(),
                selected_hook_id=hook_evidence.id,
                claim_map=claim_map,
                version=1,
                draft_style=draft_style,
                recipient_fields_used=recipient_meta,
                person_hook_cited=is_person_hook
            )
    except Exception as e:
        logger.warning(f"S6 draft generation error: {e}")

    # Fallback template — style-aware
    recipient_meta = {
        "recipient_name": recipient_name,
        "recipient_title": title_display,
        "recipient_lens": lens_display,
        "seniority": seniority_display
    }
    if is_inferred:
        fallback_body = (
            f"Hi {greeting_name},\n\n"
            f"Saw that {clean_name} recently noted: \"{hook_evidence.excerpt[:90]}...\"\n\n"
            f"As volume at that scale grows, {hypothesis.problem.lower()} can quietly become a bottleneck — "
            f"wondering if that's something your team is navigating.\n\n"
            f"We build automated workflow systems that ingest raw incoming items, "
            f"reconcile exceptions against policy, and update systems with human-in-the-loop checkpoints. "
            f"Worth a quick chat to explore if it's relevant?\n\n"
            f"Best,\n{sender_name}"
        )
    else:
        fallback_body = (
            f"Hi {greeting_name},\n\n"
            f"Saw that {clean_name} recently noted: \"{hook_evidence.excerpt[:90]}...\"\n\n"
            f"With that, teams often face scaling bottlenecks around {hypothesis.problem.lower()}. "
            f"We build automated workflow systems that ingest raw incoming items, "
            f"reconcile exceptions against policy, and update systems with human-in-the-loop checkpoints.\n\n"
            f"Open to comparing notes on how peer teams handle this?\n\n"
            f"Best,\n{sender_name}"
        )

    return OutreachDraft(
        id=f"draft_{uuid.uuid4().hex[:8]}",
        subject=f"{clean_name.lower()} operations / {hypothesis.lens.replace('_', ' ')}",
        body=fallback_body,
        linkedin_note=f"Hi {greeting_name}, following {clean_name}'s recent operational milestones. Would love to connect and share notes on workflow automation.",
        why_this_hook=f"Triggered by {hook_evidence.title}: '{hook_evidence.claim}'",
        selected_hook_id=hook_evidence.id,
        claim_map={},
        version=1,
        draft_style=draft_style,
        recipient_fields_used=recipient_meta,
        person_hook_cited=is_person_hook
    )
