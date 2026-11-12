import re
import json
import logging
from typing import List, Tuple
from app.models import OutreachDraft, EvidenceItem, QualityReport
from app.llm.router import call_llm
from app.llm.prompts import S7_CHECK_SYSTEM, S7_CHECK_USER_TEMPLATE

logger = logging.getLogger(__name__)

BANNED_PHRASES = [
    "i hope this email finds you well",
    "game changer",
    "game-changer",
    "revolutionary",
    "disruptive",
    "streamline your operations",
    "synergies",
    "touching base",
    "circling back",
    "reach out to you"
]

def check_swap_the_role(body: str, recipient_function: str = None) -> Tuple[bool, str]:
    """
    Swap-the-role check (Section 8): could this draft go to someone in a completely different function unchanged?
    Verifies that domain-specific terminology is present and not egregiously mismatched with recipient function.
    """
    body_lower = body.lower()
    role_domain_terms = [
        "support", "queue", "ticket", "invoic", "billing", "reconciliation",
        "dispatch", "logistics", "fulfillment", "supply chain", "compliance",
        "kyc", "aml", "contract", "recruiting", "hiring", "lead", "revops",
        "incident", "integration", "margin", "scale", "capacity", "operations",
        "csat", "sla", "backlog", "triage", "refund", "dispute"
    ]
    if not any(t in body_lower for t in role_domain_terms):
        return False, "Swap-the-role alert: copy lacks domain-specific operational references and could be sent to any role."

    # If recipient function is specified, verify no complete departmental clash
    if recipient_function == "Customer Support/CX":
        support_terms = ["support", "ticket", "queue", "cx", "csat", "refund", "dispute", "triage", "sla", "customer"]
        fin_terms = ["accounts payable", "ledger", "invoice reconciliation", "3-way matching", "general ledger"]
        has_support = any(st in body_lower for st in support_terms)
        has_fin_only = any(ft in body_lower for ft in fin_terms) and not has_support
        if has_fin_only:
            return False, "Swap-the-role failed: copy targeted to Customer Support contains only finance/AP ledger concepts without support context."

    return True, "Passed swap-the-role test"

def _run_deterministic_checks(
    body: str,
    company_name: str,
    evidence_list: List[EvidenceItem]
) -> Tuple[List[str], List[str], bool]:
    """
    Executes programmatic deterministic sanity checks:
    1. Company Name Token Check
    2. Word Count Bounds
    3. Banned Generic Sales Cliches
    4. Numeric Verification against cited evidence (Prevents invented metrics)
    5. Person-Level Claim Grounding (Section 5.5):
       - Claims about the person must cite sdr_provided evidence.
       - Exact-text check for quoted phrases.
       - Person claims cannot be supported by company-only evidence.
    """
    words = body.split()
    word_count = len(words)
    unsupported = []
    notes = []
    invented_numbers = False

    # 1. Company Name Token Check
    clean_name = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', company_name)
    tokens = [tok.lower() for tok in re.findall(r'\b\w{3,}\b', clean_name)]
    if not any(tok in body.lower() for tok in tokens):
        notes.append(f"Company name '{company_name}' not explicitly mentioned in body")

    # 2. Word Count Check
    if word_count < 90 or word_count > 130:
        notes.append(f"Draft is outside the 90-130 word target ({word_count} words)")

    # 3. Banned phrases check
    body_lower = body.lower()
    for phrase in BANNED_PHRASES:
        if phrase in body_lower:
            notes.append(f"Contains generic cliches: '{phrase}'")

    # 4. Number Verification (Prevent invented stats)
    numbers_in_body = set(re.findall(r'\b\d+(?:\.\d+)?%?\b', body))
    all_evidence_text = " ".join([f"{e.claim} {e.excerpt}" for e in evidence_list])
    for num in numbers_in_body:
        # Allow small harmless numbers like 5 (as in 5-minute), 1, 2
        if num in ["5", "1", "2"]:
            continue
        if num not in all_evidence_text:
            invented_numbers = True
            unsupported.append(f"Uncited numeric claim detected: '{num}'")

    # 5. Person-Level Claim Grounding (Section 5.5 & Section 8)
    person_markers = [
        "your post", "your recent post", "you wrote", "you mentioned",
        "in your talk", "in your podcast", "in your bio", "your interview",
        "loved your", "congrats on your", "saw your talk", "noticed your keynote"
    ]
    person_sdr_items = [
        e for e in evidence_list
        if getattr(e, "source_type", "") in ["sdr_provided", "person_voice"] or getattr(e, "about", "") == "person"
    ]
    has_person_markers = any(m in body_lower for m in person_markers)
    if has_person_markers and not person_sdr_items:
        unsupported.append("Claim about recipient made without sender-provided evidence (Section 5.5 violation)")

    # 6. Double Greeting Check (Section 8)
    greeting_matches = re.findall(r'\b(?:hi|hello|hey|dear)\s+[a-zA-Z]+[,!:]', body, re.IGNORECASE)
    if len(greeting_matches) > 1:
        notes.append(f"Double greeting detected: {greeting_matches}")

    # 7. Exact-text check for any verbatim quotes in the body
    quotes_in_body = re.findall(r'["\']([^"\']{15,})["\']', body)
    for q in quotes_in_body:
        q_clean = q.strip().lower()
        if not any(q_clean in (e.excerpt or "").lower() or q_clean in (e.claim or "").lower() for e in evidence_list):
            unsupported.append(f"Quoted text '{q[:40]}...' does not match any cited evidence excerpt verbatim")

    # 8. Swap-the-role check (Section 8: could this draft go to someone in a different function unchanged?)
    passed_role, role_note = check_swap_the_role(body)
    if not passed_role:
        notes.append(role_note)

    return unsupported, notes, invented_numbers

