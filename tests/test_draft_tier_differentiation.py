"""
Tests for S6 tier-differentiated drafting.
Verifies that:
  - layer="inferred" routes to S6_DRAFT_USER_TEMPLATE_INFERRED (contains observable_signal token)
  - layer="stated" routes to S6_DRAFT_USER_TEMPLATE_DIRECT (no observable_signal token)
  - draft_style field is set correctly on the returned OutreachDraft
  - Both templates render without KeyError when formatted
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.llm.prompts import S6_DRAFT_USER_TEMPLATE_DIRECT, S6_DRAFT_USER_TEMPLATE_INFERRED, S6_DRAFT_USER_TEMPLATE
from app.models import ProblemHypothesis, EvidenceItem, SolutionSketch

# --- Template structure tests (synchronous) ---

def test_direct_template_has_no_observable_signal_token():
    """Direct template must NOT contain {observable_signal} — it doesn't need a signal bridge."""
    assert "{observable_signal}" not in S6_DRAFT_USER_TEMPLATE_DIRECT

def test_inferred_template_has_observable_signal_token():
    """Inferred template MUST contain {observable_signal} as a named format token."""
    assert "{observable_signal}" in S6_DRAFT_USER_TEMPLATE_INFERRED

def test_direct_template_format_no_keyerror():
    """Direct template must format cleanly with the standard set of vars (no missing keys)."""
    rendered = S6_DRAFT_USER_TEMPLATE_DIRECT.format(
        company_name="TestCo",
        target_persona="VP Operations",
        problem_statement="Manual invoice reconciliation creates 3-day payment delays.",
        hook_evidence="Claim: 'Invoices processed manually' | Excerpt: '...' (Source: https://testco.com)",
        solution_sketch="Process: Invoice Automation. What it does: AI extracts fields. Impact: 70% faster.",
        seller_offering="document workflow automation",
        seller_value_prop="reducing back-office cycle times",
        sender_name="Tanishq"
    )
    assert "TestCo" in rendered
    assert "DIRECT" in rendered.upper() or "confirmed fact" in rendered

def test_inferred_template_format_no_keyerror():
    """Inferred template must format cleanly with observable_signal included."""
    rendered = S6_DRAFT_USER_TEMPLATE_INFERRED.format(
        company_name="TestCo",
        target_persona="Head of Operations",
        problem_statement="Rapid customer growth may be straining manual support workflows.",
        observable_signal="TestCo recently expanded to 3 new cities and hired 12 operations coordinators.",
        hook_evidence="Claim: 'Rapid expansion' | Excerpt: '...' (Source: https://testco.com/jobs)",
        solution_sketch="Process: Support Ticket Automation. What it does: Routes and resolves tickets. Impact: Faster resolution.",
        seller_offering="workflow automation systems",
        seller_value_prop="reducing manual bottleneck cycle times",
        sender_name="Tanishq"
    )
    assert "TestCo" in rendered
    assert "INFERRED" in rendered.upper() or "hypothesis" in rendered.lower()

def test_backward_compat_alias_points_to_direct():
    """S6_DRAFT_USER_TEMPLATE backward-compat alias must equal S6_DRAFT_USER_TEMPLATE_DIRECT."""
    assert S6_DRAFT_USER_TEMPLATE == S6_DRAFT_USER_TEMPLATE_DIRECT

# --- generate_draft routing tests (async, mocked LLM) ---

MOCK_LLM_RESPONSE = {
    "subject": "ops bottleneck question",
    "subject_alternatives": ["workflow load?", "support queue depth"],
    "body": "Hi TestCo Team,\n\nSaw that TestCo recently expanded rapidly. As volume scales, support workflows often become strained — wondering if that's something you're navigating.\n\nWe build automated systems that triage and route support tickets with human checkpoints.\n\nOpen to a quick chat?",
    "linkedin_note": "Noticed TestCo's expansion — curious if support ops is keeping up. Happy to connect.",
    "why_this_hook": "Inferred draft: used observable expansion signal to bridge to hypothesis. No direct complaint cited.",
    "claim_map": {"Saw that TestCo recently expanded": ["ev_1"]}
}

