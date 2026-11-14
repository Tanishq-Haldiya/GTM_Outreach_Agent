import asyncio
import inspect
import time
import uuid
import re
import json
import logging
from typing import List, Dict, Any, Callable, Optional
from urllib.parse import urlparse

from app.config import AGGREGATOR_DOMAINS, AGGREGATOR_BRANDS
from app.models import EvidenceItem, CompanyIdentity, CompanyProfile
from app.tools.search import search_web
from app.tools.fetch import fetch_page_text
from app.llm.router import call_llm
from app.config import FAST_RESEARCH_CHANNEL_LIMIT
from app.llm.prompts import S2_EXTRACT_SYSTEM, S2_EXTRACT_USER_TEMPLATE

logger = logging.getLogger(__name__)

def compute_source_authority(
    url: str,
    source_type: str,
    reliability_tier: str = "B",
    excerpt: str = "",
    company_domain: str = "",
    signal_type: Optional[str] = None
) -> float:
    """
    Computes a quantitative source authority score between 0.40 and 0.99.
    Combines institutional credibility, platform reputation, excerpt fidelity,
    and claim-type alignment (e.g. user reviews and employee feedback are top authority
    for operational friction, while SEC/filings are top authority for corporate compliance).
    """
    base_scores = {
        "sec_filing": 0.98,
        "compliance": 0.96,
        "status_incident": 0.95,
        "changelog": 0.94,
        "website": 0.92,
        "careers": 0.90,
        "exec_voice": 0.91,
        "news": 0.85,
        "review": 0.82,
        "community": 0.75,
        "employee_voice": 0.75,
        "person_voice": 0.88,
    }
    score = base_scores.get(source_type.lower(), 0.70)
    url_lower = (url or "").lower()
    
    # 1. Authority boosts for high-reputation public institutions and verified platforms
    if any(auth_domain in url_lower for auth_domain in ["sec.gov", "mca.gov.in", "companieshouse.gov.uk", "ftc.gov"]):
        score = max(score, 0.98)
    elif "statuspage.io" in url_lower or "status." in url_lower:
        score = max(score, 0.95)
    elif any(press in url_lower for press in ["bloomberg.com", "reuters.com", "techcrunch.com", "wsj.com", "ft.com", "forbes.com"]):
        score = max(score, 0.88)
    elif any(store in url_lower for store in ["play.google.com", "apps.apple.com", "g2.com", "trustpilot.com", "ambitionbox.com"]):
        score = max(score, 0.84)
    elif "reddit.com" in url_lower:
        score = max(score, 0.76)

    # 2. Claim-type alignment (Finding #4):
    # Customer reviews, employee voice, and user forums are the primary ground-truth
    # authority for friction/complaints; corporate PR sites are low authority for their own friction.
    if signal_type:
        sig_lower = signal_type.lower()
        if any(f in sig_lower for f in ["friction", "outage_downtime", "manual_process"]):
            if source_type in ["review", "community", "employee_voice"]:
                score += 0.06  # Claim alignment boost: customer/employee voice is gold standard for friction
            elif source_type in ["website"]:
                score -= 0.04  # Corporate marketing pages downplay friction
        elif any(c in sig_lower for c in ["compliance_risk", "expansion", "leadership_priority"]):
            if source_type in ["sec_filing", "compliance", "exec_voice", "website"]:
                score += 0.03
            elif source_type in ["community", "review"]:
                score -= 0.04  # Reviews are lower authority for corporate governance/filings

    # 3. First-party company domain affinity boost
    if company_domain:
        stem = company_domain.split(".")[0].lower()
        if stem and stem in url_lower:
            score += 0.03

    # 4. Reliability tier modifier
    tier_mods = {"A": 0.03, "B": 0.0, "C": -0.03}
    score += tier_mods.get(reliability_tier.upper(), 0.0)

    # 5. Excerpt fidelity bonus: concrete excerpts with depth provide stronger grounding
    if excerpt.strip():
        if len(excerpt.strip()) > 80:
            score += 0.02
        elif len(excerpt.strip()) < 25:
            score -= 0.03

    return round(max(0.40, min(0.99, score)), 2)

# Every search is domain-anchored or clean-name keyed to prevent entity leakage while ensuring deep coverage
RESEARCHER_CONFIGS = [
    {
        "name": "official_overview",
        "query": '({domain} OR "{name}") (overview OR business OR operations OR distribution OR platform OR services OR production OR technology OR systems OR software OR ERP OR workflow OR integrations OR tools)',
        "signal": "profile",
        "source_type": "website"
    },
    {
        "name": "hiring_and_operations",
        "query": '({domain} OR "{name}") (careers OR jobs OR hiring OR "open positions") (operations OR coordinator OR analyst OR manager OR specialist OR associate)',
        "signal": "manual_process",
        "source_type": "careers"
    },
    {
        "name": "customer_reviews_and_friction",
        "query": '("{name}" OR {domain}) (reviews OR complaints OR "customer support" OR "customer service" OR delays OR billing OR refund OR Trustpilot OR G2 OR "turnaround time" OR backlog OR delivery OR fulfillment OR onboarding OR downtime)',
        "signal": "friction",
        "source_type": "review"
    },
    {
        "name": "status_and_incidents",
        "query": '({domain} OR "{name}") (statuspage OR "status page" OR incident OR outage OR downtime OR "degraded performance" OR latency OR SLA OR postmortem)',
        "signal": "outage_downtime",
        "source_type": "status_incident"
    },
    {
        "name": "changelogs_and_migrations",
        "query": '({domain} OR "{name}") (changelog OR releases OR "release notes" OR "API v2" OR "API v1" OR deprecated OR migration OR sunset OR "breaking change")',
        "signal": "migration_sunset",
        "source_type": "changelog"
    },
    {
        "name": "executive_voice_and_priorities",
        "query": '("{name}" OR {domain}) (CEO OR COO OR founder OR "earnings call" OR transcript OR podcast OR interview OR keynote) ("operational efficiency" OR priorities OR bottleneck OR strategy OR scale)',
        "signal": "leadership_priority",
        "source_type": "exec_voice"
    },
    {
        "name": "compliance_and_regulatory",
        "query": '({domain} OR "{name}") ("10-K" OR "10-Q" OR compliance OR regulatory OR audit OR "sales tax" OR VAT OR nexus OR GDPR OR "SOC 2" OR filing OR license)',
        "signal": "compliance_risk",
        "source_type": "compliance"
    },
    {
        "name": "news_and_scale",
        "query": '({domain} OR "{name}") (expansion OR restructuring OR revenue OR earnings OR licensing OR acquisition OR announcement OR growth OR headcount OR scale OR volume OR contracts OR bottlenecks OR "supply chain")',
        "signal": "expansion",
        "source_type": "news"
    },
    {
        "name": "employee_voice_and_ops",
        "query": '("{name}" OR {domain}) (site:ambitionbox.com/reviews OR site:glassdoor.com/Reviews OR site:glassdoor.co.in/Reviews OR site:indeed.com/cmp) (reviews OR "cons" OR "workload" OR "manual" OR "process" OR "tools" OR "culture")',
        "signal": "operational_strain",
        "source_type": "employee_voice"
    }
]

