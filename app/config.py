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
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", os.getenv("NVIDIA_NIM_API_KEY", "")).strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# LLM Models
# Fast model for S1, S5, S6, S7
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b")
# Context-heavy model for S2 extraction, S3 problem discovery
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# NVIDIA NIM (OpenAI-compatible)
NVIDIA_HEAVY_MODEL = os.getenv("NVIDIA_HEAVY_MODEL", os.getenv("NVIDIA_MODEL", "mistralai/mistral-large-4-1t-a52b")).strip()
NVIDIA_REASONING_MODEL = os.getenv("NVIDIA_REASONING_MODEL", "nvidia/nemotron-3-ultra-550b-a55b").strip()
NVIDIA_LIGHT_MODEL = os.getenv("NVIDIA_LIGHT_MODEL", "nvidia/nemotron-3.5-bolt-e4b").strip()
NVIDIA_MODEL = NVIDIA_HEAVY_MODEL
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()

# Pipeline Configuration
S1_CONFIDENCE_THRESHOLD = 0.80
LLM_FAST_TIMEOUT_SECONDS = 30.0
LLM_LARGE_TIMEOUT_SECONDS = 50.0
# Keep one request in flight by default. This protects free-tier TPM limits when
# S2 research, role normalisation, and later pipeline stages overlap.
LLM_MAX_CONCURRENT_REQUESTS = max(1, int(os.getenv("LLM_MAX_CONCURRENT_REQUESTS", "1")))
# Fast runs prioritise high-signal channels. "deep" mode still uses every
# specialist researcher for a broader investigation.
FAST_RESEARCH_CHANNEL_LIMIT = max(1, int(os.getenv("FAST_RESEARCH_CHANNEL_LIMIT", "5")))

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

# Current product and operating assumptions shown in the UI.
ASSUMPTIONS_LOG = [
    {"num": 1, "decision": "A run can start from a company, a person, or both", "why": "The workflow supports company-led research, person-first discovery, and a person linked to a known employer."},
    {"num": 2, "decision": "Identity confidence is checked before deeper research", "why": "Company and person resolution ask for clarification when confidence is below 0.80, reducing name and employer mix-ups."},
    {"num": 3, "decision": "Person and employer context help resolve each other", "why": "A known employer narrows person matches; a resolved person's company can focus company research."},
    {"num": 4, "decision": "Role or title is optional buyer context", "why": "It can shape problem relevance and draft framing without preventing company-level discovery when omitted."},
    {"num": 5, "decision": "Research uses public company and person sources, without LinkedIn scraping", "why": "Company channels cover operations, news, hiring, incidents, reviews, changelogs and official records; person voice is searched when relevant."},
    {"num": 6, "decision": "Evidence must be relevant to the resolved company or person", "why": "Profile checks and source validation help prevent unrelated namesakes, directory pages, and boilerplate from becoming evidence."},
    {"num": 7, "decision": "Evidence retains its source and support for each claim", "why": "The review can inspect cited pages and excerpts; unsupported or malformed evidence should not be presented as verified fact."},
    {"num": 8, "decision": "Problems may be directly observed or carefully inferred", "why": "Direct complaints and events support stated problems; growth, hiring, or change signals can support qualified hypotheses, not claims of proven pain."},
    {"num": 9, "decision": "Grounding checks evaluate hypotheses before they are used", "why": "Automated checks compare the problem with its cited evidence and target; provider failure is surfaced for human review rather than treated as a successful audit."},
    {"num": 10, "decision": "Problems are ranked on evidence, impact, automation fit, recency and buyer credibility", "why": "A consistent score makes trade-offs visible, while the ranking remains a decision aid rather than proof that a company has a problem."},
    {"num": 11, "decision": "The proposed workflow solution is generated from the selected problem", "why": "Tying the solution and draft to the chosen evidence-backed opportunity reduces generic pitches and topic drift."},
    {"num": 12, "decision": "Model providers have budgets, timeouts, cooldowns and fallbacks", "why": "These controls pace requests and recover from provider capacity surges (e.g. Gemini/Groq overload). If upstream extraction degrades, the system safely falls back to inferred hypotheses rather than risking ungrounded complaints."},
    {"num": 13, "decision": "Drafts are checked and reviewed by a person before use", "why": "Quality checks flag grounding or personalization risks, and the system does not send outreach automatically."},
    {"num": 14, "decision": "Run history and evidence are stored in SQLite", "why": "Local runs persist on the configured filesystem; deployments with ephemeral storage can lose history on restart unless persistent storage is configured."},
    {"num": 15, "decision": "Sender-provided notes are untrusted context", "why": "Pasted material can guide research and personalization, but it is kept distinct from independently verified public evidence."},
]
