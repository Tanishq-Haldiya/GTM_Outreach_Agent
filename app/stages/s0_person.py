import re
import time
import asyncio
import logging
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urlparse
from rapidfuzz import fuzz

from app.config import S1_CONFIDENCE_THRESHOLD, AGGREGATOR_DOMAINS
from app.models import PersonCandidate, PersonProfile
from app.roles import normalize_person_role, detect_person_seniority
from app.tools.search import search_web
from app.tools.wikidata import search_wikidata_entities
from app.llm.router import call_llm

logger = logging.getLogger(__name__)

def _clean_name(name: str) -> str:
    """Cleans a person or company name for matching."""
    if not name:
        return ""
    # Strip titles/credentials like Ph.D., MD, Esq., etc.
    n = re.sub(r'\b(ph\.?d|m\.?d|esq|cfa|cpa|jr|sr|ii|iii)\b', '', name, flags=re.IGNORECASE)
    n = re.sub(r'[^a-zA-Z0-9\s]', ' ', n).strip().lower()
    return " ".join(n.split())

def _extract_first_name(full_name: str) -> str:
    """Extracts first name from full name."""
    if not full_name:
        return "there"
    parts = full_name.strip().split()
    first = parts[0]
    # Remove honorifics like Mr., Ms., Dr.
    if first.lower().rstrip('.') in ["mr", "ms", "mrs", "dr", "prof"] and len(parts) > 1:
        first = parts[1]
    return first.capitalize()

def _detect_source_type(url: str, snippet: str) -> str:
    """Classifies source type for employment corroboration credit."""
    u = (url or "").lower()
    s = (snippet or "").lower()
    if "linkedin.com" in u:
        return "linkedin_snippet"
    if any(k in u for k in ["/team", "/leadership", "/about", "/people", "/management"]):
        return "team_page"
    if any(k in u for k in ["prnewswire", "businesswire", "globenewswire", "techcrunch", "bloomberg", "reuters", "press"]):
        return "press_release"
    if any(k in s for k in ["speaker", "keynote", "conference", "panelist", "summit"]) or "speaker" in u:
        return "speaker_bio"
    if any(k in s for k in ["podcast", "interview", "episode", "guest"]):
        return "interview"
    if "wikidata.org" in u:
        return "wikidata"
    return "web_search"

def _normalize_profile_url(url: str) -> str:
    """Normalizes profile URLs (e.g. LinkedIn handles) to deduplicate candidates by person."""
    if not url:
        return ""
    u = url.lower().strip()
    m = re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', u)
    if m:
        return f"linkedin.com/in/{m.group(1)}"
    return u

def _get_company_variants(company: str) -> List[str]:
    c_lower = (company or "").lower().strip()
    if not c_lower:
        return []
    variants = [c_lower]
    # Strip common suffixes/units
    stripped = re.sub(r'\b(exports unit|unit|ltd|pvt ltd|inc|llc|corp|corporation|group|technologies|solutions|holdings)\b', '', c_lower).strip()
    if stripped and stripped != c_lower:
        variants.append(stripped)
    words = [w for w in re.split(r'[\s,.-]+', c_lower) if len(w) >= 4 and w not in {'from', 'with', 'that', 'this', 'unit', 'exports', 'team', 'technologies', 'solutions'}]
    if words and words[0] not in variants:
        variants.append(words[0])
    return variants

