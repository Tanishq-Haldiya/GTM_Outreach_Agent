import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import pytest
from app.models import ProblemHypothesis, EvidenceItem, SolutionSketch
from app.stages.s6_draft import generate_draft
from app.stages.s7_check import verify_grounding

@pytest.mark.anyio
async def test_zamp_pitch():
    company = "Zamp"
    ev = EvidenceItem(
        id="ev_zamp_1",
        researcher="profile",
        source_type="website",
        url="https://zamp.com",
        title="Zamp Managed Sales Tax Platform",
        claim="Zamp provides managed sales tax compliance and automated calculations with hands-on support.",
        excerpt="Zamp eliminates sales tax complexity with fully managed filings and real-time calculations.",
        signal_type="manual_process",
        reliability_tier="A"
    )
    hyp = ProblemHypothesis(
        id="hyp_1",
        problem="High-touch managed tax filing workflows scale linearly with merchant onboarding volume.",
        lens="finance_ops",
        layer="implied",
        evidence_ids=["ev_zamp_1"]
    )
    sol = SolutionSketch(
        id="sol_1",
        hypothesis_id="hyp_1",
        process_name="Automated Exception Reconciliation Engine",
        what_it_automates="Multi-state discrepancy reconciliation for high-volume filings",
        input_consumed="Inbound merchant transaction logs and jurisdiction rules",
        key_steps=["Data normalization", "Tax calculation audit", "Exception queuing"],
        human_checkpoints=["Low-confidence edge cases"],
        systems_touched=["State Filing Portals", "Merchant DB"],
        impact_direction="Compresses filing review time by 80%",
        buyer_credibility_hook="Resolves jurisdiction-specific discrepancy volume"
    )

    print("Generating draft for Zamp...")
    draft = await generate_draft(company, hyp, ev, sol, recipient_role="Head of Operations")
    print(f"\n--- DRAFT GENERATED ({len(draft.body.split())} words) ---")
    print("Subject:", draft.subject)
    print("Body:\n", draft.body)

    print("\nRunning S7 Grounding & QA Check...")
    verified, report = await verify_grounding(draft, company, [ev])
    print("Verdict:", report.verdict)
    print("Passed Swap Test:", report.passed_swap_test)
    print("Quality Notes:", report.notes)
    print("\nFinal Verified Body:\n", verified.body)

    # Verify that the draft does NOT start with critique text
    assert not verified.body.startswith("The email is fundamentally flawed")
    assert "Zamp" in verified.body

if __name__ == "__main__":
    asyncio.run(test_zamp_pitch())