def _get_clean_company_name(name: str, domain: Optional[str] = None) -> str:
    """Extracts the primary clean brand name for targeted, high-recall research."""
    name = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', name)
    name = re.sub(r'["\(\)\/]', '', name).strip()

    # If domain stem matches the first word (e.g. domain='matiks.com', name='Matiks Mental Arithmetic Private Limited')
    if domain:
        stem = domain.split('.')[0].lower()
        parts = name.split()
        if parts and parts[0].lower() == stem and len(parts[0]) >= 3:
            return parts[0]

    legal_suffixes = [
        r'\bPrivate Limited\b', r'\bPvt\s+Ltd\b', r'\bPvt\b', r'\bLimited\b', r'\bLtd\b',
        r'\bInc\b', r'\bIncorporated\b', r'\bLLC\b', r'\bCorp\b', r'\bCorporation\b',
        r'\bCo\b', r'\bCompany\b', r'\bHoldings\b', r'\bGroup\b', r'\bEnterprises\b',
        r'\bTechnologies\b', r'\bTechnology\b', r'\bSolutions\b', r'\bServices\b',
        r'\bSoftware\b', r'\bVentures\b', r'\bLabs\b', r'\bStudio\b', r'\bStudios\b',
        r'\bEntertainment\b'
    ]
    cleaned = name
    for pattern in legal_suffixes:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()

    cleaned = re.sub(r'[^\w\s]', '', cleaned).strip()
    return cleaned if len(cleaned) >= 2 else name

# URL path segments that indicate the page is a corporate directory, not an operational signal.
# Evidence from these pages is structural/informational by nature and cannot constitute
# a direct customer complaint — it is at best Tier 2 Inferred evidence.
# Pages with ZERO operational signal — only identity/legal content.
# These are blocked entirely at S2 (never crawled, never enter evidence pool).
_ZERO_SIGNAL_PAGE_PATTERNS = [
    "/contact", "/contact-us", "/contactus",
    "/about", "/about-us", "/aboutus",
    "/team", "/our-team",
    "/privacy", "/privacy-policy",
    "/terms", "/terms-of-service", "/tos",
    "/sitemap",
    "/parking",
    "/address",
]

# Pages with INFERRED-ONLY signal — legitimate operational signals (job postings,
# FAQs, branch scale, press) but cannot support a Direct / Stated hypothesis.
# These flow into S3 Tier 2 (Inferred discovery) but are excluded from Tier 1.
_INFERRED_ONLY_PAGE_PATTERNS = [
    "/careers", "/jobs", "/hiring",
    "/press", "/media", "/news-room", "/newsroom",
    "/faq", "/faqs",
    "/branch", "/branches",
    "/location", "/locations",
    "/helpdesk",
]

# Combined set for backward-compat callers that just need "is this a non-complaint page"
_BOILERPLATE_PAGE_PATTERNS = _ZERO_SIGNAL_PAGE_PATTERNS + _INFERRED_ONLY_PAGE_PATTERNS


def _is_zero_signal_url(url: str) -> bool:
    """
    Returns True if the URL is a purely zero-signal corporate page
    (contact info, legal, about) that should be blocked entirely.
    These pages can NEVER support any hypothesis tier.
    """
    import os
    path = urlparse(url).path.lower().rstrip("/")
    path_no_ext = os.path.splitext(path)[0]
    for pat in _ZERO_SIGNAL_PAGE_PATTERNS:
        if path_no_ext == pat or path_no_ext.endswith(pat):
            return True
        if f"{pat}/" in path_no_ext or path_no_ext.startswith(pat + "/"):
            return True
    return False


def _is_inferred_only_url(url: str) -> bool:
    """
    Returns True if the URL is an inferred-signal-only page
    (careers, FAQ, press, branch listings) that can support Inferred hypotheses
    but must NEVER be used as evidence for a Direct / Stated hypothesis.
    """
    import os
    path = urlparse(url).path.lower().rstrip("/")
    path_no_ext = os.path.splitext(path)[0]
    for pat in _INFERRED_ONLY_PAGE_PATTERNS:
        if path_no_ext == pat or path_no_ext.endswith(pat):
            return True
        if f"{pat}/" in path_no_ext or path_no_ext.startswith(pat + "/"):
            return True
    return False


def _is_boilerplate_url(url: str) -> bool:
    """
    Backward-compatible wrapper: returns True for both zero-signal AND
    inferred-only pages (i.e., any page that cannot be a Direct / Stated source).
    Use _is_zero_signal_url() when you need the stricter block.
    """
    return _is_zero_signal_url(url) or _is_inferred_only_url(url)