async def verify_grounding(
    draft: OutreachDraft,
    company_name: str,
    evidence_list: List[EvidenceItem]
) -> Tuple[OutreachDraft, QualityReport]:
    """
    S7 Grounding Check & Swap-The-Name Test:
    Executes programmatic validation followed by an LLM adversarial swap-test.
    Performs 1 repair pass if needed, and re-validates the repair deterministically (Finding #9).
    """
    evidence_map = {e.id: e for e in evidence_list}

    # Run initial deterministic checks
    unsupported, notes, invented_numbers = _run_deterministic_checks(draft.body, company_name, evidence_list)

    # LLM Swap-The-Name Test
    passed_swap_test = False
    llm_check_completed = False
    ev_summary = [
        {"id": e.id, "claim": e.claim, "excerpt": e.excerpt}
        for e in evidence_list[:4]
    ]
    prompt = S7_CHECK_USER_TEMPLATE.format(
        company_name=company_name,
        subject=draft.subject,
        body=draft.body,
        evidence_json=json.dumps(ev_summary)
    )

    try:
        check_res = await call_llm(prompt, system_prompt=S7_CHECK_SYSTEM, task_type="fast", json_mode=True)
        if isinstance(check_res, dict) and isinstance(check_res.get("passed_swap_test"), bool):
            llm_check_completed = True
            passed_swap_test = check_res["passed_swap_test"]
            if not passed_swap_test:
                notes.append(f"Failed swap-test: {check_res.get('swap_test_notes', 'Draft is too generic')}")
            
            # Check if repair is recommended
            repair_sugg = check_res.get("repair_suggestion", "").strip()
            # Only adopt repair if it is genuinely a rewritten email body, NOT editorial commentary/critique
            critique_markers = [
                "the email is", "fundamentally flawed", "criticizing the", "poor sales strategy", 
                "signature must be", "the sender cannot", "persona and logic", "editorial note",
                "intent was", "critique:", "poor strategy"
            ]
            has_greeting = any(repair_sugg.lower().startswith(g) for g in ["hi ", "hello ", "hey ", "dear "])
            has_signoff = any(s in repair_sugg.lower() for s in ["best,", "regards,", "cheers,", "thanks,", "sincerely,"])
            contains_critique = any(phrase in repair_sugg.lower() for phrase in critique_markers)
            
            is_valid_email_repair = (
                repair_sugg and len(repair_sugg) > 50 and
                has_greeting and has_signoff and
                not contains_critique
            )
            if is_valid_email_repair:
                # Deterministic re-verification of the repair output (Finding #9)
                rep_unsupported, rep_notes, rep_invented = _run_deterministic_checks(repair_sugg, company_name, evidence_list)
                if rep_invented or rep_unsupported or any("generic cliches" in n for n in rep_notes):
                    # Repair introduced defects! Reject repair, preserve original draft, and flag
                    logger.warning(f"S7 repair rejected due to defects: {rep_unsupported} | {rep_notes}")
                    notes.append("Automated repair rejected: introduced uncited claims or cliches; original draft preserved")
                else:
                    draft.body = repair_sugg
                    draft.quality_verdict = "pass_with_repair"
                    passed_swap_test = True  # Repaired draft resolved the swap test issue
                    notes.append("Applied automated repair (verified against grounding & style constraints)")
            elif repair_sugg:
                # Store the model's critique in QA notes for SDR visibility; never overwrite the draft with critique
                notes.append(f"QA Advisory: {repair_sugg[:200]}")
        else:
            notes.append("Automated swap test returned no valid verdict; human review is required.")
    except Exception as e:
        logger.warning(f"S7 LLM check warning: {e}")
        notes.append("Automated swap test unavailable; human review is required before outreach.")

    # Determine final verdict
    verdict = "pass"
    word_count = len(draft.body.split())
    if unsupported or invented_numbers:
        verdict = "flagged"
    elif not 90 <= word_count <= 130:
        verdict = "review_recommended"
    elif not llm_check_completed or not passed_swap_test or len(notes) > 1:
        verdict = "pass_with_repair" if draft.quality_verdict == "pass_with_repair" else "review_recommended"

    report = QualityReport(
        passed_swap_test=passed_swap_test,
        unsupported_claims=unsupported,
        word_count=word_count,
        invented_numbers_detected=invented_numbers,
        verdict=verdict,
        repaired=(draft.quality_verdict == "pass_with_repair"),
        notes=notes
    )

    draft.quality_verdict = verdict
    draft.quality_notes = notes

    return draft, report