def is_ended_role(title: str, company: str, snippet: str = "") -> bool:
    """
    Detects whether a role or company association has ended based on LinkedIn snippets,
    titles, past employment markers, or closed date ranges.
    """
    t_lower = (title or "").lower().strip()
    c_lower = (company or "").lower().strip()
    s_lower = (snippet or "").lower()

    # 1. Direct title or company string markers (e.g. 'Former VP', 'Ex-Google')
    past_markers = [
        "former", "ex-", "ex ", "previously", "past ", "prior to",
        "stepped down", "alumni", "retired", "emeritus", "left the company",
        "served as", "past experience"
    ]
    if any(p in t_lower or p in c_lower for p in past_markers):
        return True

    if not c_lower or not s_lower:
        return False

    comp_variants = _get_company_variants(company)

    # 2. Check explicit Past: / Previous: / Prior: section in LinkedIn snippets
    past_match = re.search(r'(?:past|previous|prior):\s*([^.\n|]+)', s_lower)
    if past_match:
        past_section = past_match.group(1)
        for c_var in comp_variants:
            if c_var in past_section:
                return True
        if t_lower and t_lower in past_section:
            return True

    # 3. Check for specific title-level closed date ranges
    # On LinkedIn, entries are lines like: "- Powertrain Engineer at Team KNOx IIT Roorkee (Jan 2025 to Apr 2026)"
    # or "Google · Software Engineer · 2018 - 2021"
    if t_lower:
        title_esc = re.escape(t_lower)
        t_date_pat = rf'{title_esc}[^\n|]*?\b(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(?:19\d\d|20\d\d)\s*(?:to|-|–|—)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(?:19\d\d|20\d\d)\b'
        m_t = re.search(t_date_pat, s_lower)
        if m_t:
            span = m_t.group(0)
            if not any(curr in span for curr in ['present', 'current', 'now']):
                return True
            else:
                return False

    # 4. Check if the company is associated with active signals ('present', 'current', 'now', 'headline')
    # and no title-specific closed date was found above
    for c_var in comp_variants:
        has_present = bool(
            re.search(rf'{re.escape(c_var)}[^\n()·|]*\([^)]*?(?:present|current|now)[^)]*\)', s_lower) or
            re.search(rf'\([^)]*?(?:present|current|now)[^)]*\)[^\n()·|]*{re.escape(c_var)}', s_lower) or
            re.search(rf'(?:current|headline|present)[^\n|·]*?{re.escape(c_var)}', s_lower) or
            re.search(rf'current role:[^\n]*{re.escape(c_var)}', s_lower) or
            re.search(rf'headline:[^\n]*{re.escape(c_var)}', s_lower)
        )
        if has_present:
            return False

    # 6. Check closed date ranges for company variants (do NOT span across past: or major sections)
    for c_var in comp_variants:
        c_esc = re.escape(c_var)
        date_patterns = [
            rf'{c_esc}[^\n()·|]*\([^)]*?(?:19\d\d|20\d\d)[^)]*?(?:to|-|–|—)\s*(?:[a-z]*\s*)?(?:19\d\d|20\d\d)[^)]*\)',
            rf'\([^)]*?(?:19\d\d|20\d\d)[^)]*?(?:to|-|–|—)\s*(?:[a-z]*\s*)?(?:19\d\d|20\d\d)[^)]*\)[^\n()·|]*{c_esc}',
            rf'{c_esc}[^\n·|]*\b(?:19\d\d|20\d\d)\s*(?:-|–|—|to)\s*(?:19\d\d|20\d\d)\b',
            rf'{c_esc}\s*·\s*[^·\n|]*?\b(?:19\d\d|20\d\d)\s*(?:-|–|—|to)\s*(?:19\d\d|20\d\d)\b'
        ]
        for pat in date_patterns:
            m = re.search(pat, s_lower)
            if m:
                matched_span = m.group(0)
                if not any(curr in matched_span for curr in ['present', 'current', 'now']):
                    return True

    # 6. Check phrasing like 'formerly at <company>', 'ex-<company>', 'left <company>'
    for c_var in comp_variants:
        if re.search(rf'\b(?:former|formerly|ex|previously|prior to)\s+(?:at\s+)?{re.escape(c_var)}\b', s_lower):
            return True
        if re.search(rf'{re.escape(c_var)}[^\n·|]*\bended\b', s_lower):
            return True

    return False

def _detect_recency_signal(snippet: str) -> float:
    """
    Rewards current-role signals; penalizes 'former', 'ex-', 'previously', or past join dates.
    """
    s = (snippet or "").lower()
    
    # Penalize former roles
    if any(term in s for term in ["former", "ex-", "previously", "stepped down", "left the company", "served as", "prior to"]):
        return 0.20

    # Strong current role signals
    if any(term in s for term in ["currently", "serves as", "is the current", "leads the", "appointed as", "joins as", "co-founded", "founded"]):
        return 1.0

    # Check for recent years (2024-2026)
    if any(yr in s for yr in ["2024", "2025", "2026"]):
        return 0.90
    if any(yr in s for yr in ["2022", "2023"]):
        return 0.75
    if any(yr in s for yr in ["2018", "2019", "2020", "2021"]):
        return 0.40

    return 0.70 # neutral baseline