def _is_result_relevant_to_entity(r: Dict[str, Any], company: CompanyIdentity) -> bool:
    """
    Enforces specification rule:
    'Every later search is keyed to the confirmed domain. Evidence that mentions
    neither the confirmed domain nor a known alias is rejected, which stops
    evidence about a similarly named company from leaking in.'

    Filtering strategy:
    - Zero-signal pages (contact, about, privacy, terms, sitemap) → BLOCKED entirely.
      They contain no operational signal of any kind.
    - Inferred-signal pages (careers, FAQ, press, branch listings) → ALLOWED through.
      They carry legitimate inferred signals (hiring patterns, FAQ friction, branch scale).
      S3 Tier 1 pre-filter ensures they never produce a Direct / Stated hypothesis.
    """
    url = r.get("url", "").lower()
    title = r.get("title", "").lower()
    snippet = r.get("snippet", "").lower()

    # Hard-block zero-signal pages — no hypothesis tier can use them
    if _is_zero_signal_url(url):
        logger.debug(f"Search result rejected (zero-signal page): {url}")
        return False
    # Inferred-only pages pass through here; S3 Tier 1 pre-filter blocks them from Direct discovery

    domain = company.domain.lower()
    domain_stem = domain.split(".")[0]
    clean_name = _get_clean_company_name(company.name, company.domain).lower()

    # 1. The confirmed domain is the strongest target anchor. Do not use a
    # domain stem on its own: a short brand can also be a common word, job, or
    # product name in an unrelated URL.
    if domain in url:
        return True

    # 1b. A dedicated community is a target anchor when the subreddit segment
    # exactly matches the confirmed domain stem, not merely a substring.
    community_path = f"/r/{domain_stem}/"
    if "reddit.com" in url and (community_path in f"{url}/" or f"/r/{domain_stem}?" in url):
        return True

    # 2. Snippet or title explicitly mentions the confirmed domain
    if domain in snippet or domain in title:
        return True

    # 3. Clean company name tokens check (handles multi-word names like "warner bros", "wells fargo", "goldman sachs")
    name_tokens = [w for w in clean_name.split() if len(w) >= 3]
    has_name_match = False
    if len(name_tokens) >= 2:
        # Require both primary tokens (e.g. "warner" AND "bros")
        if all(tok in title or tok in snippet for tok in name_tokens[:2]):
            has_name_match = True
    elif len(name_tokens) == 1:
        tok = name_tokens[0]
        if tok in title or tok in snippet:
            has_name_match = True

    if not has_name_match:
        return False

    # A one-word name cannot establish identity by itself unless anchored by the URL stem,
    # or the brand token appears as a distinct word in the title/snippet.
    if len(name_tokens) == 1:
        tok = name_tokens[0]
        has_url_stem_anchor = (
            len(domain_stem) >= 3 and (
                f"/{domain_stem}/" in f"{url}/" or
                f".{domain_stem}." in url or
                f"-{domain_stem}-" in url or
                f"/{domain_stem}-" in url or
                f"-{domain_stem}/" in url or
                f"id=com.{domain_stem}" in url or
                f"/{domain_stem}?" in url or
                url.endswith(f"/{domain_stem}")
            )
        )
        has_title_anchor = bool(re.search(rf"\b{re.escape(tok)}\b", title))
        if not (has_url_stem_anchor or has_title_anchor):
            return False

    # Reject generic aggregator landing pages and lead-gen ad copy. This is a
    # source-quality check, independent of any particular company or industry.
    if any(agg in url for agg in AGGREGATOR_DOMAINS):
        agg_ad_flags = [
            "boost outreach", "ai-writer", "connect smarter", "messages' ai-writer",
            "find email", "phone number", "pricing plans", "get contact info",
            "sign up for free", "try for free"
        ]
        if any(flag in snippet for flag in agg_ad_flags):
            return False

    if any(bad in url for bad in ["yellowpages.com", "manta.com"]):
        return False

    return True