@pytest.mark.anyio
async def test_generate_draft_inferred_sets_draft_style_inferred():
    """generate_draft with layer='inferred' must return draft_style='inferred'."""
    from app.stages.s6_draft import generate_draft

    hyp = ProblemHypothesis(
        id="hyp_1",
        problem="Rapid growth may be straining manual support queue handling.",
        lens="customer_support",
        layer="inferred",
        root_cause="Rapid growth without automated triage.",
        workflow_burden="Support team manually triaging all tickets.",
        automation_fit="Automated ticket routing with LLM classification."
    )
    hook_ev = EvidenceItem(
        id="ev_1",
        researcher="hiring",
        source_type="careers",
        claim="TestCo recently expanded to 3 new cities and hired 12 operations coordinators.",
        excerpt="TestCo recently expanded to 3 new cities.",
        url="https://testco.com/jobs/ops-coordinator",
        title="Operations Coordinator",
        signal_type="expansion",
        reliability_tier="B"
    )
    solution = SolutionSketch(
        id="sol_1",
        hypothesis_id="hyp_1",
        process_name="Support Ticket Automation",
        what_it_automates="Automatic triage and routing of support tickets",
        input_consumed="Incoming tickets",
        key_steps=["Classify", "Route", "Escalate"],
        human_checkpoints=["Human review for edge cases"],
        systems_touched=["Helpdesk"],
        impact_direction="Faster resolution times",
        buyer_credibility_hook="Peer teams using automation handle 3x volume without headcount increase.",
        recommended_persona="Head of Support"
    )

    with patch("app.stages.s6_draft.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = MOCK_LLM_RESPONSE
        draft = await generate_draft("TestCo", hyp, hook_ev, solution)

    assert draft.draft_style == "inferred"
    # Verify inferred template was used (observable_signal passed to call_llm prompt)
    call_args = mock_llm.call_args
    prompt_used = call_args[0][0]  # first positional arg
    assert "INFERRED" in prompt_used.upper() or "observable" in prompt_used.lower()
    assert "TestCo recently expanded" in prompt_used  # observable signal was embedded

@pytest.mark.anyio
async def test_generate_draft_stated_sets_draft_style_direct():
    """generate_draft with layer='stated' must return draft_style='direct'."""
    from app.stages.s6_draft import generate_draft

    hyp = ProblemHypothesis(
        id="hyp_2",
        problem="Users report multi-week delays in milestone gift fulfillment.",
        lens="fulfillment_ops",
        layer="stated",
        root_cause="Manual order processing disconnected from courier APIs.",
        workflow_burden="Support team manually triaging delivery complaints.",
        automation_fit="Automated courier dispatch with real-time tracking webhooks."
    )
    hook_ev = EvidenceItem(
        id="ev_2",
        researcher="customer_voice",
        source_type="community",
        claim="Multiple users on Reddit report not receiving streak reward hoodies after 6 weeks.",
        excerpt="Still waiting for my hoodie from 6 weeks ago. No update from support.",
        url="https://reddit.com/r/duolingo/comments/example",
        title="Reddit community complaint",
        signal_type="friction",
        reliability_tier="C"
    )
    solution = SolutionSketch(
        id="sol_2",
        hypothesis_id="hyp_2",
        process_name="Reward Fulfillment Automation",
        what_it_automates="End-to-end reward dispatch and status update",
        input_consumed="Reward redemption requests",
        key_steps=["Verify address", "Dispatch via courier API", "Send tracking updates"],
        human_checkpoints=["Flag exceptions for manual review"],
        systems_touched=["Courier API", "CRM"],
        impact_direction="Eliminate delivery backlogs",
        buyer_credibility_hook="Similar platforms automated fulfillment and cut complaint volume significantly.",
        recommended_persona="VP Operations"
    )

    with patch("app.stages.s6_draft.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {**MOCK_LLM_RESPONSE, "body": "Hi TestCo Team,\n\nNoticed that TestCo users on Reddit have flagged multi-week delays in streak reward hoodies — sounds like fulfillment is hitting a real bottleneck.\n\nWe build automated dispatch systems that connect reward triggers to courier APIs with tracking webhooks.\n\nOpen to comparing notes?"}
        draft = await generate_draft("TestCo", hyp, hook_ev, solution)

    assert draft.draft_style == "direct"
    call_args = mock_llm.call_args
    prompt_used = call_args[0][0]
    assert "DIRECT" in prompt_used.upper() or "confirmed fact" in prompt_used.lower()
    assert "{observable_signal}" not in prompt_used  # inferred token must NOT appear in direct prompt


def test_problem_with_configuration_friction_is_usable():
    """Operational friction and configuration friction problems must evaluate as usable."""
    from app.stages.s6_draft import _is_usable_problem_statement

    problem = (
        "Users experience frustration in the practice section due to rigid configuration requirements "
        "that prevent them from accessing the same Sprint games used for practice."
    )
    assert _is_usable_problem_statement(problem) is True


@pytest.mark.anyio
async def test_winner_with_false_fallback_banner_not_provisional():
    """A winner with fallback_info['fallback_banner_used']=False must not be treated as provisional."""
    from app.stages.s6_draft import generate_draft

    hyp = ProblemHypothesis(
        id="hyp_matiks_1",
        problem=(
            "Users experience frustration in the practice section due to rigid configuration requirements "
            "that prevent them from accessing the same Sprint games used for practice."
        ),
        lens="customer_support",
        layer="stated",
        grounding_status="verified",
        root_cause="The practice section lacks a streamlined configuration option.",
        workflow_burden="Users must manually configure specific digit counts and settings.",
        automation_fit="Automate practice section parameter selection."
    )
    # Simulate s4_score attaching fallback_info where no role fallback occurred
    hyp.fallback_info = {
        "fallback_banner_used": False,
        "banner_message": "",
        "suggested_roles": []
    }

    hook_ev = EvidenceItem(
        id="ev_matiks_1",
        researcher="reddit_community_intelligence",
        source_type="community",
        claim="Players find the app practice section frustrating due to configuration requirements.",
        excerpt="Frustrated with practice section rigid setup.",
        url="https://reddit.com/r/matiks/123",
        title="Matiks Community",
        signal_type="friction",
        reliability_tier="B"
    )
    solution = SolutionSketch(
        id="sol_matiks_1",
        hypothesis_id="hyp_matiks_1",
        process_name="Practice Mode Standardization",
        what_it_automates="Automating configuration parameters for practice games",
        input_consumed="User game mode preferences",
        key_steps=["Load preset", "Launch Sprint format"],
        human_checkpoints=["Manual parameter adjustment option"],
        systems_touched=["Game Config Engine"],
        impact_direction="Eliminate practice drop-offs",
        buyer_credibility_hook="Reduces customer support complaints regarding practice configuration.",
        recommended_persona="Head of Product"
    )

    with patch("app.stages.s6_draft.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "subject": "Matiks practice flows",
            "subject_alternatives": ["practice section setup"],
            "body": "Hi Sudhanshu,\n\nNoticed players discussing rigid configuration in the practice section...\n\nBest,\nTanishq",
            "linkedin_note": "Hi Sudhanshu, saw notes on practice configuration friction.",
            "why_this_hook": "Direct draft leveraging community feedback on practice configuration.",
            "claim_map": {}
        }
        draft = await generate_draft("Matiks", hyp, hook_ev, solution, recipient_name="Sudhanshu")

    assert draft.draft_style == "direct"
    assert "The available public material does not establish" not in draft.body
    assert "Matiks practice flows" == draft.subject