async def discover_person_candidates(
    person_name: str,
    hints: Optional[Dict[str, Any]] = None,
    hint_query: Optional[str] = None
) -> List[PersonCandidate]:
    """
    Parallel discovery (Section 2, Step A & B):
    Reuses the search harness to find mentions of this person across LinkedIn snippets,
    news, speaker bios, team pages, and Wikidata.
    Extracts up to 8 plausible candidates.
    """
    hints = dict(hints or {})
    if hint_query and not hints.get("company_hint"):
        hints["company_hint"] = hint_query
    company_hint = hints.get("company_hint") or hints.get("company") or hints.get("company_name") or ""
    city_hint = hints.get("city_hint") or hints.get("city") or hints.get("location") or ""
    role_hint = hints.get("role_hint") or hints.get("role") or hints.get("title") or ""
    
    hint_tokens = " ".join([h for h in [company_hint, city_hint, role_hint] if h])

    # Construct search queries
    q1 = f'"{person_name}" {hint_tokens}'.strip()
    q2 = f'"{person_name}" CEO OR founder OR head OR director OR VP OR manager'
    q3 = f'site:linkedin.com/in "{person_name}"'
    q4 = f'"{person_name}" interview OR podcast OR speaker OR "joins as" OR appointed'

    # Execute searches in parallel
    tasks = [
        search_web(q1, max_results=6),
        search_web(q2, max_results=6),
        search_web(q3, max_results=8),
        search_web(q4, max_results=6),
        search_wikidata_entities(person_name, limit=4)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    raw_snippets = []
    # Collect search results
    for i in range(4):
        res = results[i]
        if isinstance(res, list):
            for r in res:
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                src_type = _detect_source_type(url, snippet)
                raw_snippets.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source_type": src_type
                })

    # Collect Wikidata
    wiki_res = results[4]
    if isinstance(wiki_res, list):
        for w in wiki_res:
            raw_snippets.append({
                "title": w.get("label", ""),
                "snippet": w.get("description", ""),
                "url": w.get("url", ""),
                "source_type": "wikidata"
            })

    if not raw_snippets:
        # Fallback candidate if web search returned nothing
        first = _extract_first_name(person_name)
        return [PersonCandidate(
            name=person_name,
            first_name=first,
            title_raw=role_hint or "Executive",
            company_raw=company_hint or "Unknown Company",
            source_url="",
            source_type="manual",
            location=city_hint or None
        )]

    # Fast structured LLM extraction pass (JSON mode)
    # Capping to top 12 snippets keeps prompt size safely under 2,500 tokens, well within Groq's 7,000 ITPM limit
    snippets_text = "\n".join([
        f"- [{s['source_type']}] Title: {s['title']} | Snippet: {s['snippet']} (URL: {s['url']})"
        for s in raw_snippets[:12]
    ])

    extract_prompt = f"""Target Person to resolve: "{person_name}".
Optional Hints: Company="{company_hint}", City="{city_hint}", Role="{role_hint}"

Research Snippets:
{snippets_text}

Task: Extract up to 8 plausible distinct identity candidates for "{person_name}".

CRITICAL REQUIREMENT - ACTIVE / CURRENT ROLES ONLY:
- Extract ALL roles that are currently active and marked present (e.g. marked "(... to present)", "present", "current", "now", or in headline).
- If a person has multiple roles currently marked present on their profile, extract EVERY role that is marked present.
- DO NOT extract past, former, ex-, or ended positions (e.g. marked "Past:", "Former", "Ex-", "previously", or closed date ranges like "2019 to 2023", "Jan 2025 to Apr 2026" without 'present').
- Markdown section headers like '## Experience' or '## Education' indicate sections, not job titles or companies: do NOT prepend or include section headers in title_raw or company_raw.
- Do NOT extract degrees or schools from the Education section as companies.

For each candidate person:
- name: Full name as seen (e.g. "{person_name}")
- title_raw: Their specific CURRENT job title / role (e.g. "Co-Founder & CEO", "VP of Operations", "Data Science Trainee", "Manager", "Student Mentor")
- company_raw: Clean brand name of the CURRENT company or organization they work for
- is_current: true or false (must be true)
- location: City or Country if mentioned, else null
- source_url: Most relevant URL proving their employment
- source_type: One of [linkedin_snippet, team_page, press_release, speaker_bio, interview, wikidata, web_search]

Return strict JSON:
{{
  "candidates": [
    {{
      "name": "{person_name}",
      "title_raw": "...",
      "company_raw": "...",
      "is_current": true,
      "location": "...",
      "source_url": "...",
      "source_type": "..."
    }}
  ]
}}"""

    extracted_candidates: List[PersonCandidate] = []
    try:
        resp = await call_llm(
            extract_prompt,
            system_prompt="You extract verified person identities from search snippets into structured JSON. Extract only real, active, current companies and titles. Ignore ended or past roles.",
            task_type="fast",
            json_mode=True
        )
        items = resp.get("candidates", []) if isinstance(resp, dict) else []
        for it in items:
            if not it or not isinstance(it, dict):
                continue
            c_name = it.get("name") or person_name
            c_comp = (it.get("company_raw") or "").strip()
            c_title = (it.get("title_raw") or "").strip()

            if not c_comp or c_comp.lower() in ["unknown", "n/a", "none"]:
                continue
            if it.get("is_current") is False:
                continue

            # Find matching snippet text to verify current status
            matched_snip = ""
            c_url = it.get("source_url") or ""
            if c_url:
                for s in raw_snippets:
                    if s["url"] == c_url:
                        matched_snip = f"{s['title']} {s['snippet']}"
                        break
            if not matched_snip:
                for s in raw_snippets:
                    if c_comp.lower() in s["snippet"].lower() or c_comp.lower() in s["title"].lower():
                        matched_snip = f"{s['title']} {s['snippet']}"
                        break

            if is_ended_role(c_title, c_comp, matched_snip):
                logger.info(f"Filtered out ended role: '{c_title}' at '{c_comp}'")
                continue

            extracted_candidates.append(PersonCandidate(
                name=c_name,
                first_name=_extract_first_name(c_name),
                title_raw=c_title or "Executive",
                company_raw=c_comp,
                location=it.get("location") or city_hint or None,
                source_url=it.get("source_url") or "",
                source_type=it.get("source_type") or "web_search",
                evidence_urls=[it.get("source_url")] if it.get("source_url") else [],
                snippet_text=matched_snip,
                is_current=True
            ))
    except Exception as e:
        logger.warning(f"S0 LLM candidate extraction failed: {e}")

    # Heuristic parsing fallback / supplement to bring all roles from profiles marked present
    existing_companies = {c.company_raw.lower() for c in extracted_candidates}

    for s in raw_snippets:
        if len(extracted_candidates) >= 8:
            break
        txt = f"{s['title']}\n{s['snippet']}"
        lines = txt.splitlines()
        in_education = False
        for line in lines:
            if len(extracted_candidates) >= 8:
                break
            line = line.strip()
            if not line:
                continue
            # Track section headers structurally
            if re.match(r'^#+\s*education\b', line, re.I):
                in_education = True
                continue
            if re.match(r'^#+\s*(?:experience|employment|work|history)\b', line, re.I):
                in_education = False
                continue
            if in_education or line.startswith("#"):
                continue

            # Clean off trailing [...] or Description: if present in search snippet
            clean_line = re.sub(r'\s*(?:\[\.\.\.\]|Description:).*$', '', line).strip()

            # Check bullet role format: "- <Title> at <Company> (<Dates>)"
            m_bullet = re.match(r'^[-*•]\s*(.+?)\s+(?:at|@)\s+(.+?)(?:\s*\(([^)]+)\))?$', clean_line)
            if m_bullet:
                t_raw = m_bullet.group(1).strip()
                comp_raw = m_bullet.group(2).strip()
                dates = (m_bullet.group(3) or "").strip()
                
                # If date range is closed and does not have present/current/now, it is ended
                if dates:
                    has_present = any(p in dates.lower() for p in ['present', 'current', 'now'])
                    has_closed = bool(re.search(r'\b(?:19\d\d|20\d\d)\s*(?:to|-|–|—)\s*(?:[a-z]*\s*)?(?:19\d\d|20\d\d)\b', dates.lower()))
                    if has_closed and not has_present:
                        continue

                if is_ended_role(t_raw, comp_raw, clean_line):
                    continue

                if len(comp_raw) > 1 and len(comp_raw) < 50 and comp_raw.lower() not in existing_companies:
                    existing_companies.add(comp_raw.lower())
                    extracted_candidates.append(PersonCandidate(
                        name=person_name,
                        first_name=_extract_first_name(person_name),
                        title_raw=t_raw,
                        company_raw=comp_raw,
                        source_url=s["url"],
                        source_type=s["source_type"],
                        evidence_urls=[s["url"]],
                        snippet_text=clean_line,
                        is_current=True
                    ))
            else:
                # Headline format: "Name - Title at Company"
                m_headline = re.search(rf'^{re.escape(person_name)}[^\na-zA-Z0-9]+(?:is\s+the\s+)?([A-Za-z /&-]+)\s+(?:at|of|@)\s+([A-Za-z0-9\s.-]+)', clean_line, re.IGNORECASE)
                if m_headline:
                    t_raw = m_headline.group(1).strip()
                    comp_raw = m_headline.group(2).split("-")[0].split("|")[0].strip()
                    if is_ended_role(t_raw, comp_raw, clean_line):
                        continue
                    if len(comp_raw) > 1 and len(comp_raw) < 50 and comp_raw.lower() not in existing_companies:
                        existing_companies.add(comp_raw.lower())
                        extracted_candidates.append(PersonCandidate(
                            name=person_name,
                            first_name=_extract_first_name(person_name),
                            title_raw=t_raw,
                            company_raw=comp_raw,
                            source_url=s["url"],
                            source_type=s["source_type"],
                            evidence_urls=[s["url"]],
                            snippet_text=clean_line,
                            is_current=True
                        ))

    # Step B: Candidate merge by (normalized name, normalized company)
    # Deduplicates so identical (person, company) entries don't self-compete
    merged: Dict[Tuple[str, str], PersonCandidate] = {}
    for cand in extracted_candidates:
        key = (_clean_name(cand.name), _clean_name(cand.company_raw))
        if not key[1]: # skip if empty company
            continue
        if key not in merged:
            merged[key] = cand
        else:
            existing = merged[key]
            # Accumulate evidence URLs
            if cand.source_url and cand.source_url not in existing.evidence_urls:
                existing.evidence_urls.append(cand.source_url)
            # Count independent source types
            existing.independent_sources_count += 1
            if len(cand.title_raw) > len(existing.title_raw):
                existing.title_raw = cand.title_raw
            if not existing.location and cand.location:
                existing.location = cand.location
            if getattr(cand, "snippet_text", "") and not getattr(existing, "snippet_text", ""):
                existing.snippet_text = cand.snippet_text
            elif getattr(cand, "snippet_text", ""):
                existing.snippet_text += " " + cand.snippet_text

    candidate_list = list(merged.values())

    # Deterministic filter: remove ended/former roles
    candidate_list = [
        c for c in candidate_list
        if not is_ended_role(c.title_raw, c.company_raw, getattr(c, "snippet_text", ""))
    ]

    # Fallback if empty
    if not candidate_list:
        candidate_list.append(PersonCandidate(
            name=person_name,
            first_name=_extract_first_name(person_name),
            title_raw=role_hint or "Executive",
            company_raw=company_hint or "Unknown Company",
            source_url="",
            source_type="manual",
            location=city_hint or None
        ))

    # Normalize functions and seniorities for all discovered candidates
    for cand in candidate_list:
        norm_info = await normalize_person_role(cand.title_raw)
        cand.function = norm_info["function"]
        cand.seniority = norm_info["seniority"]
        cand.title_normalized = norm_info.get("title_normalized", cand.title_raw)

    return candidate_list

