import os
import re
import difflib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import yaml

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

ROLES_CONFIG_PATH = Path(__file__).resolve().parent / "roles.yaml"

# Global cache for roles config
_ROLES_DATA: Optional[Dict[str, Any]] = None

def load_roles_config() -> Dict[str, Any]:
    global _ROLES_DATA
    if _ROLES_DATA is not None:
        return _ROLES_DATA

    if not ROLES_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Roles configuration not found at {ROLES_CONFIG_PATH}")

    with open(ROLES_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "roles" not in data:
        raise ValueError("Invalid roles configuration: missing 'roles' list.")

    _ROLES_DATA = data
    return _ROLES_DATA

# Canonical lens synonyms mapping
CANONICAL_LENS_MAP = {
    "finance ops": "finance ops",
    "finance_ops": "finance ops",
    "finance": "finance ops",
    "billing": "finance ops",
    "procurement": "procurement",
    "procurement_ops": "procurement",
    "sourcing": "procurement",
    "supply chain and logistics": "supply chain and logistics",
    "supply_chain_logistics": "supply chain and logistics",
    "supply_chain": "supply chain and logistics",
    "fulfillment_ops": "supply chain and logistics",
    "logistics": "supply chain and logistics",
    "hr and recruiting": "HR and recruiting",
    "hr_and_recruiting": "HR and recruiting",
    "hr_ops": "HR and recruiting",
    "recruiting": "HR and recruiting",
    "people": "HR and recruiting",
    "customer support": "customer support",
    "customer_support": "customer support",
    "support": "customer support",
    "cx": "customer support",
    "sales and gtm ops": "sales and GTM ops",
    "sales_and_gtm_ops": "sales and GTM ops",
    "sales_ops": "sales and GTM ops",
    "revops": "sales and GTM ops",
    "gtm": "sales and GTM ops",
    "compliance and kyc": "compliance and KYC",
    "compliance_and_kyc": "compliance and KYC",
    "compliance_kyc": "compliance and KYC",
    "compliance": "compliance and KYC",
    "kyc": "compliance and KYC",
    "risk": "compliance and KYC",
    "it ops": "IT ops",
    "it_ops": "IT ops",
    "it": "IT ops",
    "engineering": "IT ops",
    "legal and contracts": "legal and contracts",
    "legal_and_contracts": "legal and contracts",
    "legal": "legal and contracts",
    "contracts": "legal and contracts",
    "data and reporting": "data and reporting",
    "data_and_reporting": "data and reporting",
    "data": "data and reporting",
    "analytics": "data and reporting",
    "bi": "data and reporting",
    "claims and case handling": "claims and case handling",
    "claims_and_case_handling": "claims and case handling",
    "claims": "claims and case handling",
    "broad (neutral weights)": "broad (neutral weights)",
    "broad": "broad (neutral weights)",
    "operations": "broad (neutral weights)",
    "general": "broad (neutral weights)"
}

def canonical_lens(lens_str: Optional[str]) -> str:
    if not lens_str:
        return "broad (neutral weights)"
    clean = re.sub(r'[\s_\-]+', ' ', lens_str.strip().lower())
    clean_snake = clean.replace(' ', '_')
    if clean in CANONICAL_LENS_MAP:
        return CANONICAL_LENS_MAP[clean]
    if clean_snake in CANONICAL_LENS_MAP:
        return CANONICAL_LENS_MAP[clean_snake]
    
    # Partial token checks
    for k, v in CANONICAL_LENS_MAP.items():
        if k in clean:
            return v
    return lens_str.strip()

def detect_seniority(title: str) -> str:
    """
    Detects seniority from keywords:
    - c_level_or_vp: outcomes, risk, scale, cost
    - director_or_head: process and team capacity
    - manager_or_ic: workflow detail and day-to-day pain
    """
    tl = title.lower()
    # Check C-level / VP
    c_vp_patterns = [
        r'\bchief\b', r'\bcfo\b', r'\bcro\b', r'\bcpo\b', r'\bchro\b',
        r'\bcio\b', r'\bcto\b', r'\bcoo\b', r'\bceo\b', r'\bclo\b', r'\bcdo\b',
        r'\bvp\b', r'\bv\.p\.\b', r'\bvice president\b', r'\bpresident\b',
        r'\bfounder\b', r'\bco-founder\b', r'\bpartner\b', r'\bgeneral counsel\b',
        r'\bmlro\b'
    ]
    for pat in c_vp_patterns:
        if re.search(pat, tl):
            return "c_level_or_vp"

    # Check Director / Head
    dir_head_patterns = [
        r'\bhead\b', r'\bdirector\b', r'\bcontroller\b', r'\blead\b', r'\bprincipal\b'
    ]
    for pat in dir_head_patterns:
        if re.search(pat, tl):
            return "director_or_head"

    # Check Manager / IC
    mgr_ic_patterns = [
        r'\bmanager\b', r'\banalyst\b', r'\bspecialist\b', r'\bcoordinator\b',
        r'\badministrator\b', r'\bassociate\b', r'\bengineer\b', r'\brepresentative\b',
        r'\brep\b', r'\bexecutive\b', r'\bofficer\b'
    ]
    for pat in mgr_ic_patterns:
        if re.search(pat, tl):
            return "manager_or_ic"

    return "director_or_head"

def get_framing_guidance(seniority: str, cares_about: str) -> str:
    cfg = load_roles_config()
    framing_map = cfg.get("seniority_framing", {
        "c_level_or_vp": "outcomes, risk, scale, cost",
        "director_or_head": "process and team capacity",
        "manager_or_ic": "workflow detail and day-to-day pain"
    })
    level_framing = framing_map.get(seniority, "process and team capacity")
    return f"Frame for seniority level ({level_framing}) and core priorities: {cares_about}."

def clean_title_string(title: str) -> str:
    # Lowercase and strip punctuation
    cleaned = re.sub(r'[^\w\s]', ' ', title.lower())
    return " ".join(cleaned.split())

def match_role_in_config(cleaned_title: str) -> Optional[Dict[str, Any]]:
    """
    Attempts exact match and fuzzy match (>= 0.85) against all aliases.
    """
    cfg = load_roles_config()
    best_match = None
    highest_ratio = 0.0

    # 1. Exact match against aliases
    for role_entry in cfg.get("roles", []):
        for alias in role_entry.get("aliases", []):
            clean_alias = clean_title_string(alias)
            if cleaned_title == clean_alias:
                return {
                    "matched_role": role_entry["role"],
                    "primary_lens": role_entry["primary_lens"],
                    "adjacent_lenses": role_entry.get("adjacent_lenses", []),
                    "cares_about": role_entry.get("cares_about", ""),
                    "confidence": 1.0,
                    "match_type": "exact"
                }

    # 2. Fuzzy match with threshold >= 0.85
    for role_entry in cfg.get("roles", []):
        for alias in role_entry.get("aliases", []):
            clean_alias = clean_title_string(alias)
            ratio = difflib.SequenceMatcher(None, cleaned_title, clean_alias).ratio()
            # Also check if alias is a prominent substring of title or vice versa
            if clean_alias in cleaned_title and len(clean_alias) > 3:
                sub_ratio = len(clean_alias) / len(cleaned_title)
                ratio = max(ratio, 0.85 + (sub_ratio * 0.1))
            if ratio > highest_ratio:
                highest_ratio = ratio
                best_match = role_entry

    if highest_ratio >= 0.85 and best_match:
        return {
            "matched_role": best_match["role"],
            "primary_lens": best_match["primary_lens"],
            "adjacent_lenses": best_match.get("adjacent_lenses", []),
            "cares_about": best_match.get("cares_about", ""),
            "confidence": round(highest_ratio, 2),
            "match_type": "fuzzy"
        }

    return None

async def call_model_for_role_normalisation(raw_title: str) -> Dict[str, Any]:
    """
    Step 4 fallback: One small model call to map unknown titles to lens and seniority.
    """
    from app.llm.router import call_llm

    cfg = load_roles_config()
    available_lenses = [
        "finance ops", "procurement", "supply chain and logistics",
        "HR and recruiting", "customer support", "sales and GTM ops",
        "compliance and KYC", "IT ops", "legal and contracts",
        "data and reporting", "claims and case handling", "broad (neutral weights)"
    ]

    prompt = f"""You are an expert B2B sales analyst. Normalize the following recipient job title into a business function lens and seniority level.

Title to normalize: "{raw_title}"

Allowed Lenses:
{json_lenses(available_lenses)}

Allowed Seniorities:
- "c_level_or_vp" (C-Suite, VP, Founders, Managing Directors)
- "director_or_head" (Directors, Heads, Controllers, Practice Leads)
- "manager_or_ic" (Managers, Leads, Specialists, Analysts, Individual Contributors)

Return strict JSON with this exact schema:
{{
  "lens": "<one value from Allowed Lenses>",
  "seniority": "<c_level_or_vp | director_or_head | manager_or_ic>",
  "confidence": <float between 0.0 and 1.0>,
  "cares_about": "<concise comma-separated priorities, e.g. Cost, speed, accuracy>"
}}
"""
    try:
        res = await call_llm(
            prompt,
            system_prompt="You normalize enterprise job titles. Return valid JSON only.",
            task_type="fast",
            json_mode=True
        )
        if isinstance(res, dict) and "lens" in res and "confidence" in res:
            return res
    except Exception as e:
        logger.warning(f"Role normalisation model fallback failed: {e}")

    return {
        "lens": "broad (neutral weights)",
        "seniority": detect_seniority(raw_title),
        "confidence": 0.5,
        "cares_about": "Growth, margin, speed, scale"
    }

def json_lenses(lenses: List[str]) -> str:
    return "\n".join([f"- {l}" for l in lenses])

async def normalize_recipient_role(raw_title: Optional[str]) -> Dict[str, Any]:
    """
    Normalizes free-text recipient role according to Spec 4.3:
    1. Lowercase and strip punctuation.
    2. Exact match against alias lists.
    3. Fuzzy match with threshold of ~0.85.
    4. If still unknown, small model call.
    5. If confidence < 0.6, treat as broad with role_unrecognized chip flag.
    """
    if not raw_title or not raw_title.strip():
        return {
            "title": "",
            "lens": "broad (neutral weights)",
            "seniority": "director_or_head",
            "confidence": 1.0,
            "cares_about": "Growth, margin, speed, scale",
            "adjacent_lenses": [],
            "framing_guidance": "Neutral company-wide operational framing.",
            "role_unrecognized": False,
            "role_fit_applied": False
        }

    cleaned = clean_title_string(raw_title)
    seniority = detect_seniority(raw_title)

    # 1 & 2 & 3: Config aliases match
    matched = match_role_in_config(cleaned)
    if matched:
        return {
            "title": raw_title.strip(),
            "lens": canonical_lens(matched["primary_lens"]),
            "seniority": seniority,
            "confidence": matched["confidence"],
            "cares_about": matched["cares_about"],
            "adjacent_lenses": [canonical_lens(a) for a in matched["adjacent_lenses"]],
            "framing_guidance": get_framing_guidance(seniority, matched["cares_about"]),
            "role_unrecognized": False,
            "role_fit_applied": canonical_lens(matched["primary_lens"]) != "broad (neutral weights)"
        }

    # 4: Model fallback
    model_res = await call_model_for_role_normalisation(raw_title)
    conf = float(model_res.get("confidence", 0.5))
    model_lens = canonical_lens(model_res.get("lens", "broad (neutral weights)"))
    model_seniority = model_res.get("seniority") or seniority
    cares_about = model_res.get("cares_about", "Growth, margin, speed, scale")

    # 5: Below 0.6 confidence check or unmapped/broad title
    if conf < 0.6 or model_lens == "broad (neutral weights)":
        return {
            "title": raw_title.strip(),
            "lens": "broad (neutral weights)",
            "seniority": model_seniority,
            "confidence": conf,
            "cares_about": "Growth, margin, speed, scale",
            "adjacent_lenses": [],
            "framing_guidance": get_framing_guidance(model_seniority, "Growth, margin, speed, scale"),
            "role_unrecognized": True,
            "role_fit_applied": False
        }

    # Find adjacent lenses for this lens if present in config
    cfg = load_roles_config()
    adj = []
    for r in cfg.get("roles", []):
        if canonical_lens(r.get("primary_lens")) == model_lens:
            adj = [canonical_lens(a) for a in r.get("adjacent_lenses", [])]
            if not cares_about:
                cares_about = r.get("cares_about", "")
            break

    return {
        "title": raw_title.strip(),
        "lens": model_lens,
        "seniority": model_seniority,
        "confidence": conf,
        "cares_about": cares_about,
        "adjacent_lenses": adj,
        "framing_guidance": get_framing_guidance(model_seniority, cares_about),
        "role_unrecognized": False,
        "role_fit_applied": model_lens != "broad (neutral weights)"
    }

def get_role_fit_multiplier(
    hypothesis_lens: str,
    recipient_lens: str,
    adjacent_lenses: Optional[List[str]] = None
) -> Tuple[float, str]:
    """
    Section 4.4 Re-scoring in S4:
    adjusted_score = base_score x role_fit
    role_fit:
      - primary lens: 1.0 ("primary")
      - adjacent lens: 0.85 ("adjacent")
      - any other lens: 0.60 ("other")
      - broad role: 1.0 for everything ("broad")
    """
    hyp_canon = canonical_lens(hypothesis_lens)
    recip_canon = canonical_lens(recipient_lens)
    adj_canons = [canonical_lens(a) for a in (adjacent_lenses or [])]

    if recip_canon == "broad (neutral weights)" or not recipient_lens:
        return 1.0, "broad"

    if hyp_canon == recip_canon:
        return 1.0, "primary"

    if hyp_canon in adj_canons:
        return 0.85, "adjacent"

    return 0.60, "other"

def suggest_roles_for_lens(problem_lens: str) -> List[str]:
    """
    Section 4.4 Better-fit hint:
    When fallback banner shows, suggest roles whose primary lens matches
    the top company-level problem, using the same table in reverse.
    """
    p_canon = canonical_lens(problem_lens)
    cfg = load_roles_config()
    suggested = []
    for r in cfg.get("roles", []):
        if canonical_lens(r.get("primary_lens")) == p_canon:
            # Pick the clean first 2-3 aliases or role name
            aliases = r.get("aliases", [])
            for a in aliases[:3]:
                if len(a) > 2 and a.title() not in suggested:
                    suggested.append(a.title())
            if not suggested:
                suggested.append(r.get("role"))
    return suggested


# --- Tier 3 Person-First Normalization & Function Taxonomy ---

ROLE_MAP_PATH = Path(__file__).resolve().parent / "role_map.yaml"
_ROLE_MAP_DATA: Optional[Dict[str, Any]] = None

def load_role_map_config() -> Dict[str, Any]:
    global _ROLE_MAP_DATA
    if _ROLE_MAP_DATA is not None:
        return _ROLE_MAP_DATA

    if not ROLE_MAP_PATH.exists():
        raise FileNotFoundError(f"Role map config not found at {ROLE_MAP_PATH}")

    with open(ROLE_MAP_PATH, "r", encoding="utf-8") as f:
        _ROLE_MAP_DATA = yaml.safe_load(f) or {}
    return _ROLE_MAP_DATA

def detect_person_seniority(title: str) -> str:
    """Classifies job title into C-level, VP/Head, Director, Manager, IC, or Student."""
    t_clean = re.sub(r'[^a-zA-Z0-9\s/&-]', ' ', (title or "").lower())
    words = set(t_clean.split())

    # Explicit student / intern / trainee
    if any(k in words or k in t_clean for k in ["student", "intern", "trainee", "apprentice", "resident", "fellow", "scholar", "undergraduate", "postgraduate"]):
        return "Student" if "student" in t_clean else "IC"

    # Explicit rule: Chief of Staff is Director-level leverage
    if "chief of staff" in t_clean:
        return "Director"

    # Explicit C-suite / Founder (use exact word match for short acronyms to avoid 'cto' matching 'director')
    c_words = {"chief", "ceo", "cfo", "cto", "coo", "cpo", "cro", "chro", "cio", "cmo", "cso", "cdo", "founder", "president"}
    c_phrases = ["chief executive", "chief operating", "chief financial", "chief technology", "chief product", "chief revenue", "chief people", "chief compliance", "general counsel", "co founder", "co-founder"]
    if any(w in words for w in c_words) or any(p in t_clean for p in c_phrases):
        return "C-level"
    # VP / Head
    if any(k in t_clean for k in ["vice president", "vp", "head of", "svp", "evp"]) or "head" in words:
        return "VP/Head"
    # Director / Controller / Lead / Founding employee
    if any(k in words or k in t_clean for k in ["director", "controller", "comptroller", "lead", "principal", "founding"]):
        return "Director"
    # Manager
    if any(k in words or k in t_clean for k in ["manager", "supervisor", "team lead"]):
        return "Manager"
    # IC
    return "IC"

async def normalize_person_role(raw_title: Optional[str]) -> Dict[str, Any]:
    """
    Person-First role normalizer (Section 3):
    Maps job titles into:
    - title_normalized
    - function (one of 10 taxonomy functions)
    - seniority (C-level, VP/Head, Director, Manager, IC, Student)
    - adjacent_functions
    - pain_categories
    - role_confidence
    """
    if not raw_title or not raw_title.strip():
        return {
            "title_raw": "",
            "title_normalized": "Executive / Business Leader",
            "function": "Executive/GM",
            "seniority": "C-level",
            "role_confidence": 0.5,
            "adjacent_functions": ["Operations", "Finance/Accounting"],
            "pain_categories": ["scaling strain", "operational efficiency"],
            "cares_about": "Enterprise growth, operational margins, scaling strain"
        }

    raw = raw_title.strip()
    clean = re.sub(r'[^a-zA-Z0-9\s/&-]', ' ', raw.lower()).strip()
    words = set(clean.split())
    seniority = detect_person_seniority(raw)
    role_map = load_role_map_config().get("functions", {})

    # 0. Deterministic overrides for special roles (Academic, Student, Merchandising, PLG)
    if any(k in words or k in clean for k in ["student", "undergraduate", "postgraduate", "phd candidate", "medical student"]):
        return {
            "title_raw": raw,
            "title_normalized": "Student",
            "function": "Academic/Student",
            "seniority": "Student",
            "role_confidence": 0.95,
            "adjacent_functions": ["Operations"],
            "pain_categories": [],
            "cares_about": "Academic curriculum, clinical training and research"
        }
    if "intern" in words or "intern" in clean:
        return {
            "title_raw": raw,
            "title_normalized": "Intern",
            "function": "Academic/Student",
            "seniority": "IC",
            "role_confidence": 0.90,
            "adjacent_functions": ["Operations"],
            "pain_categories": [],
            "cares_about": "Internship experience and skill building"
        }
    if any(m in clean for m in ["merchandiser", "merchandising"]):
        func_meta = role_map.get("Supply Chain/Logistics", {})
        return {
            "title_raw": raw,
            "title_normalized": raw.title() if "merchandiser" in clean else "Merchandiser",
            "function": "Supply Chain/Logistics",
            "seniority": seniority if seniority != "C-level" else "IC",
            "role_confidence": 0.92,
            "adjacent_functions": func_meta.get("adjacent_functions", ["Operations"]),
            "pain_categories": func_meta.get("pain_categories", []),
            "cares_about": func_meta.get("cares_about", "Order fulfillment, buyer communication, supplier and fabric schedules")
        }
    if "product led growth" in clean or "plg" in words or "founding product" in clean:
        func_meta = role_map.get("Product", {})
        return {
            "title_raw": raw,
            "title_normalized": raw.title() if "product led growth" in clean else "Founding Product Led Growth",
            "function": "Product",
            "seniority": seniority if seniority != "C-level" else "Director",
            "role_confidence": 0.95,
            "adjacent_functions": func_meta.get("adjacent_functions", ["Sales/Growth/Marketing", "Operations"]),
            "pain_categories": func_meta.get("pain_categories", []),
            "cares_about": func_meta.get("cares_about", "User onboarding, conversion funnels, product-led loops and adoption")
        }

    # 1. Explicit keyword matching against function definitions
    best_func = None
    best_score = 0.0
    for func_name, func_data in role_map.items():
        for kw in func_data.get("keywords", []):
            if kw == clean:
                best_func = func_name
                best_score = 1.0
                break
            elif kw in clean or clean in kw:
                score = 0.85
                if score > best_score:
                    best_score = score
                    best_func = func_name
        if best_score == 1.0:
            break

    # 2. Fuzzy match across keywords
    if not best_func or best_score < 0.80:
        for func_name, func_data in role_map.items():
            for kw in func_data.get("keywords", []):
                r = difflib.SequenceMatcher(None, clean, kw).ratio()
                if r >= 0.85 and r > best_score:
                    best_score = r
                    best_func = func_name

    # 3. LLM fallback if still unmapped
    if not best_func or best_score < 0.60:
        try:
            import json as _json
            from app.llm.router import call_llm
            allowed_funcs = list(role_map.keys())
            prompt = f"""Normalize this person's job title into one business function and seniority.
Title: "{raw}"
Allowed Functions: {_json.dumps(allowed_funcs)}
Allowed Seniorities: ["C-level", "VP/Head", "Director", "Manager", "IC"]

Output strict JSON:
{{
  "function": "<one Allowed Function>",
  "seniority": "<one Allowed Seniority>",
  "title_normalized": "<clean standardized title>",
  "confidence": <float 0.0-1.0>
}}"""
            res = await call_llm(prompt, system_prompt="Normalize job titles accurately. Output JSON only.", task_type="fast", json_mode=True)
            if isinstance(res, dict) and res.get("function") in allowed_funcs:
                best_func = res.get("function")
                seniority = res.get("seniority") or seniority
                best_score = float(res.get("confidence", 0.75))
        except Exception:
            pass

    if not best_func:
        best_func = "Executive/GM"
        best_score = 0.50

    func_meta = role_map.get(best_func, {})
    title_norm = raw.title()
    if best_func == "Executive/GM" and ("ceo" in clean or "chief executive" in clean):
        title_norm = "Chief Executive Officer (CEO)"
    elif best_func == "Finance/Accounting" and ("cfo" in clean or "chief financial" in clean):
        title_norm = "Chief Financial Officer (CFO)"
    elif best_func == "Engineering/IT" and ("cto" in clean or "chief tech" in clean):
        title_norm = "Chief Technology Officer (CTO)"
    elif best_func == "Customer Support/CX" and ("head of support" in clean or "cx lead" in clean):
        title_norm = "Head of Customer Support"

    return {
        "title_raw": raw,
        "title_normalized": title_norm,
        "function": best_func,
        "seniority": seniority,
        "role_confidence": round(best_score, 2),
        "adjacent_functions": func_meta.get("adjacent_functions", []),
        "pain_categories": func_meta.get("pain_categories", []),
        "cares_about": func_meta.get("cares_about", "")
    }

def get_person_role_fit_multiplier(owner_function: Optional[str], person_function: Optional[str], hypothesis_text: str = "") -> Tuple[float, str]:
    """
    Deterministic Role Fit Multiplier (Section 6 & 7):
    - Direct match (owner_function == person_function): 1.0 ('HIGH')
    - Adjacent function: 0.75 ('ADJACENT')
    - Executive person: any function passes, 0.80 ('HIGH/ADJACENT' with scaling bonus up to 1.0)
    - Distant function: 0.40 ('LOW')
    """
    if not person_function or person_function in ["broad", "broad (neutral weights)"]:
        return 1.0, "HIGH"

    owner = (owner_function or "").strip()
    person = person_function.strip()

    # Direct match
    if owner and owner.lower() == person.lower():
        return 1.0, "HIGH"

    # Executive person handling
    if person == "Executive/GM":
        scaling_words = ["scale", "scaling", "growth", "margin", "margin pressure", "capacity", "cost", "hiring"]
        if any(w in (hypothesis_text or "").lower() for w in scaling_words):
            return 1.0, "HIGH"
        return 0.80, "HIGH"

    # Adjacent check
    role_map = load_role_map_config().get("functions", {})
    adjacents = role_map.get(person, {}).get("adjacent_functions", [])
    if owner in adjacents or any(adj.lower() == owner.lower() for adj in adjacents):
        return 0.75, "ADJACENT"

    return 0.40, "LOW"
