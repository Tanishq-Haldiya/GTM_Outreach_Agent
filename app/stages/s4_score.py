from typing import List, Tuple, Dict, Any, Optional
from app.config import SCORE_WEIGHTS, LAYER_MULTIPLIERS
from app.models import ProblemHypothesis, EvidenceItem
from app.roles import canonical_lens, get_role_fit_multiplier, suggest_roles_for_lens

def score_and_select_hypothesis(
    hypotheses: List[ProblemHypothesis],
    evidence_list: List[EvidenceItem],
    recipient_lens: Optional[str] = None,
    adjacent_lenses: Optional[List[str]] = None,
    return_fallback_info: bool = False,
    person_profile: Optional[Any] = None
) -> Any:
    """
    S4 Deterministic Scoring and Selection:
    Computes exact scores based on weights, layer multipliers, recency discount,
    Tier 1 Role-Fit multipliers, and Tier 3 Person RoleFit multipliers.
    Ranks hypotheses and picks the winner and its hook evidence.
    """
    from app.roles import get_person_role_fit_multiplier

    evidence_map = {e.id: e for e in evidence_list}
    is_role_provided = bool(recipient_lens and canonical_lens(recipient_lens) != "broad (neutral weights)")
    is_person_provided = bool(person_profile and getattr(person_profile, "function", None))

    # 1. Compute Base Score for every hypothesis (Tier 0 formula)
    for hyp in hypotheses:
        w = SCORE_WEIGHTS
        raw_composite = (
            (w["evidence_strength"] * hyp.evidence_strength) +
            (w["business_impact"] * hyp.business_impact) +
            (w["automatability"] * hyp.automatability) +
            (w["timeliness"] * hyp.timeliness) +
            (w["buyer_credibility"] * hyp.buyer_credibility)
        )
        layer_mult = LAYER_MULTIPLIERS.get(hyp.layer, 0.7)
        freshness_mult = 0.65 if hyp.timeliness < 0.50 else 1.0
        base_score = round(raw_composite * layer_mult * freshness_mult, 3)
        hyp.base_score = base_score

        # Role-fit multiplier (Tier 1 role lens or Tier 3 person function)
        if is_person_provided:
            role_fit, role_badge = get_person_role_fit_multiplier(
                getattr(hyp, "owner_function", None),
                person_profile.function,
                hyp.problem
            )
            role_badge = role_badge.lower()
        elif is_role_provided:
            role_fit, role_badge = get_role_fit_multiplier(hyp.lens, recipient_lens, adjacent_lenses)
        else:
            role_fit, role_badge = 1.0, "broad"

        adjusted_score = round(base_score * role_fit, 3)
        hyp.role_fit = role_fit
        hyp.role_fit_badge = role_badge
        hyp.adjusted_score = adjusted_score
        hyp.final_score = adjusted_score

        # Quantitative source authority across cited evidence items
        cited_auths = [
            getattr(evidence_map[eid], "authority_score", 0.85)
            for eid in hyp.evidence_ids
            if eid in evidence_map and getattr(evidence_map[eid], "authority_score", None) is not None
        ]
        avg_auth = round(sum(cited_auths) / len(cited_auths), 2) if cited_auths else 0.80

        hyp.score_breakdown = {
            "evidence_strength": round(hyp.evidence_strength, 2),
            "w_evidence": w["evidence_strength"],
            "business_impact": round(hyp.business_impact, 2),
            "w_impact": w["business_impact"],
            "automatability": round(hyp.automatability, 2),
            "w_auto": w["automatability"],
            "timeliness": round(hyp.timeliness, 2),
            "w_time": w["timeliness"],
            "buyer_credibility": round(hyp.buyer_credibility, 2),
            "w_cred": w["buyer_credibility"],
            "avg_source_authority": avg_auth,
            "raw_composite": round(raw_composite, 3),
            "layer_mult": layer_mult,
            "freshness_mult": freshness_mult,
            "base_score": base_score,
            "role_fit": role_fit,
            "role_fit_badge": role_badge,
            "adjusted_score": adjusted_score,
            "final_score": adjusted_score
        }

    # Sort descending by adjusted_score (or base_score when role is broad)
    hypotheses.sort(key=lambda h: (h.adjusted_score if h.adjusted_score is not None else h.final_score), reverse=True)
    for i, hyp in enumerate(hypotheses):
        hyp.rank = i + 1

    # Check fallback condition (Section 4.4)
    # If role is provided, check if any problem in primary or adjacent lenses has base_score >= 0.35
    fallback_info = {
        "fallback_banner_used": False,
        "banner_message": "",
        "suggested_roles": []
    }

    winner = hypotheses[0] if hypotheses else None

    if is_role_provided and hypotheses:
        has_strong_role_problem = any(
            h.role_fit_badge in ["primary", "adjacent"] and (h.base_score or 0) >= 0.35
            for h in hypotheses
        )
        if not has_strong_role_problem:
            # Fallback triggered! Pick best company-level problem by base_score
            company_best = max(hypotheses, key=lambda h: (h.base_score or 0))
            winner = company_best
            fallback_info["fallback_banner_used"] = True
            fallback_info["banner_message"] = (
                f"No strong problem was found in this role's area ({recipient_lens}). "
                f"Drafting for the best company-level problem instead."
            )
            fallback_info["suggested_roles"] = suggest_roles_for_lens(company_best.lens)

    # Attach fallback info to winner
    if winner:
        setattr(winner, "fallback_info", fallback_info)

    # --- Section 5.4 Hook Selection ---
    hook_ev = None
    person_hook_selected = False

    # Check for valid person-level items
    person_items = [
        e for e in evidence_list
        if (getattr(e, "about", "company") == "person" or getattr(e, "source_type", "") in ["sdr_provided", "person_voice"])
        and getattr(e, "sensitivity", "none") != "sensitive"
    ]

    top_adj_score = hypotheses[0].adjusted_score if hypotheses else 0.0

    if person_items and hypotheses:
        # Situation 1: Person-level item exists and its topic_lens matches one of top 3 role-adjusted problems,
        # and that problem is within about 0.15 of the top adjusted score
        top_3 = hypotheses[:3]
        for p_ev in person_items:
            # Match by lens or signal
            ev_lens = canonical_lens(getattr(p_ev, "signal_type", "") or getattr(p_ev, "title", ""))
            for cand_hyp in top_3:
                hyp_lens = canonical_lens(cand_hyp.lens)
                score_diff = top_adj_score - (cand_hyp.adjusted_score or 0.0)
                if (ev_lens == hyp_lens or ev_lens in ["broad (neutral weights)", "leadership_priority"]) and score_diff <= 0.15:
                    winner = cand_hyp
                    hook_ev = p_ev
                    person_hook_selected = True
                    break
            if person_hook_selected:
                break

    # If no person hook selected, use Tier 0 evidence selection
    if not hook_ev and winner:
        for eid in winner.evidence_ids:
            if eid in evidence_map:
                candidate_ev = evidence_map[eid]
                cand_auth = getattr(candidate_ev, "authority_score", 0.85) or 0.0
                hook_auth = getattr(hook_ev, "authority_score", 0.0) if hook_ev else 0.0
                if not hook_ev or cand_auth > hook_auth or (cand_auth == hook_auth and candidate_ev.reliability_tier < hook_ev.reliability_tier):
                    hook_ev = candidate_ev

    if not hook_ev and evidence_list:
        hook_ev = evidence_list[0]

    if return_fallback_info:
        return hypotheses, winner, hook_ev, fallback_info

    return hypotheses, winner, hook_ev
