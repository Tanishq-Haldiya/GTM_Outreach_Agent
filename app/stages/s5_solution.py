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
            return SolutionSketch(
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
    except Exception as e:
        logger.warning(f"S5 solution design error: {e}")

    # Fallback
    return SolutionSketch(
        id=f"sol_{uuid.uuid4().hex[:8]}",
        hypothesis_id=hypothesis.id,
        process_name="Intelligent Document & Ops Orchestration",
        what_it_automates=f"Manual exception handling and verification for {hypothesis.lens}",
        input_consumed="Inbound requests, PDFs, and discrepancy queues",
        key_steps=["Multi-format ingestion", "Entity extraction & policy reconciliation", "ERP sync"],
        human_checkpoints=["Low-confidence validation", "Out-of-policy approval"],
        systems_touched=["Core ERP", "Document Management", "Notification Bus"],
        impact_direction="Compresses operational cycle time from days to minutes",
        buyer_credibility_hook="Directly resolves document-heavy manual review overhead"
    )