def _sanitize_raw_snippet(text: str) -> str:
    """Strip UI chrome, reviewer counts, action buttons, and promo hashtags from raw search snippets."""
    if not text:
        return ""
    # Strip Play Store / review UI noise
    text = re.sub(r"\b\d+\s+people found this review helpful\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bFlag inappropriate\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b", "", text, flags=re.IGNORECASE)
    # Strip social / YouTube promo boilerplate
    text = re.sub(r"🔔\s*Subscribe for daily updates[^\n.]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"#\w+", "", text)
    # Strip Tavily markdown ID dumps
    text = re.sub(r"#\s*[\w\s]+\s+ID:\s*[\w]+\s+Website:[^\n]*\s+Legal name:[^\n]*", "", text, flags=re.IGNORECASE)
    # Collapse multiple spaces and newlines
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def _is_evidence_claim_valid(claim: str, excerpt: str, company: CompanyIdentity, url: Optional[str] = None) -> bool:
    """
    Strict Guardrail: Rejects hallucinated, aggregator-polluted, or entity-mismatched claims.

    Zero-signal pages (contact, about, privacy, terms) are hard-blocked — no hypothesis can cite them.
    Inferred-only pages (careers, FAQ, press) are ALLOWED: they carry legitimate inferred signals.
    S3 Tier 1 pre-filter ensures inferred-only evidence never produces a Direct / Stated hypothesis.
    """
    claim_lower = claim.lower().strip()
    excerpt_lower = excerpt.lower().strip()
    comp_name_lower = company.name.lower().strip()

    # 0. Hard-block zero-signal pages at claim intake (contact, about, privacy, terms, sitemap)
    if url and _is_zero_signal_url(url):
        logger.info(f"Guardrail rejected evidence from zero-signal page ({url}): {claim[:80]}")
        return False
    # Note: inferred-only pages (careers, FAQ, press) pass here — blocked from Tier 1 in S3 instead

    # 1. Reject if claim features a quarantined aggregator/lead-gen vendor
    for brand in AGGREGATOR_BRANDS:
        if brand in claim_lower and brand not in comp_name_lower:
            # Allow employee review citations if discussing verified workplace/operational feedback
            if brand in ["glassdoor", "indeed", "ambitionbox"] and any(w in claim_lower for w in ["employee", "staff", "review", "workload", "overtime", "process", "culture", "manual", "tool", "dispatch", "shift"]):
                continue
            logger.info(f"Guardrail rejected claim citing aggregator brand '{brand}': {claim}")
            return False
        if brand in excerpt_lower and brand not in comp_name_lower:
            if any(term in excerpt_lower for term in ["offers ai", "helps you connect", "find email", "phone number", "powered recommendations"]):
                logger.info(f"Guardrail rejected excerpt citing aggregator promo '{brand}': {excerpt}")
                return False

    # 2. Reject generic outreach vendor or lead-gen marketing phrases
    bad_phrases = [
        "boost outreach with", "ai-writer to help", "connect smarter and faster",
        "find email addresses", "phone numbers and email", "free trial",
        "sign up for free", "pricing plans", "get contact info",
        "subscribe for daily updates", "no resume shortlisting", "off-campus drives",
        "click to subscribe", "subscribe to our channel"
    ]
    if any(phrase in claim_lower or phrase in excerpt_lower for phrase in bad_phrases):
        logger.info(f"Guardrail rejected claim with generic outreach ad phrase: {claim}")
        return False

    # 3. Grounding anchor. A confirmed domain (including a review path carrying
    # it) or an exact dedicated community establishes identity. Multi-word
    # company names may also establish identity through their name tokens.
    # A single-word name is anchored if the URL carries the domain stem,
    # or the clean brand token appears explicitly as a word in the claim/excerpt.
    clean_name = _get_clean_company_name(company.name, company.domain).lower()
    tokens = [tok for tok in clean_name.split() if len(tok) >= 3]
    domain_stem = company.domain.split(".")[0].lower()

    url_anchored = False
    if url:
        url_lower = url.lower()
        is_exact_community = (
            "reddit.com" in url_lower and
            (f"/r/{domain_stem}/" in f"{url_lower}/" or f"/r/{domain_stem}?" in url_lower)
        )
        has_domain_stem_in_url = (
            len(domain_stem) >= 3 and (
                f"/{domain_stem}/" in f"{url_lower}/" or
                f".{domain_stem}." in url_lower or
                f"-{domain_stem}-" in url_lower or
                f"/{domain_stem}-" in url_lower or
                f"-{domain_stem}/" in url_lower or
                f"id=com.{domain_stem}" in url_lower or
                f"/{domain_stem}?" in url_lower or
                f"={domain_stem}&" in url_lower or
                url_lower.endswith(f"/{domain_stem}")
            )
        )
        if company.domain.lower() in url_lower or is_exact_community or has_domain_stem_in_url:
            url_anchored = True

    multiword_name_anchored = (
        len(tokens) >= 2 and
        all(tok in claim_lower or tok in excerpt_lower for tok in tokens[:2])
    )
    singleword_name_anchored = (
        len(tokens) == 1 and
        bool(re.search(rf"\b{re.escape(tokens[0])}\b", f"{claim_lower} {excerpt_lower}"))
    )
    has_anchor = (
        url_anchored or
        company.domain.lower() in claim_lower or company.domain.lower() in excerpt_lower or
        multiword_name_anchored or
        singleword_name_anchored
    )
    if not has_anchor:
        logger.info(f"Guardrail rejected unanchored evidence claim: {claim}")
        return False

    return True

async def _crawl_official_website(
    company: CompanyIdentity,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None
) -> List[EvidenceItem]:
    """Directly crawls the confirmed domain homepage to extract high-confidence Tier A first-party facts.
    Intentionally crawls only the root domain — boilerplate sub-pages (contact, about, careers) are excluded
    because they carry no authentic operational signals and are blocked by _is_evidence_claim_valid anyway.
    """
    items: List[EvidenceItem] = []
    
    # Strict Aggregator Quarantine: NEVER crawl directories, social networks, or lead-gen aggregators
    if any(agg in company.domain.lower() for agg in AGGREGATOR_DOMAINS):
        logger.warning(f"Quarantined aggregator domain '{company.domain}' for {company.name}; skipping direct crawl.")
        return items

    # Only crawl the root homepage — not any sub-pages
    url = f"https://{company.domain}"
    try:
        page_text = await fetch_page_text(url, max_chars=8000)
        if not page_text or len(page_text) < 200:
            return items

        prompt = f"""Target Company: {company.name}
Official URL: {url}
Industry Context: {company.industry or 'Enterprise Technology'}
Official Website Content:
{page_text[:4000]}

Extract 3 to 5 Tier A verified operational facts directly from their official website:
1. Core product capabilities, manufacturing model, or service operations.
2. Scale claims, volume handled, capacity, or customer/distributor segments.
3. Specific workflows supported (e.g. production, inventory, logistics, compliance, reconciliation).
4. Direct integrations, systems, certifications, or facilities mentioned.

STRICT ANTI-HALLUCINATION RULES:
- Only extract facts that describe {company.name} itself.
- Never extract features of third-party tools, directories, or ads.

Output strictly in JSON:
{{
  "evidence": [
    {{
      "claim": "1-sentence factual statement",
      "excerpt": "Verbatim quote from the text",
      "signal_type": "profile | manual_process | tool_stack | expansion | operational_strain",
      "reliability_tier": "A"
    }}
  ]
}}"""
        extracted = await call_llm(
            prompt,
            system_prompt="You are an enterprise research analyst extracting Tier A facts from official website copy.",
            task_type="large_context",
            json_mode=True
        )
        if isinstance(extracted, dict) and "evidence" in extracted:
            for ev in extracted["evidence"]:
                claim = ev.get("claim", "").strip()
                excerpt = ev.get("excerpt", claim)[:300]
                if not claim:
                    continue

                # Enforce evidence claim guardrail with confirmed URL
                if not _is_evidence_claim_valid(claim, excerpt, company, url=url):
                    continue

                item = EvidenceItem(
                    id=f"ev_{uuid.uuid4().hex[:8]}",
                    researcher="official_website",
                    source_type="website",
                    url=url,
                    title=f"{company.name} Official Platform Overview",
                    claim=claim,
                    excerpt=excerpt,
                    signal_type=ev.get("signal_type", "profile"),
                    reliability_tier="A",
                    authority_score=compute_source_authority(url, "website", "A", excerpt, company.domain, signal_type=ev.get("signal_type", "profile")),
                    published_date=None
                )
                items.append(item)
                if on_evidence_found:
                    await on_evidence_found(item)
    except Exception as e:
        logger.warning(f"Direct crawl of {url} warning: {e}")

    return items

async def _run_single_researcher(
    cfg: Dict[str, str],
    company: CompanyIdentity,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None,
    max_results: int = 8,
) -> List[EvidenceItem]:
    """Runs a single researcher task: domain-keyed search -> entity filter -> structured extraction."""
    items: List[EvidenceItem] = []
    clean_name = _get_clean_company_name(company.name, company.domain)
    query = cfg["query"].format(domain=company.domain, name=clean_name)
    
    try:
        raw_results = await asyncio.wait_for(
            search_web(query, max_results=max_results),
            timeout=12.0
        )
        if not raw_results:
            return items

        # Strict entity relevance filter: discard results from other companies with similar names
        relevant_results = [r for r in raw_results if _is_result_relevant_to_entity(r, company)]
        if not relevant_results:
            return items

        # Format snippets for LLM extraction
        snippets = []
        for r in relevant_results[:max_results]:
            # Compact source windows are sufficient for factual extraction and
            # protect per-minute token budgets during a fan-out.
            snippet = (r.get('snippet') or '')[:(600 if max_results > 4 else 360)]
            text = f"Title: {(r.get('title') or '')[:180]}\nURL: {r.get('url')}\nDate: {r.get('published_date')}\nSnippet: {snippet}"
            snippets.append(text)
        snippets_combined = "\n---\n".join(snippets)

        prompt = S2_EXTRACT_USER_TEMPLATE.format(
            company_name=company.name,
            company_domain=company.domain,
            industry=company.industry or "Technology / Business Operations",
            researcher_name=cfg["name"],
            snippets_text=snippets_combined
        )

        extracted = None
        try:
            extracted = await call_llm(prompt, system_prompt=S2_EXTRACT_SYSTEM, task_type="large_context", json_mode=True)
        except Exception as extract_err:
            logger.warning(f"Researcher '{cfg['name']}' LLM extraction failed ({extract_err}); falling back to direct snippet extraction.")

        if isinstance(extracted, dict) and "evidence" in extracted:
            domain_stem = company.domain.split(".")[0]
            clean_name_lower = clean_name.lower()
            for ev in extracted["evidence"]:
                claim = ev.get("claim", "").strip()
                excerpt = ev.get("excerpt", claim)[:300]
                if not claim:
                    continue
                
                ev_url = ev.get("url") or relevant_results[0].get("url", "")

                # Enforce evidence claim guardrail
                if not _is_evidence_claim_valid(claim, excerpt, company, url=ev_url):
                    continue

                # Double-check that extracted item does not reference a conflicting domain
                if ev_url and not any(comp in ev_url.lower() for comp in [domain_stem, company.domain]):
                    if domain_stem not in claim.lower() and clean_name_lower not in claim.lower():
                        continue

                item = EvidenceItem(
                    id=f"ev_{uuid.uuid4().hex[:8]}",
                    researcher=cfg["name"],
                    source_type=cfg["source_type"],
                    url=ev_url,
                    title=ev.get("title") or relevant_results[0].get("title", ""),
                    claim=claim,
                    excerpt=excerpt,
                    signal_type=ev.get("signal_type", cfg["signal"]),
                    reliability_tier=ev.get("reliability_tier", "B"),
                    authority_score=compute_source_authority(ev_url, cfg["source_type"], ev.get("reliability_tier", "B"), excerpt, company.domain, signal_type=ev.get("signal_type", cfg["signal"])),
                    published_date=ev.get("published_date")
                )
                items.append(item)
                if on_evidence_found:
                    await on_evidence_found(item)

        # Resilient Snippet Fallback: If LLM extraction failed or returned 0 items, salvage verified search signals directly
        if not items and relevant_results:
            logger.info(f"Researcher '{cfg['name']}': Generating evidence items directly from {len(relevant_results[:2])} top verified snippets.")
            for r in relevant_results[:2]:
                snip = _sanitize_raw_snippet((r.get("snippet") or "").strip())
                if not snip or len(snip) < 20:
                    continue
                # Preserve clean, sanitized wording.
                claim = snip[:160]
                excerpt = snip[:300]
                r_url = r.get("url") or f"https://{company.domain}"
                if not _is_evidence_claim_valid(claim, excerpt, company, url=r_url):
                    continue
                item = EvidenceItem(
                    id=f"ev_{uuid.uuid4().hex[:8]}",
                    researcher=cfg["name"],
                    source_type=cfg["source_type"],
                    url=r_url,
                    title=r.get("title") or f"{company.name} Research Signal",
                    claim=claim,
                    excerpt=excerpt,
                    signal_type=cfg["signal"],
                    reliability_tier="B",
                    authority_score=compute_source_authority(r_url, cfg["source_type"], "B", excerpt, company.domain, signal_type=cfg["signal"]),
                    published_date=r.get("published_date")
                )
                items.append(item)
                if on_evidence_found:
                    await on_evidence_found(item)

    except Exception as e:
        logger.warning(f"Researcher '{cfg['name']}' unhandled exception: {e}")

    return items


async def _run_batched_researchers(
    configs: List[Dict[str, str]],
    company: CompanyIdentity,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None,
    max_results: int = 4,
) -> List[EvidenceItem]:
    """Search specialist channels independently, then extract all evidence in one LLM call."""
    clean_name = _get_clean_company_name(company.name, company.domain)
    search_results = await asyncio.gather(*[
        search_web(cfg["query"].format(domain=company.domain, name=clean_name), max_results=max_results)
        for cfg in configs
    ], return_exceptions=True)

    source_rows: Dict[str, tuple] = {}
    prompt_rows = []
    for cfg, results in zip(configs, search_results):
        if isinstance(results, Exception):
            logger.warning("Research channel '%s' search failed: %s", cfg["name"], results)
            continue
        relevant = [r for r in (results or []) if _is_result_relevant_to_entity(r, company)]
        for result in relevant[:max_results]:
            source_id = f"src_{len(source_rows) + 1}"
            source_rows[source_id] = (cfg, result)
            prompt_rows.append({
                "source_id": source_id,
                "channel": cfg["name"],
                "title": (result.get("title") or "")[:150],
                "url": result.get("url") or "",
                "date": result.get("published_date"),
                "snippet": (result.get("snippet") or "")[:360],
            })

    if not prompt_rows:
        return []

    prompt = (
        f"Target company: {company.name} ({company.domain})\n"
        f"Industry: {company.industry or 'Business'}\n"
        "Extract concise, verifiable facts from these search results. Return at most one evidence item per source. "
        "Include source_id exactly as given and copy a short verbatim excerpt. Do not infer problems or combine sources. "
        "Skip irrelevant, ambiguous, third-party, or unsupported results.\n\n"
        f"Sources:\n{json.dumps(prompt_rows, ensure_ascii=False)}\n\n"
        'Return JSON: {"evidence":[{"source_id":"src_1","claim":"...","excerpt":"...","signal_type":"profile|manual_process|tool_stack|expansion|friction|outage_downtime|migration_sunset|leadership_priority|compliance_risk","reliability_tier":"A|B|C","published_date":null}]}'
    )
    try:
        extracted = await call_llm(prompt, system_prompt=S2_EXTRACT_SYSTEM, task_type="large_context", json_mode=True)
    except Exception as exc:
        logger.warning("Batched researcher extraction failed; using source snippets: %s", exc)
        extracted = {}

    items: List[EvidenceItem] = []
    seen_sources = set()
    for row in (extracted.get("evidence", []) if isinstance(extracted, dict) else []):
        source_id = row.get("source_id")
        if source_id not in source_rows:
            continue
        cfg, result = source_rows[source_id]
        claim = str(row.get("claim") or "").strip()
        excerpt = str(row.get("excerpt") or "").strip()[:300]
        url = str(result.get("url") or "")
        if not claim or not excerpt or not _is_evidence_claim_valid(claim, excerpt, company, url=url):
            continue
        ev = EvidenceItem(
            id=f"ev_{uuid.uuid4().hex[:8]}", researcher=cfg["name"], source_type=cfg["source_type"],
            url=url, title=str(result.get("title") or "")[:200], claim=claim, excerpt=excerpt,
            signal_type=str(row.get("signal_type") or cfg["signal"]),
            reliability_tier=str(row.get("reliability_tier") or "B"),
            authority_score=compute_source_authority(url, cfg["source_type"], str(row.get("reliability_tier") or "B"), excerpt, company.domain, signal_type=str(row.get("signal_type") or cfg["signal"])),
            published_date=row.get("published_date") or result.get("published_date"),
        )
        items.append(ev)
        seen_sources.add(source_id)

    # If the model is unavailable or omits a result, retain only a few source
    # snippets as explicitly sourced evidence; downstream guards still apply.
    for source_id, (cfg, result) in source_rows.items():
        if source_id in seen_sources:
            continue
        snippet = _sanitize_raw_snippet(str(result.get("snippet") or "").strip())
        url = str(result.get("url") or "")
        claim = snippet[:160]
        if len(snippet) < 30 or not _is_evidence_claim_valid(claim, snippet[:300], company, url=url):
            continue
        items.append(EvidenceItem(
            id=f"ev_{uuid.uuid4().hex[:8]}", researcher=cfg["name"], source_type=cfg["source_type"],
            url=url, title=str(result.get("title") or f"{company.name} Research Signal")[:200],
            claim=claim, excerpt=snippet[:300], signal_type=cfg["signal"], reliability_tier="B",
            authority_score=compute_source_authority(url, cfg["source_type"], "B", snippet, company.domain, signal_type=cfg["signal"]),
            published_date=result.get("published_date"),
        ))
    if on_evidence_found:
        for item in items:
            await on_evidence_found(item)
    return items

async def _run_reddit_chronological_agent(
    company: CompanyIdentity,
    cutoff_months: int = 12,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None
) -> List[EvidenceItem]:
    """
    General Chronological Reddit Intelligence Agent:
    Discovers authentic customer discussions WITHOUT biased/hardcoded keywords.
    Searches recent posts backwards up to a 12-month recency cutoff.
    Extracts genuine operational bottlenecks, manual friction, fulfillment delays, and user challenges.
    """
    items: List[EvidenceItem] = []
    clean_name = _get_clean_company_name(company.name, company.domain)
    sub_name = clean_name.lower().replace(" ", "")

    queries = [
        f"site:reddit.com/r/{sub_name} {clean_name}",
        f"site:reddit.com/r/{sub_name} new",
        f'site:reddit.com "{clean_name}"'
    ]

    raw_results = []
    seen_urls = set()
    for q in queries:
        try:
            results = await search_web(q, max_results=8, time_range="year")
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    raw_results.append(r)
        except Exception as e:
            logger.warning(f"Reddit search warning for '{q}': {e}")

    # Entity relevance filter: discard unrelated subreddits (e.g. r/space, r/boating)
    relevant = [r for r in raw_results if _is_result_relevant_to_entity(r, company)]
    if not relevant:
        return items

    thread_texts = []
    for i, r in enumerate(relevant[:10], 1):
        thread_texts.append(
            f"Thread #{i}:\n"
            f"Title: {r.get('title')}\n"
            f"URL: {r.get('url')}\n"
            f"Date/Recency: {r.get('published_date') or 'Recent'}\n"
            f"Excerpt: {r.get('snippet')}\n"
        )
    threads_combined = "\n---\n".join(thread_texts)

    prompt = f"""Target Company: {company.name} ({company.domain})
Industry Context: {company.industry or 'Technology / Services'}

Recent Reddit Community Discussions (ordered reverse chronologically):
{threads_combined}

TASK FOR GENERAL REDDIT ANALYST AGENT:
Analyze these recent community threads backwards in time.
Extract up to 4 concrete, authentic operational observations, user challenges, or customer friction points.
Look for:
1. Physical fulfillment or reward delivery delays (if applicable).
2. Service, support, or communication bottlenecks.
3. Manual steps, form submissions, or lack of status tracking.
4. Product friction, integration blockers, or unmet user expectations.

STRICT ANTI-HALLUCINATION RULES:
- Only extract issues actually discussed in the snippets above.
- Never invent problems not present in the text.
- Ignore off-topic chatter, simple math problems/puzzles, or generic spam.

Output strictly in JSON:
{{
  "observations": [
    {{
      "claim": "Crisp 1-sentence factual observation about what users are experiencing",
      "excerpt": "Verbatim quote or close excerpt from the thread",
      "url": "Thread URL",
      "signal_type": "friction | fulfillment_ops | manual_process",
      "recency": "active | recent | past"
    }}
  ]
}}"""

    try:
        res = await call_llm(
            prompt,
            system_prompt="You are an objective community intelligence agent analyzing recent Reddit posts in reverse chronological order to identify authentic operational friction.",
            task_type="large_context",
            json_mode=True
        )
        if isinstance(res, dict) and "observations" in res:
            for obs in res["observations"]:
                claim = (obs.get("claim") or "").strip()
                excerpt = (obs.get("excerpt") or claim)[:300]
                if not claim:
                    continue
                url = obs.get("url") or relevant[0].get("url", f"https://reddit.com/r/{sub_name}")
                if not _is_evidence_claim_valid(claim, excerpt, company, url=url):
                    continue
                item = EvidenceItem(
                    id=f"ev_{uuid.uuid4().hex[:8]}",
                    researcher="reddit_community_intelligence",
                    source_type="community",
                    url=url,
                    title=f"Community Signal ({clean_name})",
                    claim=claim,
                    excerpt=excerpt,
                    signal_type=obs.get("signal_type", "friction"),
                    reliability_tier="B",
                    authority_score=compute_source_authority(url, "community", "B", excerpt, company.domain, signal_type=obs.get("signal_type", "friction")),
                    published_date=obs.get("recency")
                )
                items.append(item)
                if on_evidence_found:
                    await on_evidence_found(item)
    except Exception as e:
        logger.warning(f"Reddit Chronological Agent LLM extraction error: {e}")

    # Fallback to direct snippet extraction if LLM failed
    if not items and relevant:
        for r in relevant[:2]:
            snip = (r.get("snippet") or "").strip()
            if not snip or len(snip) < 25:
                continue
            claim = f"{clean_name} community discussion: {snip[:140]}"
            item = EvidenceItem(
                id=f"ev_{uuid.uuid4().hex[:8]}",
                researcher="reddit_community_intelligence",
                source_type="community",
                url=r.get("url", f"https://reddit.com/r/{sub_name}"),
                title=r.get("title", f"{clean_name} Community Discussion"),
                claim=claim,
                excerpt=snip[:300],
                signal_type="friction",
                reliability_tier="C",
                authority_score=compute_source_authority(r.get("url", ""), "community", "C", snip, company.domain, signal_type="friction"),
                published_date=r.get("published_date")
            )
            items.append(item)
            if on_evidence_found:
                await on_evidence_found(item)

    return items

async def build_company_profile(company: CompanyIdentity) -> CompanyProfile:
    """
    Step 1: Profiles the confirmed company:
    - What it does (core offerings and mechanics)
    - Who its consumers / ICP are (e.g. mobile gamers, students, corporate teams, distributors)
    - Business model & operational workflows (monetization, physical rewards, licensing)
    - Trajectory (funding, headcount scale, stage)
    Gathers facts from official site, Wikipedia, Glassdoor, and business knowledge bases.
    """
    clean_name = _get_clean_company_name(company.name, company.domain)
    url = f"https://{company.domain}"

    # Parallel gather: Official site crawl (if not quarantined) + search for Wikipedia, Glassdoor, and overviews
    tasks = []
    
    async def fetch_site():
        if not any(agg in company.domain.lower() for agg in AGGREGATOR_DOMAINS):
            return await fetch_page_text(url, max_chars=6000)
        return ""
    tasks.append(fetch_site())

    profile_query = f'("{clean_name}" OR "{company.domain}") ("what it does" OR overview OR wikipedia OR glassdoor OR "business model")'
    tasks.append(search_web(profile_query, max_results=5))

    trajectory_query = f'("{clean_name}" OR "{company.domain}") (funding OR valuation OR "headcount" OR "employees" OR seed OR "series" OR founded)'
    tasks.append(search_web(trajectory_query, max_results=4))

    site_text, overview_results, trajectory_results = await asyncio.gather(*tasks, return_exceptions=True)

    sources = []
    snippets = []

    if isinstance(site_text, str) and len(site_text) > 100:
        snippets.append(f"Official Website ({url}) Text:\n{site_text[:2500]}")
        sources.append(url)

    if isinstance(overview_results, list):
        for r in overview_results:
            if _is_result_relevant_to_entity(r, company):
                snippets.append(f"- {r.get('title')}: {r.get('snippet')} (URL: {r.get('url')})")
                if r.get('url') and r.get('url') not in sources:
                    sources.append(r.get('url'))

    if isinstance(trajectory_results, list):
        for r in trajectory_results:
            if _is_result_relevant_to_entity(r, company):
                snippets.append(f"- Trajectory/Scale: {r.get('title')}: {r.get('snippet')} (URL: {r.get('url')})")
                if r.get('url') and r.get('url') not in sources:
                    sources.append(r.get('url'))

    combined_corpus = "\n".join(snippets)

    prompt = f"""Target Company: {company.name} ({company.domain})
Industry Context: {company.industry or 'Technology / Services'}
Headquarters: {company.hq or 'Unknown'}

Information from Official Website, Wikipedia, Glassdoor, and Authoritative Sources:
{combined_corpus[:7000]}

Build a concise, highly accurate Company Profile with these 4 dimensions:
1. what_it_does: Clear 1-2 sentence description of their core product/services and operational model.
2. target_consumers: Who their consumers or buyers are (e.g. mobile gamers & math enthusiasts, SMB owners, enterprise finance teams, auto part distributors).
3. business_model: How they monetize and their primary operational flows (e.g., freemium subscription with physical merchandise rewards, B2B SaaS licensing, industrial dealer distribution).
4. trajectory: Scale, headcount trends, recent funding rounds, stage (e.g., Pre-Series A $10M led by General Catalyst, 71 employees with 129% yearly growth).
5. summary: 1-sentence executive overview combining what they do and who they serve.

Output strictly in JSON:
{{
  "summary": "...",
  "what_it_does": "...",
  "target_consumers": "...",
  "business_model": "...",
  "trajectory": "..."
}}"""

    try:
        profile_res = await call_llm(
            prompt,
            system_prompt="You are a senior equity research analyst profiling a target company with zero hallucination.",
            task_type="fast",
            json_mode=True
        )
        if isinstance(profile_res, dict) and "what_it_does" in profile_res:
            return CompanyProfile(
                summary=profile_res.get("summary", f"{company.name} operating at {company.domain}"),
                what_it_does=profile_res.get("what_it_does", ""),
                target_consumers=profile_res.get("target_consumers", ""),
                business_model=profile_res.get("business_model", ""),
                trajectory=profile_res.get("trajectory", ""),
                sources=sources[:5]
            )
    except Exception as e:
        logger.warning(f"Error building company profile for {company.name}: {e}")

    # Fallback profile
    return CompanyProfile(
        summary=f"{company.name} is an active enterprise operating at {company.domain} in {company.industry or 'Technology'}.",
        what_it_does=f"{company.name} provides products and services in {company.industry or 'its core sector'}.",
        target_consumers=f"Commercial clients and end-users of {company.domain}",
        business_model="Digital and operational workflows",
        trajectory=f"Operating at {company.domain}",
        sources=sources[:3]
    )

async def audit_evidence_against_profile(
    candidate_items: List[EvidenceItem],
    profile: CompanyProfile,
    company: CompanyIdentity
) -> List[EvidenceItem]:
    """
    Evidence Relevance Guard Agent:
    Validates candidate evidence against the established Company Profile.
    Rejects:
    1. Items describing third-party aggregator tools or directory platforms.
    2. Items belonging to similarly named companies in unrelated industries.
    3. Generic marketing boilerplate or ungrounded claims.
    Accepts:
    Genuine customer friction (Reddit, reviews), public announcements, hiring trends, trajectory facts.
    """
    if not candidate_items:
        return []

    # Programmatic pre-filter
    valid_candidates = []
    for item in candidate_items:
        if _is_evidence_claim_valid(item.claim, item.excerpt, company):
            valid_candidates.append(item)

    if not valid_candidates:
        return []

    prompt = f"""Target Company: {company.name} ({company.domain})
Verified Company Profile:
- What it does: {profile.what_it_does}
- Target Consumers: {profile.target_consumers}
- Business Model: {profile.business_model}
- Trajectory: {profile.trajectory}

Candidate Evidence Items:
{json.dumps([{"id": it.id, "researcher": it.researcher, "claim": it.claim, "excerpt": it.excerpt, "source": it.url} for it in valid_candidates], indent=2)}

TASK FOR RELEVANCE GUARD AGENT:
Audit each evidence item. Evaluate whether the claim genuinely belongs to {company.name} ({company.domain}) and is relevant to its verified profile, consumer base, hiring, growth trajectory, or customer friction (e.g. Reddit feedback, reward fulfillment, scaling strain).
- REJECT any item about another company, third-party software ad, or irrelevant generic spam.
- ACCEPT authentic facts about {company.name}, its products, its hiring, its customer reviews, or its operational friction.

Output strictly in JSON:
{{
  "evaluations": [
    {{
      "id": "ev_id",
      "verdict": "accept | reject",
      "relevance_reason": "Crisp 1-sentence explanation of why it is relevant or why it was rejected"
    }}
  ]
}}"""

    try:
        guard_res = await call_llm(
            prompt,
            system_prompt="You are a strict Data Integrity and Evidence Relevance Guard Agent.",
            task_type="fast",
            json_mode=True
        )
        if isinstance(guard_res, dict) and "evaluations" in guard_res:
            eval_map = {ev["id"]: ev for ev in guard_res["evaluations"] if "id" in ev}
            audited_items = []
            for it in valid_candidates:
                audit = eval_map.get(it.id)
                if audit and audit.get("verdict", "").lower() == "reject":
                    logger.info(f"Relevance Guard Agent rejected evidence {it.id}: {audit.get('relevance_reason')}")
                    continue
                it.relevance_status = "verified"
                if audit and audit.get("relevance_reason"):
                    it.relevance_reason = audit.get("relevance_reason")
                audited_items.append(it)
            return audited_items
    except Exception as e:
        logger.warning(f"Evidence guard agent evaluation warning: {e}")

    return valid_candidates

async def _run_person_voice_channel(
    person: Any,
    company: CompanyIdentity,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None
) -> List[EvidenceItem]:
    """
    Section 5: Person Voice Channel (source_type="person_voice")
    Searches for public talks, podcasts, bylined articles, or interviews by this person.
    Provides personal grounding hooks for drafting.
    """
    p_name = getattr(person, "name", "") if person else ""
    if not p_name:
        return []

    items: List[EvidenceItem] = []
    queries = [
        f'"{p_name}" site:{company.domain} interview OR podcast OR talk OR article',
        f'"{p_name}" "{company.name}" podcast OR interview OR keynote'
    ]

    for q in queries:
        try:
            res = await search_web(q, max_results=3)
            for r in res:
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                if not snippet or len(snippet) < 30:
                    continue
                # Grounding check: verify person name or company is in title or snippet
                if p_name.lower() in snippet.lower() or p_name.lower() in title.lower():
                    ev_item = EvidenceItem(
                        id=f"ev_{uuid.uuid4().hex[:8]}",
                        researcher="person_voice",
                        source_type="person_voice",
                        url=url,
                        title=title,
                        claim=f"Public statement / interview by {p_name} ({company.name}): {snippet[:140]}",
                        excerpt=snippet[:280],
                        signal_type="leadership_priority",
                        reliability_tier="B",
                        authority_score=compute_source_authority(url, "person_voice", "B", snippet, company.domain, signal_type="leadership_priority")
                    )
                    items.append(ev_item)
                    if on_evidence_found:
                        res = on_evidence_found(ev_item)
                        if inspect.isawaitable(res):
                            await res
                    break
        except Exception as e:
            logger.debug(f"Person voice search query error: {e}")

    return items

async def execute_research_fanout(
    company: CompanyIdentity,
    profile: Optional[CompanyProfile] = None,
    on_evidence_found: Optional[Callable[[EvidenceItem], Any]] = None,
    person_profile: Optional[Any] = None,
    mode: str = "fast",
    on_researcher_event: Optional[Callable[[str, str, int, float], Any]] = None,
) -> List[EvidenceItem]:
    """
    Executes parallel research strictly anchored to the confirmed domain.
    Combines direct official website crawling with specialized domain-locked search channels.
    Uses concurrency throttling (Semaphore) to prevent LLM quota / rate limit exhaustion.
    Then audits all candidates through the Evidence Relevance Guard Agent.
    """
    sem = asyncio.Semaphore(1)
    result_limit = 8 if mode == "deep" else 4

    async def _throttled_researcher(cfg):
        started = time.monotonic()
        if on_researcher_event:
            await on_researcher_event(cfg["name"], "queued", 0, 0.0)
        async with sem:
            if on_researcher_event:
                await on_researcher_event(cfg["name"], "running", 0, 0.0)
            try:
                result = await _run_single_researcher(cfg, company, on_evidence_found, max_results=result_limit)
                return result
            finally:
                if on_researcher_event:
                    await on_researcher_event(cfg["name"], "completed", len(locals().get("result", [])), time.monotonic() - started)

    async def _throttled_call(label, factory):
        started = time.monotonic()
        if on_researcher_event:
            await on_researcher_event(label, "queued", 0, 0.0)
        async with sem:
            if on_researcher_event:
                await on_researcher_event(label, "running", 0, 0.0)
            result = []
            try:
                result = await factory()
                return result
            finally:
                if on_researcher_event:
                    await on_researcher_event(label, "completed", len(result) if isinstance(result, list) else 0, time.monotonic() - started)

    crawl_task = _throttled_call("official_website_crawl", lambda: _crawl_official_website(company, on_evidence_found))
    reddit_task = _throttled_call("reddit_community_search", lambda: _run_reddit_chronological_agent(company, on_evidence_found=on_evidence_found))
    # A fast run is designed to finish within modest free-tier model budgets.
    # The selected channels cover first-party context, hiring/scale, customer
    # friction, and compliance. Deep mode retains the full specialist fan-out.
    fast_channel_names = {
        "hiring_and_operations", "customer_reviews_and_friction",
        "compliance_and_regulatory", "news_and_scale",
        "employee_voice_and_ops",
    }
    selected_configs = RESEARCHER_CONFIGS if mode == "deep" else [
        cfg for cfg in RESEARCHER_CONFIGS if cfg["name"] in fast_channel_names
    ][:FAST_RESEARCH_CHANNEL_LIMIT]
    if mode == "deep":
        researcher_tasks = [_throttled_researcher(cfg) for cfg in selected_configs]
    else:
        researcher_tasks = [_throttled_call(
            "batched_specialist_research",
            lambda: _run_batched_researchers(selected_configs, company, on_evidence_found, result_limit),
        )]

    tasks = [crawl_task, reddit_task] + researcher_tasks
    if person_profile:
        tasks.append(_throttled_call("person_voice_search", lambda: _run_person_voice_channel(person_profile, company, on_evidence_found)))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_evidence: List[EvidenceItem] = []
    
    for res in results:
        if isinstance(res, list):
            all_evidence.extend(res)

    # Fallback anchored to confirmed domain if web signals are sparse
    if len(all_evidence) < 2:
        fallback_item = EvidenceItem(
            id=f"ev_{uuid.uuid4().hex[:8]}",
            researcher="official_website",
            source_type="website",
            url=f"https://{company.domain}",
            title=f"{company.name} Official Overview ({company.domain})",
            claim=f"{company.name} operates at {company.domain} in {company.industry or 'enterprise technology'}.",
            excerpt=f"{company.name} official domain {company.domain} operations and infrastructure.",
            signal_type="profile",
            reliability_tier="A",
            authority_score=0.95
        )
        all_evidence.append(fallback_item)

    # Run through the Evidence Relevance Guard Agent if profile is provided
    if profile:
        verified_evidence = await audit_evidence_against_profile(all_evidence, profile, company)
        return verified_evidence if verified_evidence else all_evidence

    return all_evidence