def score_person_candidates(
    candidates: List[PersonCandidate],
    person_name: str,
    hints: Optional[Dict[str, Any]] = None,
    answers_history: Optional[List[str]] = None
) -> Tuple[List[PersonCandidate], PersonCandidate, float, bool]:
    """
    Deterministic Scoring (Section 2, Step C):
    PersonConf = Ambiguity x [0.35*NameMatch + 0.30*EmploymentCorroboration + 0.20*HintMatch + 0.15*Recency]
    """
    hints = hints or {}
    company_hint = (hints.get("company_hint") or hints.get("company") or hints.get("company_name") or "").lower().strip()
    city_hint = (hints.get("city_hint") or hints.get("city") or hints.get("location") or "").lower().strip()
    role_hint = (hints.get("role_hint") or hints.get("role") or hints.get("title") or "").lower().strip()
    
    # Merge all answers into answer corpus for clarification updates
    answer_text = " ".join(answers_history or []).lower().strip()

    clean_target_name = _clean_name(person_name)

    for c in candidates:
        clean_c_name = _clean_name(c.name)
        clean_c_comp = _clean_name(c.company_raw)

        # 1. NameMatch (0.35)
        # Exact match, token sort ratio, or nickname
        if clean_target_name == clean_c_name:
            name_score = 1.0
        else:
            token_ratio = fuzz.token_sort_ratio(clean_target_name, clean_c_name) / 100.0
            set_ratio = fuzz.token_set_ratio(clean_target_name, clean_c_name) / 100.0
            name_score = max(token_ratio, set_ratio)

        # 2. EmploymentCorroboration (0.30)
        # Number of independent source types tying this person to this company and title.
        # Two or more independent sources earn full credit (1.0).
        if c.independent_sources_count >= 2:
            corrob_score = 1.0
        elif c.source_type in ["team_page", "press_release", "wikidata"]:
            corrob_score = 0.85
        elif c.source_type in ["linkedin_snippet", "speaker_bio", "interview"]:
            corrob_score = 0.70
        elif c.company_raw and c.company_raw != "Unknown Company":
            corrob_score = 0.55
        else:
            corrob_score = 0.15

        # 3. HintMatch (0.20)
        # Baseline neutral: 0.50 if no hints
        hint_score = 0.50
        matched_points = 0
        total_checks = 0

        # Check company hint
        if company_hint:
            total_checks += 2
            if company_hint in clean_c_comp or clean_c_comp in company_hint:
                matched_points += 2
            elif fuzz.token_sort_ratio(company_hint, clean_c_comp) >= 80:
                matched_points += 1.8

        # Check city / location hint
        if city_hint:
            total_checks += 1
            c_loc = (c.location or "").lower()
            if city_hint in c_loc or c_loc in city_hint:
                matched_points += 1

        # Check role / title hint
        if role_hint:
            total_checks += 1
            c_title_clean = (c.title_raw or "").lower()
            if role_hint in c_title_clean or c_title_clean in role_hint:
                matched_points += 1

        # Check user clarification answer history
        if answer_text:
            total_checks += 2
            if clean_c_comp in answer_text or answer_text in clean_c_comp:
                matched_points += 2
            elif (c.location or "").lower() in answer_text:
                matched_points += 1

        if total_checks > 0:
            hint_score = min(1.0, max(0.10, matched_points / total_checks))

        # 4. Recency (0.15)
        # Check snippet/title text for former or current signals
        snippet_context = f"{getattr(c, 'snippet_text', '')} {c.title_raw} {c.company_raw}".strip()
        recency_score = _detect_recency_signal(snippet_context)
        if is_ended_role(c.title_raw, c.company_raw, getattr(c, "snippet_text", "")):
            recency_score = 0.10
            c.is_current = False

        # Base weighted score before ambiguity penalty
        base_score = (
            0.35 * name_score +
            0.30 * corrob_score +
            0.20 * hint_score +
            0.15 * recency_score
        )

        c.name_match_score = round(name_score, 3)
        c.employment_corroboration = round(corrob_score, 3)
        c.hint_match_score = round(hint_score, 3)
        c.recency_score = round(recency_score, 3)
        c.final_score = round(base_score, 3)

    # Filter ended roles if active candidates exist
    active_pool = [
        c for c in candidates
        if c.is_current and not is_ended_role(c.title_raw, c.company_raw, getattr(c, "snippet_text", ""))
    ]
    if active_pool:
        candidates = active_pool

    # Sort candidates by final_score descending
    candidates.sort(key=lambda x: x.final_score, reverse=True)
    best = candidates[0]

    # Ambiguity Separation Penalty (mirrors S1)
    # If runner-up has a DIFFERENT company and trails closely (< 0.15 difference),
    # apply separation penalty to pull confidence below threshold.
    ambiguity_factor = 1.0
    if len(candidates) > 1:
        # Find runner-up with distinct company
        best_comp_clean = _clean_name(best.company_raw)
        runner_ups = [c for c in candidates[1:] if _clean_name(c.company_raw) != best_comp_clean]
        if runner_ups:
            diff = best.final_score - runner_ups[0].final_score
            if diff < 0.15:
                ambiguity_factor = max(0.65, 0.75 + (diff / 0.15) * 0.25)
                best.final_score = round(best.final_score * ambiguity_factor, 3)

    best.ambiguity_factor = round(ambiguity_factor, 3)
    confidence = min(0.99, max(0.05, best.final_score))

    # Gate: >= 0.80 auto-confirmed, else clarification required
    is_confirmed = (confidence >= S1_CONFIDENCE_THRESHOLD) and (best.company_raw != "Unknown Company")

    return candidates[:8], best, confidence, is_confirmed

