import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "outreach.db"))

# API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# LLM Models
# Fast model for S1, S5, S6, S7
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b")
# Context-heavy model for S2 extraction, S3 problem discovery
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Pipeline Configuration
S1_CONFIDENCE_THRESHOLD = 0.80
LLM_FAST_TIMEOUT_SECONDS = 25.0
LLM_LARGE_TIMEOUT_SECONDS = 40.0

# Aggregator & Directory Domains (Quarantined to prevent entity poisoning)
AGGREGATOR_DOMAINS = {
    "tavily.com", "leadiq.com", "zoominfo.com", "crunchbase.com", "pitchbook.com",
    "wikipedia.org", "wikidata.org", "linkedin.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "g2.com", "capterra.com",
    "trustpilot.com", "glassdoor.com", "indeed.com", "bloomberg.com", "reuters.com",
    "techcrunch.com", "forbes.com", "yahoo.com", "rocketreach.co", "rocketreach.com",
    "tracxn.com", "dnb.com", "owler.com", "craft.co", "signalhire.com",
    "datanyze.com", "lusha.com", "indiamart.com", "tradeindia.com", "justdial.com",
    "zaubacorp.com", "tofler.in", "instafinancials.com", "yellowpages.com", "yelp.com",
    "apollo.io", "cognism.com", "seamless.ai", "zippia.com", "comparably.com",
    "hunter.io", "upcountry.com", "lead411.com", "adapt.io"
}

# Third-Party Lead-Gen & Directory Brands (Blocked from evidence claims & hypotheses)
AGGREGATOR_BRANDS = {
    "rocketreach", "zoominfo", "apollo.io", "leadiq", "lusha", "cognism",
    "seamless.ai", "hunter.io", "tracxn", "owler", "dnb", "zaubacorp",
    "crunchbase", "pitchbook", "glassdoor", "indeed", "indiamart", "tradeindia",
    "justdial", "tofler"
}

# Hypothesis Scoring Weights (from spec section 5)
SCORE_WEIGHTS = {
    "evidence_strength": 0.30,
    "business_impact": 0.25,
    "automatability": 0.20,
    "timeliness": 0.15,
    "buyer_credibility": 0.10,
}

LAYER_MULTIPLIERS = {
    "stated": 1.0,
    "implied": 0.9,
    "inferred": 0.6,
}

# Seller Capability (Pure capability description, no vendor brand name)
DEFAULT_SELLER_CAPABILITY = {
    "offering": "workflow automation agents and systems for document-heavy, exception-prone back-office operations",
    "value_prop": "eliminating manual bottlenecks and multi-day review queues with full human-in-the-loop auditability",
    "sender_name": "Tanishq",
}

# Decisions log table (mirrored in UI Assumptions panel)
ASSUMPTIONS_LOG = [
    {"num": 1, "decision": "Input is a company name, with optional hints (website, country, industry)", "why": "Matches brief; hints reduce disambiguation ambiguity."},
    {"num": 2, "decision": "We are the seller: an AI automation provider for core operations", "why": "Gives pitch a realistic point of view without hard-wiring a single vendor."},
    {"num": 3, "decision": "The process discovers problems independently before designing solutions", "why": "Prevents generic canned template pitches."},
    {"num": 4, "decision": "Hypotheses are strictly categorized: stated, implied, or inferred", "why": "Builds buyer trust: draft may only assert stated/implied facts; inferred are only questions."},
    {"num": 5, "decision": "Public web sources only; no LinkedIn scraping", "why": "Adheres to ToS, eliminates fragility; careers, press, and reviews carry strong operational signals."},
    {"num": 6, "decision": "Human-in-the-loop review before anything sends; system never auto-sends", "why": "Strict requirement from case study brief."},
    {"num": 7, "decision": "Numbers in draft must originate from cited evidence", "why": "Prevents invented metrics and hallucinations."},
    {"num": 8, "decision": "Company must be confirmed before research starts (threshold >= 0.80)", "why": "Prevents researching wrong entities with shared or ambiguous brand names."},
    {"num": 9, "decision": "Free-tier API router with automatic fallbacks and local SQLite caching", "why": "Cost resilience and zero downtime during live interview demo."},
    {"num": 10, "decision": "Provider calls have bounded fast/context timeouts", "why": "Prevents a stalled model request from hanging an outreach run indefinitely."},
    {"num": 14, "decision": "The prospect is a company; the sender may add a recipient title and pasted context", "why": "Keeps scope small while serving the brief's person-level relevance"},
    {"num": 15, "decision": "The system never researches or scrapes individuals; person-level material exists only if the sender pastes it", "why": "Privacy, terms of service, and complexity"},
    {"num": 16, "decision": "The role adjusts ranking and framing, and the unadjusted ranking stays visible", "why": "Transparency and easy explanation"},
    {"num": 17, "decision": "Pasted text is untrusted data and sender-provided evidence, never verified by the system", "why": "Trust and prompt-injection safety"},
]
