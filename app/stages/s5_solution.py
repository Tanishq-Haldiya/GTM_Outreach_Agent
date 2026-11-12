import uuid
import logging
from typing import Dict, Any
from app.models import ProblemHypothesis, EvidenceItem, SolutionSketch
from app.config import DEFAULT_SELLER_CAPABILITY
from app.llm.router import call_llm
from app.llm.prompts import S5_SOLUTION_SYSTEM, S5_SOLUTION_USER_TEMPLATE

logger = logging.getLogger(__name__)

async def design_solution(
    company_name: str,
    hypothesis: ProblemHypothesis,
    hook_evidence: EvidenceItem,
    seller_capability: Dict[str, Any] = None,
    recipient_title: str = None,
    recipient_lens: str = None,
    seniority: str = None,
    framing_guidance: str = None
) -> SolutionSketch:
    """
    S5 Solution Design:
    Designs a targeted AI/automation workflow architecture for the winning problem.
    """
    seller = seller_capability or DEFAULT_SELLER_CAPABILITY

    title_val = recipient_title or "Operations Lead"
    lens_val = recipient_lens or hypothesis.lens
    seniority_val = seniority or "director_or_head"
    framing_val = framing_guidance or "Process efficiency and team capacity."

    prompt = S5_SOLUTION_USER_TEMPLATE.format(
        company_name=company_name,
        problem_statement=hypothesis.problem,
        lens=hypothesis.lens,
        layer=hypothesis.layer,
        hook_evidence=f"[{hook_evidence.title}] {hook_evidence.claim} (Excerpt: '{hook_evidence.excerpt}')" if hook_evidence else "General operational friction",
        recipient_title=title_val,
        recipient_lens=lens_val,
        seniority=seniority_val,
        framing_guidance=framing_val,
        seller_offering=seller.get("offering", "workflow automation systems for document-heavy back-office operations"),
        seller_value_prop=seller.get("value_prop", "reducing manual bottleneck cycle times")
    )

    try:
        res = await call_llm(prompt, system_prompt=S5_SOLUTION_SYSTEM, task_type="fast", json_mode=True)
        if isinstance(res, dict):
            solution = SolutionSketch(
                id=f"sol_{uuid.uuid4().hex[:8]}",
                hypothesis_id=hypothesis.id,
                process_name=res.get("process_name", "Automated Operational Workflow"),
                what_it_automates=res.get("what_it_automates", hypothesis.problem),
                input_consumed=res.get("input_consumed", "Transaction requests, emails, and document feeds"),
                key_steps=res.get("key_steps", ["Ingestion & OCR", "LLM Extraction", "Policy Check", "ERP Update"]),
                human_checkpoints=res.get("human_checkpoints", ["Confidence score below 0.90", "Exception escalations"]),
                systems_touched=res.get("systems_touched", ["ERP", "Internal DB", "Email / Inbox"]),
                impact_direction=res.get("impact_direction", "Eliminates multi-day processing queues to under 2 minutes"),
                buyer_credibility_hook=res.get("buyer_credibility_hook", "Targets proven manual friction points")
            )
            return solution
    except Exception as e:
        logger.warning(f"S5 solution design error: {e}")

    # Generic fallback stays anchored to the selected problem when providers fail.
    process_label = (hypothesis.lens or "operational").replace("_", " ").strip().title()
    problem = hypothesis.problem.rstrip(" .")
    return SolutionSketch(
        id=f"sol_{uuid.uuid4().hex[:8]}",
        hypothesis_id=hypothesis.id,
        process_name=f"{process_label} exception workflow",
        what_it_automates=f"A structured workflow for handling {problem}, checking cases against the relevant criteria, and preparing clear next steps for review.",
        input_consumed=f"Case details and supporting information relevant to: {problem}",
        key_steps=[
            "Capture the case details described in the selected problem",
            "Check the available information against the applicable criteria and flag exceptions",
            "Route uncertain cases for human review with a clear next step",
        ],
        human_checkpoints=["Unclear or incomplete information", "Cases requiring policy or business judgment"],
        systems_touched=["Existing intake channel", "Case management system", "Relevant source of record"],
        impact_direction="More consistent handling of the selected workflow while keeping decisions with the team",
        buyer_credibility_hook=f"Designed around the selected problem: {problem}"
    )
