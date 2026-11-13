import uuid
import re
import logging
from typing import Dict, Any, Optional
from app.models import ProblemHypothesis, EvidenceItem, SolutionSketch, OutreachDraft
from app.config import DEFAULT_SELLER_CAPABILITY
from app.llm.router import call_llm
from app.llm.prompts import (
    S6_DRAFT_SYSTEM,
    S6_DRAFT_USER_TEMPLATE_DIRECT,
    S6_DRAFT_USER_TEMPLATE_INFERRED,
    S6_DRAFT_USER_TEMPLATE_REVIEW,
)
from app.stages.s2_research import _get_clean_company_name
from app.stages.topic_alignment import matches_problem_topic

logger = logging.getLogger(__name__)


def _is_raw_metric_dump(text: str) -> bool:
    """Identify scraped headcount/trajectory series that should not be quoted."""
    numeric_values = re.findall(r"(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?%?", text or "")
    periods = re.findall(r"\b(?:yearly|annually|quarterly|monthly|weekly)\b", text or "", flags=re.IGNORECASE)
    has_tracker_format = bool(re.search(r"\bnow\s*:\s*|[;|•·]", text or "", flags=re.IGNORECASE))
    return len(numeric_values) >= 3 and len(periods) >= 2 and has_tracker_format


def _naturalize_evidence_text(claim: str, excerpt: str) -> tuple[str, str]:
    if _is_raw_metric_dump(claim) or _is_raw_metric_dump(excerpt):
        summary = "Public workforce data indicates recent team growth."
        return summary, summary
    return claim, excerpt