def generate_person_clarification_questions(candidates: List[PersonCandidate]) -> List[str]:
    """Generates clarifying question to separate ambiguous person candidates."""
    companies = list(dict.fromkeys([c.company_raw for c in candidates if c.company_raw and c.company_raw != "Unknown Company"]))
    if len(companies) >= 2:
        return [f"Which company does this person currently work for? (e.g. {', '.join(companies[:3])})"]
    titles = list(dict.fromkeys([c.title_raw for c in candidates if c.title_raw]))
    if len(titles) >= 2:
        return [f"What is their current role or department? (e.g. {', '.join(titles[:2])})"]
    return ["Please provide their company domain, city, or current job title to confirm their identity."]

async def resolve_person(person_name: str, hints: Optional[Dict[str, Any]] = None) -> Tuple[PersonProfile, bool]:
    """
    Main entry point for S0: Person Resolution.
    Returns: (PersonProfile, is_confirmed)
    """
    candidates = await discover_person_candidates(person_name, hints)
    scored_candidates, best, confidence, is_confirmed = score_person_candidates(candidates, person_name, hints)

    # Filter out ended roles from alternatives so SDR clarification cards never show ended roles
    active_alternatives = [
        c for c in scored_candidates
        if c.is_current and not is_ended_role(c.title_raw, c.company_raw, getattr(c, "snippet_text", ""))
    ]
    alternatives_to_show = active_alternatives[:8] if active_alternatives else scored_candidates[:8]

    # Ensure ALL candidate alternatives have accurate normalized functions and seniorities
    for cand in alternatives_to_show:
        if not cand.function or not cand.seniority:
            c_norm = await normalize_person_role(cand.title_raw)
            cand.function = c_norm["function"]
            cand.seniority = c_norm["seniority"]
            cand.title_normalized = c_norm.get("title_normalized", cand.title_raw)

    # Normalize role for the winning candidate
    norm_role = await normalize_person_role(best.title_raw)

    profile = PersonProfile(
        name=best.name,
        first_name=best.first_name or _extract_first_name(best.name),
        company_raw=best.company_raw,
        title_raw=best.title_raw,
        title_normalized=norm_role.get("title_normalized", best.title_raw),
        function=norm_role.get("function", "Executive/GM"),
        seniority=norm_role.get("seniority", "C-level"),
        location=best.location,
        evidence_urls=best.evidence_urls or ([best.source_url] if best.source_url else []),
        confidence=confidence,
        role_source="web",
        role_confidence=norm_role.get("role_confidence", 0.80),
        as_of_date=time.strftime("%Y-%m-%d"),
        alternatives=alternatives_to_show,
        clarification_questions=generate_person_clarification_questions(alternatives_to_show)
    )

    return profile, is_confirmed
