import re
import time
import asyncio
import logging
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urlparse
from rapidfuzz import fuzz

from app.config import S1_CONFIDENCE_THRESHOLD, AGGREGATOR_DOMAINS, AGGREGATOR_BRANDS
from app.models import CompanyCandidate, CompanyIdentity
from app.tools.search import search_web
from app.tools.wikidata import search_wikidata_entities
from app.llm.router import call_llm

logger = logging.getLogger(__name__)

GENERIC_STOP_WORDS = {
    "business", "company", "services", "service", "operating", "industry",
    "platform", "looking", "about", "their", "which", "there", "these",
    "corporate", "enterprise", "solutions", "technology", "tech"
}

def _clean_company_name(name: str) -> str:
    # Strip markdown links e.g. [ARB Bearings Limited Information](/arb... -> ARB Bearings Limited Information
    name = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', name)
    name = re.sub(r'["\(\)\/]', '', name).strip().lower()
    for suffix in [" inc", " ltd", " llc", " corp", " corporation", " pvt", " co", " group", " company", " limited", " information"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()

def _extract_underlying_website(text: str) -> Optional[str]:
    """Extracts actual official company website mentioned inside directory snippets (e.g. Website: arb-bearings.com)."""
    match = re.search(r'(?:website|site|url)[:\s\|\*]+(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text, re.IGNORECASE)
    if match:
        found_domain = match.group(1).lower().strip()
        if not any(agg in found_domain for agg in AGGREGATOR_DOMAINS):
            return found_domain
    return None

def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        parts = netloc.split(".")
        if len(parts) > 2 and parts[0] in ["support", "blog", "app", "docs", "help", "careers", "jobs", "about", "investors", "in"]:
            netloc = ".".join(parts[1:])
        return netloc
    except Exception:
        return ""

async def discover_candidates(company_input: str) -> List[CompanyCandidate]:
    """
    Retrieves web signals and extracts distinct candidate entities sharing the given name.
    """
    clean_input = _clean_company_name(company_input)
    search_task = search_web(f"{company_input} company official website overview", max_results=6)
    wiki_task = search_wikidata_entities(company_input, limit=4)
    search_res, wiki_res = await asyncio.gather(search_task, wiki_task)

    snippets = []
    for r in search_res:
        snippets.append(f"- {r.get('title')}: {r.get('snippet')} (URL: {r.get('url')})")
    for w in wiki_res:
        snippets.append(f"- Wikidata: {w.get('label')} - {w.get('description')} (URI: {w.get('url')})")
    snippets_combined = "\n".join(snippets)

    # Prompt LLM to extract structured distinct candidate entities
    extract_prompt = f"""User input company: "{company_input}".
Research search results:
{snippets_combined}

Identify up to 4 plausible distinct companies that match or share the name "{company_input}".
For each company, provide:
- name: clear company brand/legal name
- domain: official website domain (e.g. ramp.com, mercury.com, apollo.io)
- industry: primary sector (e.g. Fintech, Healthcare, Aerospace, Utilities, IT Services)
- hq: headquarters location or blank if unknown
- description: 1 concise sentence of what they do
- distinguishing_fact: the primary fact that distinguishes it from other companies with the same or similar name

Return strictly JSON with key "candidates": list of objects."""

    candidates: List[CompanyCandidate] = []
    try:
        extracted = await call_llm(extract_prompt, task_type="fast", json_mode=True)
        if isinstance(extracted, dict) and "candidates" in extracted:
            for c in extracted["candidates"]:
                # Clean candidate name (strip markdown link brackets e.g. [ARB Bearings Limited](/arb... -> ARB Bearings Limited)
                cand_name = c.get("name") or company_input
                cand_name = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', cand_name)
                cand_name = re.sub(r'["\(\)\/]', '', cand_name).replace("Information", "").strip()
                cand_name = re.sub(r'\b(\w+)\s+\1\b', r'\1', cand_name, flags=re.IGNORECASE).strip()

                domain = (c.get("domain") or "").lower().replace("https://", "").replace("http://", "").split("/")[0]
                if domain.startswith("www."): domain = domain[4:]
                
                # Strict Aggregator Quarantine: NEVER let directory sites (RocketReach, ZoomInfo, etc.) become the company domain
                if any(agg in domain for agg in AGGREGATOR_DOMAINS) or "." not in domain:
                    # 1. Search description or search snippets for real underlying company website
                    real_site = _extract_underlying_website(c.get("description", "") + " " + snippets_combined)
                    if real_site:
                        domain = real_site
                    else:
                        # 2. Extract first non-aggregator domain from raw search results
                        for r in search_res:
                            d = _extract_domain(r.get("url", ""))
                            if d and not any(agg in d for agg in AGGREGATOR_DOMAINS):
                                domain = d
                                break
                        else:
                            domain = f"{_clean_company_name(cand_name).replace(' ', '')}.com"

                cand = CompanyCandidate(
                    name=cand_name,
                    domain=domain,
                    industry=c.get("industry", ""),
                    hq=c.get("hq", ""),
                    description=c.get("description", ""),
                    distinguishing_fact=c.get("distinguishing_fact", ""),
                    sources=["web_search"]
                )
                candidates.append(cand)
    except Exception as e:
        logger.warning(f"LLM candidate extraction error: {e}")

    # Deduplicate candidates by domain, merging richer metadata if duplicates exist
    seen_domains = set()
    deduped: List[CompanyCandidate] = []
    for cand in candidates:
        d = (cand.domain or "").lower().strip()
        if d and d in seen_domains:
            for existing in deduped:
                if (existing.domain or "").lower().strip() == d:
                    if not existing.hq and cand.hq:
                        existing.hq = cand.hq
                    if not existing.industry and cand.industry:
                        existing.industry = cand.industry
                    if len(cand.description or "") > len(existing.description or ""):
                        existing.description = cand.description
            continue
        if d:
            seen_domains.add(d)
        deduped.append(cand)
    candidates = deduped

    # Fallback to direct search results if extraction yielded nothing
    if not candidates:
        for r in search_res:
            d = _extract_domain(r.get("url", ""))
            if d and not any(agg in d for agg in AGGREGATOR_DOMAINS):
                candidates.append(CompanyCandidate(
                    name=r.get("title", "").split("-")[0].split("|")[0].strip(),
                    domain=d,
                    description=r.get("snippet", ""),
                    sources=["web_search"]
                ))
                break

    if not candidates:
        candidates.append(CompanyCandidate(
            name=company_input,
            domain=f"{clean_input.replace(' ', '')}.com",
            description=f"Company entity for {company_input}"
        ))

    return candidates

def score_candidates_pool(
    candidates: List[CompanyCandidate],
    company_input: str,
    hints: Dict[str, Any],
    answers_history: List[str] = None
) -> Tuple[List[CompanyCandidate], CompanyCandidate, float, bool]:
    """
    Deterministically scores all candidates against the input, hints, and accumulated user answers.
    Returns: (scored_candidates, best_candidate, confidence, is_confirmed)
    """
    # Deduplicate candidates pool by domain upfront so identical companies don't self-compete
    seen_domains = set()
    deduped_candidates = []
    for c in candidates:
        d = (c.domain or "").lower().strip()
        if d and d in seen_domains:
            continue
        if d:
            seen_domains.add(d)
        deduped_candidates.append(c)
    candidates = deduped_candidates

    clean_input = _clean_company_name(company_input)
    website_hint = (hints.get("website_hint") or "").lower()
    country_hint = (hints.get("country_hint") or "").lower()
    industry_hint = (hints.get("industry_hint") or "").lower()
    
    # Merge all answers into a searchable answer corpus
    answer_text = " ".join(answers_history or []).lower()

    for c in candidates:
        clean_c_name = _clean_company_name(c.name)
        domain_root = c.domain.split(".")[0]
        
        # 1. Name Match (0.35)
        is_exact = clean_input == clean_c_name or clean_input == domain_root or clean_input in clean_c_name.split()
        if is_exact:
            name_score = 1.0
        else:
            name_score = max(
                fuzz.token_sort_ratio(clean_input, clean_c_name) / 100.0,
                fuzz.token_set_ratio(clean_input, clean_c_name) / 100.0
            )

        # 2. Corroboration (0.30)
        corroboration = 0.85 if c.description and c.domain else 0.50

        # 3. Hint / Clarification Match (0.20)
        # Check against initial hints AND user answer text
        hint_score = 0.50 # neutral baseline
        matched_points = 0
        total_checks = 0

        # Check website hint
        if website_hint:
            total_checks += 2
            if website_hint in c.domain or c.domain in website_hint:
                matched_points += 2
                
        # Check industry hint
        if industry_hint:
            total_checks += 1
            if industry_hint in c.industry.lower() or industry_hint in c.description.lower():
                matched_points += 1

        # Check country / location hint
        if country_hint:
            total_checks += 1
            if country_hint in c.hq.lower() or country_hint in c.description.lower():
                matched_points += 1

        # Section 4: Joint-Confidence Rule (S0 -> S1 handoff)
        # If S0 had strong employment corroboration and S0 evidence URLs confirm this candidate's domain,
        # award a joint-confidence bonus to hint match.
        s0_evidence_urls = hints.get("s0_evidence_urls") or []
        s0_corrob = float(hints.get("s0_employment_corroboration") or 0.0)
        if s0_corrob >= 0.70 and s0_evidence_urls and c.domain:
            if any(c.domain in u.lower() for u in s0_evidence_urls):
                matched_points += 2.5
                total_checks += 2.5

        # Check accumulated answers from clarification rounds
        if answer_text:
            total_checks += 3
            # Check domain match in answer
            if c.domain in answer_text or domain_root in answer_text:
                matched_points += 3
            else:
                # Check industry match (filtering stop words)
                ind_words = [w for w in re.findall(r'\w+', c.industry.lower()) if len(w) > 3 and w not in GENERIC_STOP_WORDS]
                ind_match = bool(ind_words and any(w in answer_text for w in ind_words))

                # Check hq/location match
                hq_words = [w for w in re.findall(r'\w+', c.hq.lower()) if len(w) > 3 and w not in GENERIC_STOP_WORDS]
                hq_match = bool(hq_words and any(w in answer_text for w in hq_words))

                if ind_match: matched_points += 2.5
                if hq_match: matched_points += 2.0

        if total_checks > 0:
            hint_score = min(matched_points / total_checks, 1.0)
            # If user provided clarification answers and candidate got 0 points, penalize contradiction
            if answer_text and matched_points == 0:
                hint_score = 0.0

        # 4. Liveness (0.15)
        liveness = 1.0 if "." in c.domain else 0.5

        # Weighted formula: 0.35 name + 0.30 corroboration + 0.20 hint + 0.15 liveness
        # If explicitly contradicted by user clarification, apply contradiction penalty
        penalty = 0.20 if (answer_text and hint_score == 0.0) else 0.0
        c_score = max(0.0, (0.35 * name_score) + (0.30 * corroboration) + (0.20 * hint_score) + (0.15 * liveness) - penalty)
        
        c.name_match_score = round(name_score, 2)
        c.corroboration_score = round(corroboration, 2)
        c.hint_match_score = round(hint_score, 2)
        c.liveness_score = round(liveness, 2)
        c.final_score = round(c_score, 3)

    # Sort descending
    candidates.sort(key=lambda x: x.final_score, reverse=True)
    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    runner_up_score = runner_up.final_score if runner_up else 0.0

    # Ambiguity factor:
    # If user explicitly matched the domain in hints or answers, ambiguity = 1.0
    if website_hint and (website_hint in best.domain or best.domain in website_hint):
        ambiguity_factor = 1.0
    elif answer_text and (best.domain in answer_text or best.domain.split('.')[0] in answer_text):
        ambiguity_factor = 1.0
    elif runner_up and best.hint_match_score >= 0.60 and runner_up.hint_match_score <= 0.20:
        # Clarification cleanly separated the winner from the runner up!
        ambiguity_factor = 1.0
    elif len(candidates) > 1:
        diff = best.final_score - runner_up_score
        if diff >= 0.25:
            ambiguity_factor = 1.0
        elif diff <= 0.05:
            ambiguity_factor = 0.60
        else:
            ambiguity_factor = 0.60 + ((diff - 0.05) / 0.20) * 0.40
    else:
        ambiguity_factor = 1.0

    overall_confidence = round(best.final_score * ambiguity_factor, 2)
    is_confirmed = overall_confidence >= S1_CONFIDENCE_THRESHOLD

    return candidates, best, overall_confidence, is_confirmed

def generate_clarifying_question(candidates: List[CompanyCandidate], round_num: int) -> str:
    """
    Selects the attribute that best separates the top remaining candidates.
    Round 1: Industry / Sector
    Round 2: HQ Location / Geography
    Round 3: Official Domain / Website
    """
    if len(candidates) < 2:
        return f"Could you provide the official website domain for {candidates[0].name} (e.g., {candidates[0].domain})?"

    c1 = candidates[0]
    c2 = candidates[1]

    if round_num == 1:
        # Separate by industry/sector
        ind1 = c1.industry or "their main sector"
        ind2 = c2.industry or "their alternative sector"
        return f"Which industry is the company in? Are you looking for {c1.name} ({ind1}) or {c2.name} ({ind2})?"
    
    elif round_num == 2:
        # Separate by location or distinguishing fact
        hq1 = c1.hq or c1.distinguishing_fact or c1.domain
        hq2 = c2.hq or c2.distinguishing_fact or c2.domain
        return f"Could you specify their headquarters location or official domain? (e.g., {c1.domain} in {c1.hq} vs {c2.domain} in {c2.hq})?"
    
    else:
        # Round 3+: Direct website domain request
        return f"To guarantee we research the exact right entity, please enter the company's official website URL (e.g., {c1.domain} or {c2.domain}):"

async def resolve_company(
    company_input: str,
    hints: Dict[str, Any]
) -> Tuple[CompanyIdentity, bool]:
    """
    Main S1 entrypoint: Discovers candidate entities and scores them against the 0.80 threshold.
    """
    candidates = await discover_candidates(company_input)
    scored_candidates, best, confidence, is_confirmed = score_candidates_pool(
        candidates, company_input, hints, answers_history=[]
    )

    clarification_questions = []
    if not is_confirmed:
        q = generate_clarifying_question(scored_candidates, round_num=1)
        clarification_questions = [q]

    identity = CompanyIdentity(
        name=best.name,
        domain=best.domain,
        industry=best.industry,
        hq=best.hq,
        confidence=confidence,
        confirmation_method="auto" if is_confirmed else "pending",
        alternatives=scored_candidates,
        clarification_questions=clarification_questions,
        clarification_round=1
    )

    return identity, is_confirmed