def _sanitize_raw_metric_copy(text: str, evidence: EvidenceItem) -> str:
    if not (_is_raw_metric_dump(evidence.claim) or _is_raw_metric_dump(evidence.excerpt)):
        return text
    text = re.sub(
        r'["“]?\s*Now:\s*[\d,]+[^"”\n]{0,320}["”]?',
        "recent team growth",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'["“][^"”\n]{0,320}(?:yearly|annually)[^"”\n]{0,320}(?:quarterly|monthly)[^"”\n]{0,160}["”]',
        "recent team growth",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _fallback_subject(lens: str) -> str:
    subjects = {
        "hr_ops": "Scaling hiring workflows",
        "operations": "Scaling operations",
        "finance_ops": "Scaling finance operations",
        "compliance_kyc": "Compliance review workflow",
        "customer_support": "Support workflow capacity",
        "supply_chain_logistics": "Scaling supply operations",
        "sales_ops": "Scaling sales operations",
    }
    return subjects.get((lens or "").lower(), "Scaling team workflows")

def _build_observable_signal(hook_evidence: EvidenceItem, hypothesis: ProblemHypothesis) -> str:
    """
    For inferred drafts, use a concise, natural-language signal rather than a raw excerpt.
    """
    # The evidence has already been naturalized before it reaches this helper.
    signal = hook_evidence.excerpt.strip()
    if len(signal) > 200:
        # Truncate to first 200 chars at a sentence boundary
        boundary = max(signal.rfind('. ', 0, 200), signal.rfind(', ', 0, 200))
        signal = signal[: boundary + 1].strip() if boundary > 50 else signal[:200].strip()
    if not signal:
        signal = hook_evidence.claim.strip()
    return signal


def _is_usable_problem_statement(
    problem: str,
    hypothesis: Optional[ProblemHypothesis] = None,
) -> bool:
    text = (problem or "").strip().casefold()
    if len(text) < 18 or len(text) > 200:
        return False
    headline_markers = (
        "headline:", "panel", "forum", "keynote", "webinar", "conference",
        "announces", "finding meaningful connections", "linkedin:", "current role:",
    )
    if any(marker in text for marker in headline_markers):
        return False
    operational_terms = (
        "manual", "backlog", "queue", "delay", "delayed", "bottleneck", "workflow",
        "onboarding", "hiring", "recruit", "support", "ticket", "refund", "billing",
        "reconcil", "verification", "compliance", "review", "exception", "handoff",
        "document", "process", "capacity", "restriction", "rejection", "error",
        "outage", "incident", "transaction", "candidate", "coordination", "fulfillment",
        "friction", "frustration", "configuration", "parameter", "setup", "interface",
        "issue", "bug", "crash", "failure", "fail", "broken", "dispute", "complaint",
        "disconnect", "inefficiency", "barrier", "workaround", "tedious", "stuck",
        "drop-off", "slow", "sync", "mismatch", "dropout", "dropouts", "triage",
        "escalation", "churn", "retention", "disruption", "unresponsive", "overload", "strain",
    )
    if any(term in text for term in operational_terms):
        return True

    # If the problem statement text itself used concise phrasing, also check
    # associated operational fields on the hypothesis (root cause, workflow burden)
    if hypothesis:
        aux_text = f"{getattr(hypothesis, 'root_cause', '') or ''} {getattr(hypothesis, 'workflow_burden', '') or ''} {getattr(hypothesis, 'automation_fit', '') or ''}".casefold()
        if any(term in aux_text for term in operational_terms):
            return True

    return False


def _build_review_fallback(
    company_name: str,
    greeting_name: str,
    sender_name: str,
    hypothesis: ProblemHypothesis,
    hook_evidence: EvidenceItem,
    recipient_meta: Dict[str, Any],
    is_problem_usable: bool,
) -> OutreachDraft:
    """Keep provider-failure drafts cautious and never turn raw titles into a pain claim."""
    if is_problem_usable:
        body = (
            f"Hi {greeting_name},\n\n"
            f"A public report about {company_name} mentioned {hypothesis.problem.rstrip(' .')}. I may be missing context, so I don't want to assume it reflects your team's current process. Is this still relevant to the work you oversee?\n\n"
            f"We build workflow automation for document-heavy operations, with people reviewing exceptions. If this is an area you're exploring, would it be useful to compare notes?\n\n"
            f"Best,\n{sender_name}"
        )
        subject = _fallback_subject(hypothesis.lens)
        note = "This problem is still awaiting grounding review. The fallback keeps it tentative; verify the source and current relevance before use."
    else:
        body = (
            f"Hi {greeting_name},\n\n"
            "The available public material does not establish a specific operational problem, so I don't want to assume one or prescribe a workflow. If improving a manual or exception-heavy process is a current priority, would you be open to comparing notes?\n\n"
            "We build workflow automation for document-heavy operations and keep people involved in exceptions. If that is relevant to your work, I would be glad to share how teams decide where automation fits.\n\n"
            f"Best,\n{sender_name}"
        )
        subject = "A workflow question"
        note = "Draft held to a neutral, exploratory angle: the cited evidence does not establish an operational problem. Confirm target identity and evidence before use."

    return OutreachDraft(
        id=f"draft_{uuid.uuid4().hex[:8]}",
        subject=subject,
        body=body,
        linkedin_note=f"Hi {greeting_name}, I'd be glad to connect and compare notes on workflow automation with human review, if that's relevant to your work.",
        why_this_hook=note,
        selected_hook_id=hook_evidence.id,
        claim_map={},
        version=1,
        draft_style="review",
        recipient_fields_used=recipient_meta,
        person_hook_cited=False,
    )

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
    has_role_fallback = bool(
        hypothesis.fallback_info is True
        or (
            isinstance(getattr(hypothesis, "fallback_info", None), dict)
            and hypothesis.fallback_info.get("fallback_banner_used")
        )
    )
    is_provisional = (hypothesis.grounding_status == "provisional") or has_role_fallback
    usable_problem = _is_usable_problem_statement(hypothesis.problem, hypothesis)
    draft_style = "review" if (is_provisional or not usable_problem) else ("inferred" if is_inferred else "direct")
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

    cleaned_claim, cleaned_excerpt = _naturalize_evidence_text(cleaned_claim, cleaned_excerpt)

    hook_ev_text = f"Claim: '{cleaned_claim}' | Excerpt: '{cleaned_excerpt}' (Source: {hook_evidence.url})"
    solution_text = f"Process: {solution.process_name}. What it does: {solution.what_it_automates}. Impact: {solution.impact_direction}."

    recipient_meta = {
        "recipient_name": recipient_name,
        "recipient_title": title_display,
        "recipient_lens": lens_display,
        "seniority": seniority_display
    }

    # A malformed or non-operational candidate should never be rewritten into
    # confident outreach. Preserve the run for review with a neutral fallback.
    if is_provisional and not usable_problem:
        return _build_review_fallback(
            clean_name, greeting_name, sender_name, hypothesis, hook_evidence, recipient_meta, False
        )

    if is_provisional:
        prompt = S6_DRAFT_USER_TEMPLATE_REVIEW.format(
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
    elif is_inferred:
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
            clean_alts = [
                a.strip() for a in raw_alts
                if isinstance(a, str)
                and a.strip()
                and a.strip().lower() != subj.lower()
                and matches_problem_topic(hypothesis.problem, a)
            ]

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

            # Smooth out condescending or robotic 'as a leader' phrases if generated
            body_text = re.sub(r'\b[Aa]s a leader\s+(?:in\s+[^,]+|overseeing\s+[^,]+)?,?\s*', '', body_text).strip()
            body_text = re.sub(r'\b[Aa]s someone leading\s+[^,]+,?\s*', '', body_text).strip()
            body_text = re.sub(r'\b[Aa]s a leadership team,?\s*', '', body_text).strip()

            body_text = _sanitize_raw_metric_copy(body_text, hook_evidence)

            linkedin_text = _sanitize_raw_metric_copy(
                res.get("linkedin_note") or "", hook_evidence
            ).strip()
            if not matches_problem_topic(hypothesis.problem, body_text):
                logger.warning("S6 copy drifted from the selected problem; using a problem-matched fallback.")
                raise ValueError("Draft did not retain enough topic terms from the selected problem")

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

            linkedin_note = linkedin_text or _sanitize_raw_metric_copy(res.get("linkedin_note", f"Hi {greeting_name}, noticed your recent team growth at {clean_name}. Would love to connect!"), hook_evidence).strip()
            why_this_hook = _sanitize_raw_metric_copy(res.get("why_this_hook", f"Grounded in verified signal: {cleaned_claim}"), hook_evidence).strip()

            return OutreachDraft(
                id=f"draft_{uuid.uuid4().hex[:8]}",
                subject=subj,
                subject_alternatives=clean_alts,
                body=body_text,
                linkedin_note=linkedin_note,
                why_this_hook=why_this_hook,
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
    if is_provisional:
        return _build_review_fallback(
            clean_name, greeting_name, sender_name, hypothesis, hook_evidence, recipient_meta, usable_problem
        )

    if is_inferred:
        fallback_signal = observable_signal.strip().rstrip(". ")
        if len(fallback_signal) > 140:
            fallback_signal = fallback_signal[:137].rsplit(" ", 1)[0] + "..."
        fallback_body = (
            f"Hi {greeting_name},\n\n"
            f"I noticed a recent signal at {clean_name}: {fallback_signal}.\n\n"
            f"As those operations scale, {hypothesis.problem.lower()} may become harder to manage. "
            f"Is that an area your team is exploring?\n\n"
            "We help teams automate document-heavy workflows while keeping people involved in exceptions. "
            "Is that worth comparing notes on?\n\n"
            f"Best,\n{sender_name}"
        )
    else:
        problem_text = hypothesis.problem.rstrip(" .")
        fallback_body = (
            f"Hi {greeting_name},\n\n"
            f"I came across public reporting related to {problem_text.lower()} and wanted to ask how your team approaches this area today.\n\n"
            "We help automate document-heavy workflows while keeping people involved in exceptions. Would a brief exchange be useful?\n\n"
            f"Best,\n{sender_name}"
        )

    return OutreachDraft(
        id=f"draft_{uuid.uuid4().hex[:8]}",
        subject=_fallback_subject(hypothesis.lens),
        body=fallback_body,
        linkedin_note=f"Hi {greeting_name}, I came across a signal related to {hypothesis.problem.rstrip(' .').lower()}. Would be glad to connect and compare notes on how teams handle it.",
        why_this_hook=f"Triggered by {hook_evidence.title}: {cleaned_claim}",
        selected_hook_id=hook_evidence.id,
        claim_map={},
        version=1,
        draft_style=draft_style,
        recipient_fields_used=recipient_meta,
        person_hook_cited=is_person_hook
    )
