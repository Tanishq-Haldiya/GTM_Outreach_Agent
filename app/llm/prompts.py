import json

S1_CLARIFY_SYSTEM = """You are a disambiguation assistant helping a GTM team identify the exact company a user intended to research."""

S1_CLARIFY_USER_TEMPLATE = """We are trying to identify the exact company from user input: "{company_input}".
Here are candidate companies discovered from search and knowledge bases:
{candidates_json}

The confidence score is below our 0.80 threshold because of ambiguity.
Generate 1 or 2 crisp, distinguishing clarifying questions to help the user specify which entity they want (e.g., asking about primary industry, website, or HQ location).

Output strictly in JSON:
{{
  "questions": ["Question 1?", "Question 2?"]
}}"""

S2_EXTRACT_SYSTEM = """You are an expert enterprise research intelligence analyst extracting verified operational facts from raw search snippets."""

S2_EXTRACT_USER_TEMPLATE = """Target Company: {company_name} (Confirmed Official Domain: {company_domain})
Industry Context: {industry}
Focus Area: {researcher_name}

Raw Search Snippets:
{snippets_text}

Extract 2 to 5 high-value, structured evidence items.
STRICT ANTI-HALLUCINATION & RELEVANCE RULES:
1. ONLY extract facts strictly and specifically belonging to {company_name} operating at {company_domain}.
2. ZERO THIRD-PARTY/AGGREGATOR CONTAMINATION:
   NEVER extract features, tools, marketing slogans, or product descriptions of third-party directories, job boards, or aggregators (e.g. RocketReach, Apollo, ZoomInfo, Glassdoor, Indeed, Lusha, LeadIQ, TradeIndia, IndiaMart). For instance, if a snippet states "RocketReach offers AI-powered recommendations...", DO NOT extract that. It describes RocketReach, NOT {company_name}.
3. INDUSTRY ALIGNMENT:
   Facts must match {company_name}'s actual business model ({industry}). If {company_name} is an industrial, manufacturing, or hardware company (e.g. bearings, automotive parts, equipment), extract facts about manufacturing plants, production capacity, distribution networks, supplier relations, certifications, or physical supply chain.
4. If a snippet does not contain concrete facts about {company_name}, return an empty array. DO NOT invent or attribute foreign features to {company_name}.
5. Look for operational cues: rapid hiring in manual teams, customer complaints about wait times or errors, promised rewards / merchandise delivery delays, streak gift fulfillment bottlenecks, customer support ticketing queues (Discord, Reddit, in-app), billing/payment friction, legacy ERP or multi-tool stacks, manual reviews, high transaction volumes.
6. Every claim must be a concise, factual 1-sentence statement describing {company_name}.
7. Excerpt must be an exact quote from the snippet.
8. Reliability tier:
   - "A": First-party site, official filings, press releases
   - "B": Reputable news articles, trade publications
   - "C": User reviews (G2, Trustpilot, Reddit, forums), Glassdoor

Output strictly in JSON:
{{
  "evidence": [
    {{
      "claim": "...",
      "excerpt": "...",
      "url": "...",
      "title": "...",
      "signal_type": "operational_strain | manual_process | tool_stack | expansion | friction",
      "reliability_tier": "A | B | C",
      "published_date": "YYYY-MM-DD or null"
    }}
  ]
}}"""

S3_DISCOVERY_SYSTEM = """You are a senior enterprise operations and B2B workflow consultant diagnosing operational bottlenecks.
MANDATORY REQUIREMENT: You MUST ALWAYS generate a minimum of 3 to 5 distinct operational hypotheses across stated, implied, and inferred layers.
If the collected evidence contains only 1 directly stated customer complaint, you MUST derive 2 to 3 additional implied or inferred hypotheses based on first-principles operational bottlenecks inherent to their business model, scale, and industry (e.g., supply chain order reconciliation, distributor inventory tracking, quality certifications, vendor billing coordination, or regulatory compliance). Never return fewer than 3 hypotheses under any circumstance."""

S3_DISCOVERY_USER_TEMPLATE = """Company: {company_name} (Confirmed Official Domain: {company_domain})
Industry: {industry} | Size Band: {size_band}

Evidence Items Collected:
{evidence_json}

Your job is to uncover 3 to 5 distinct operational problem hypotheses strictly for {company_name} ({company_domain}).

CRITICAL ANTI-HALLUCINATION & INDUSTRY REALISM RULES:
1. STRICT ENTITY & EVIDENCE GROUNDING:
   Every hypothesis must directly pertain to {company_name} ({company_domain}) and its verified business operations.
   NEVER hypothesize problems about third-party directories, aggregator tools, or lead-gen software (e.g. RocketReach, ZoomInfo, Apollo).
2. INDUSTRY & OPERATING MODEL REALISM:
   Hypotheses MUST realistically fit {company_name}'s actual industry ({industry}) and operational reality:
   - For Industrial Goods, Manufacturing, Automotive Parts, Bearings, Hardware, Engineering:
     Hypotheses must strictly relate to physical supply chains, distributor/dealer order reconciliation, raw material supplier lead times, inventory holding vs stockouts, manufacturing plant maintenance scheduling, quality compliance audits, or warranty claim validation.
     STRICTLY PROHIBITED: Hypothesizing software licensing, digital SaaS subscriptions, streaming rights, or AI email writing tools for an industrial goods manufacturer.
   - For Consumer Apps, Gaming, Mobile, EdTech, Reward Platforms:
     Hypotheses must strictly relate to physical rewards / merchandise fulfillment bottlenecks (delayed delivery of streak gifts, t-shirts, hoodies, cakes), address verification errors, user support ticketing queues across Discord/Reddit/in-app, manual courier tracking, cheating/bot mitigation, or payout/coupon reconciliation.
   - For Media & Entertainment: Rights distribution, syndication, multi-territory licensing, streaming metadata.
   - For Fintech & Financial Services: KYC verification, reconciliation across payment rails, chargebacks, fraud dispute queues.
   - For Healthcare: Provider credentialing, claims triage, HIPAA/regulatory audits, clinical scheduling.
   - For B2B Tech / SaaS: Client onboarding queues, CRM-to-ERP sync, ticket triage, usage-based billing audits.
3. PRIORITIZE EXPLICIT USER & COMMUNITY COMPLAINTS:
   If the collected evidence contains direct user/customer complaints from Reddit, community forums, or app reviews (e.g. unfulfilled streak rewards, missing confirmation/coupon emails, delayed physical delivery of milestone gifts like t-shirts, hoodies, or cakes, or manual support backlogs), you MUST create a top-priority "stated" operational hypothesis directly addressing this workflow failure, tied to those specific evidence IDs.

Categories for Layer:
- "stated": High confidence. Company or customers explicitly complain about it (reviews, interviews, filings).
- "implied": Medium confidence. Company behaviour reveals it (hiring 15+ AP specialists or KYC analysts, rapid multi-country expansion, migration between tools).
- "inferred": Lower confidence. First-principles business model friction (e.g. marketplaces naturally have seller disputes/payout delays; manufacturers have distributor reconciliation and inventory strain).

Lenses to consider:
- supply_chain_logistics, procurement, finance_ops, inventory_operations, quality_compliance, customer_support, sales_ops, legal_contracts.

Score each hypothesis from 0.0 to 1.0 across:
- evidence_strength: (1.0 for explicit statement, 0.7 for multiple behavioral signals, 0.4 for single signal, 0.2 for pure inference)
- business_impact: (relevance to cost, speed, revenue, or risk at their scale)
- automatability: (repetitive, document-heavy, rules plus bounded judgment)
- timeliness: (how recent and time-bound the signal is)
- buyer_credibility: (would an executive take this seriously from an external email?)

Output strictly in JSON with at least 3 distinct hypotheses:
{{
  "hypotheses": [
    {{
      "id": "hyp_1",
      "problem": "Clear, specific 1-sentence operational problem statement",
      "lens": "customer_support | finance_ops | etc.",
      "lens_explanation": "1-2 sentences on why this operational lens applies to their business model",
      "layer": "stated",
      "evidence_ids": ["ev_1"],
      "evidence_strength": 0.85,
      "business_impact": 0.85,
      "automatability": 0.8,
      "timeliness": 0.8,
      "buyer_credibility": 0.85,
      "root_cause": "Specific operational cause",
      "workflow_burden": "Manual team friction",
      "automation_fit": "Targeted automation solution",
      "rationale": "Comprehensive explanation"
    }},
    {{
      "id": "hyp_2",
      "problem": "Clear operational problem revealed by organizational scaling or behavior",
      "lens": "operations | compliance_kyc | etc.",
      "lens_explanation": "1-2 sentences on why this operational lens applies to their business model",
      "layer": "implied",
      "evidence_ids": ["ev_2"],
      "evidence_strength": 0.75,
      "business_impact": 0.8,
      "automatability": 0.85,
      "timeliness": 0.75,
      "buyer_credibility": 0.8,
      "root_cause": "Scaling friction cause",
      "workflow_burden": "Internal coordination burden",
      "automation_fit": "Targeted automation solution",
      "rationale": "Comprehensive explanation"
    }},
    {{
      "id": "hyp_3",
      "problem": "Structural first-principles operational bottleneck inherent to their business model",
      "lens": "finance_ops | licensing_contracts | etc.",
      "lens_explanation": "1-2 sentences on why this operational lens applies to their business model",
      "layer": "inferred",
      "evidence_ids": ["ev_1"],
      "evidence_strength": 0.6,
      "business_impact": 0.85,
      "automatability": 0.8,
      "timeliness": 0.7,
      "buyer_credibility": 0.75,
      "root_cause": "Business model complexity cause",
      "workflow_burden": "Manual cross-system overhead",
      "automation_fit": "Targeted automation solution",
      "rationale": "Comprehensive explanation"
    }}
  ]
}}"""

S5_SOLUTION_SYSTEM = """You are a Principal AI Solutions Architect designing targeted process automation for B2B enterprises."""

S5_SOLUTION_USER_TEMPLATE = """Company: {company_name}
Selected Operational Problem:
{problem_statement} (Lens: {lens}, Layer: {layer})
Supporting Hook Evidence:
{hook_evidence}

Recipient Context:
- Target Role/Title: {recipient_title}
- Function Lens: {recipient_lens}
- Seniority Level: {seniority}
- Framing Guidance: {framing_guidance}

Solution Capability Context:
Capability: {seller_offering}
Value Focus: {seller_value_prop}

Design a clean, realistic AI/automation solution sketch.
Rules:
1. Do NOT invent fake customer statistics (e.g. never say "We saved Acme 42% on Day 1").
2. Clearly describe what input is ingested, how AI + human checkpoints process it, and what systems are touched.
3. Align the architecture and buyer credibility hook with the recipient's function lens and seniority.

Output strictly in JSON:
{{
  "process_name": "...",
  "what_it_automates": "...",
  "input_consumed": "...",
  "key_steps": ["Step 1", "Step 2", "Step 3"],
  "human_checkpoints": ["Checkpoint 1", "..."],
  "systems_touched": ["ERP / CRM / Document Store / etc."],
  "impact_direction": "Qualitative or clearly cited efficiency gain",
  "buyer_credibility_hook": "Why the prospect would believe this is solvable now",
  "recommended_persona": "Head of Operations / VP Finance / Chief Risk Officer / etc."
}}"""

S6_DRAFT_SYSTEM = """You are an elite B2B SDR writing hyper-personalized, grounded cold outreach emails that get opened and answered.

CRITICAL — TWO DISTINCT WRITING MODES:

MODE A — DIRECT (layer: "stated" or "implied"):
The problem has been directly observed or strongly evidenced. Lead with the PAIN as a confirmed fact.
Structure: [Company name] + [problem observed] → [why it creates friction] → [capability that solves it] → [assertive CTA to fix a known pain]
Tone: Confident, peer-to-peer, compassionate but direct. You are helping solve something you KNOW is real.

MODE B — INFERRED (layer: "inferred"):
The problem has NOT been directly observed — it is a first-principles inference from an observable signal (e.g., recent growth, hiring surge, expansion). Lead with the SIGNAL as the hook, then bridge to the INFERRED friction as a hypothesis.
Structure: [Company name] + [observable fact you can assert] → [as X scales/grows, Y often emerges] → [capability as a potential solution] → [exploratory CTA — invite conversation, do NOT promise to fix a confirmed pain]
Tone: Consultative, curious, exploratory. You are asking if the pain exists, not asserting it."""

_S6_SHARED_RULES = """STRICT DRAFTING RULES (BOTH MODES):
1. Length: 90 to 130 words maximum.
2. Always explicitly mention {company_name} in the opening hook sentence.
3. Greeting: Use {greeting_target} (e.g., "Hi {recipient_name}," if provided, otherwise "Hi there,").
4. Role Connection (MANDATORY): The draft MUST connect the chosen problem to something this role ({recipient_title}) is responsible for, in exactly one sentence.
5. Role Framing: Align messaging with seniority level ({seniority}):
   - C-level or VP: outcomes, risk, scale, cost.
   - Director or Head: process and team capacity.
   - Manager or IC: workflow detail and day-to-day pain.
   Framing guidance: {framing_guidance}
6. Person-Level Evidence Rules (Tier 2):
   - Any claim about the recipient (their bio, words, posts, talks, or background) MUST strictly cite a sender-provided item.
   - A claim about the person can NEVER be supported by company-level evidence.
   - Quote only short phrases verbatim from the provided text; NEVER invent flattering references such as praise for a talk or award not in the text.
   - If no person-level context is provided or it is too thin, make ZERO person-level claims.
7. No claims about the recipient's internal emotional state (e.g. never say "I know you're stressed" or "you must feel overwhelmed").
8. Absolutely NO invented metrics or made-up percentages. Numbers ONLY from cited evidence.
9. Inferred problems only framed as hypotheses or questions, never stated as confirmed facts.
10. NEVER mention expired seasonal holidays like 'New Year' or 'Christmas' in the email body or subject line; frame streak rewards or contests as recurring 'milestone streaks' or 'reward challenges'.
11. Capability-first: Introduce the solution purely through capability (e.g., "We build automated workflow systems that..." or "We help teams automate..."). Do NOT invent or mention a vendor company brand name.
12. Tone: Peer-to-peer, respectful, zero hype, no buzzwords ("revolutionary", "game-changing", "streamline your operations").
13. Sign-off: Simply "Best,\\n{sender_name}".
14. LinkedIn Note: Under 300 characters for a connection request.
15. SDR why-this-hook note: 2 sentences explaining to the sales rep why this angle was chosen (include whether this is a Direct or Inferred draft and role alignment).

HIGH-CONVERTING SUBJECT LINE RULES (CRITICAL):
- Length: Strictly 2 to 4 words.
- Specificity: Must reference the exact operational initiative, workflow mechanism, or volume metric.
- ZERO EXPIRED SEASONAL/HOLIDAY LABELS: NEVER use expired holiday or seasonal campaign words (e.g. NEVER write "New Year rewards", "holiday promo", "Christmas sale"). Frame as the recurring operational workflow (e.g. "streak reward fulfillment").
- Peer Tone: Must sound like an authentic message from a respected colleague, NOT vendor spam.
- FORBIDDEN: Never write vague, robotic labels like "company transition", "workflow optimization", or "system overview".
- Good Examples: "streak reward fulfillment", "challenge reward status", "question re: WEBTOON rollout", "support load on 35k titles?", "handling transition volume", "state notice backlog?"

Output strictly in JSON:
{{
  "subject": "Primary 2-4 word peer subject line",
  "subject_alternatives": [
    "Alternative angle 1 (2-4 words)",
    "Alternative angle 2 (2-4 words)"
  ],
  "body": "The email draft body",
  "linkedin_note": "Short <300 char LinkedIn note",
  "why_this_hook": "Explanation for the internal SDR team",
  "claim_map": {{
    "Sentence 1...": ["ev_1"]
  }}
}}"""

class RobustPromptTemplate(str):
    """
    String subclass that provides backward-compatible fallback values for format keys
    (e.g., recipient_name, recipient_title, recipient_lens, seniority, framing_guidance)
    when tests or legacy callers only pass target_persona.
    """
    def format(self, *args, **kwargs):
        target = kwargs.get("target_persona") or kwargs.get("recipient_title") or "Operations Leader"
        defaults = {
            "recipient_name": kwargs.get("recipient_name") or "",
            "recipient_title": kwargs.get("recipient_title") or target,
            "recipient_lens": kwargs.get("recipient_lens") or "broad",
            "seniority": kwargs.get("seniority") or "executive",
            "framing_guidance": kwargs.get("framing_guidance") or "Connect to operational priorities and strategic leverage.",
            "greeting_target": kwargs.get("greeting_target") or target,
            "target_persona": target,
        }
        for k, v in defaults.items():
            if k not in kwargs:
                kwargs[k] = v
        return super().format(*args, **kwargs)


S6_DRAFT_USER_TEMPLATE_DIRECT = RobustPromptTemplate(
    "Company: {company_name}\n"
    "Recipient Name: {recipient_name}\n"
    "Recipient Title: {recipient_title}\n"
    "Recipient Lens: {recipient_lens}\n"
    "Seniority Level: {seniority}\n"
    "Framing Guidance: {framing_guidance}\n"
    "Problem (DIRECTLY OBSERVED — state it as confirmed fact): {problem_statement}\n"
    "Hook Evidence (The specific proof you can cite to anchor the opening):\n"
    "{hook_evidence}\n\n"
    "Solution Sketch:\n"
    "{solution_sketch}\n\n"
    "Sender Capability Context:\n"
    "We specialize in: {seller_offering} ({seller_value_prop})\n"
    "Sign-off Name: {sender_name}\n\n"
    "DIRECT DRAFT INSTRUCTIONS:\n"
    "- Open by citing the confirmed problem as a real, observed fact — anchor it in the hook evidence.\n"
    "- Example opening style: \"Noticed [specific thing] at [Company] — sounds like [root friction] is adding real overhead to the team.\"\n"
    "- ONE sentence connecting the chosen problem to something this role ({recipient_title}) is responsible for.\n"
    "- Introduce your capability as a direct solution to this known pain.\n"
    "- CTA: Assertive but low-friction — offer to solve a pain you KNOW is real. E.g., \"Open to comparing notes on how other teams handle this?\"\n\n"
    + _S6_SHARED_RULES
)

S6_DRAFT_USER_TEMPLATE_INFERRED = RobustPromptTemplate(
    "Company: {company_name}\n"
    "Recipient Name: {recipient_name}\n"
    "Recipient Title: {recipient_title}\n"
    "Recipient Lens: {recipient_lens}\n"
    "Seniority Level: {seniority}\n"
    "Framing Guidance: {framing_guidance}\n"
    "Problem (INFERRED — do NOT assert as confirmed, frame as hypothesis): {problem_statement}\n"
    "Observable Signal / Trigger (This is what you can assert as FACT — the hook):\n"
    "{observable_signal}\n"
    "Full Evidence Context:\n"
    "{hook_evidence}\n\n"
    "Solution Sketch:\n"
    "{solution_sketch}\n\n"
    "Sender Capability Context:\n"
    "We specialize in: {seller_offering} ({seller_value_prop})\n"
    "Sign-off Name: {sender_name}\n\n"
    "INFERRED DRAFT INSTRUCTIONS:\n"
    "- Open with the OBSERVABLE SIGNAL as an assertable fact — this is what you actually saw. E.g., \"Saw that [Company] recently [observable fact from signal]...\"\n"
    "- Bridge to the inferred friction using a \"as X scales/grows, Y often emerges\" pattern. E.g., \"As volume grows, [specific operational process] can quietly become a bottleneck...\"\n"
    "- ONE sentence connecting the operational friction to what this role ({recipient_title}) cares about.\n"
    "- Present the inferred problem as a HYPOTHESIS or QUESTION — never assert it as confirmed. E.g., \"...wondering if that's something your team is navigating.\"\n"
    "- Introduce your capability as something that COULD help IF this friction exists.\n"
    "- CTA: Exploratory — invite a conversation to validate the hypothesis, not to close a confirmed pain. E.g., \"Worth a quick chat to compare notes?\"\n"
    "- DO NOT use phrases like \"I know you're facing...\" or \"You clearly have a problem with...\" — that would be a hallucination.\n\n"
    + _S6_SHARED_RULES
)

# Backward-compat alias — referenced by older imports
S6_DRAFT_USER_TEMPLATE = S6_DRAFT_USER_TEMPLATE_DIRECT

S7_CHECK_SYSTEM = """You are a rigorous QA Editor verifying that cold sales copy contains zero hallucinations, is strictly grounded in cited evidence, respects recipient privacy boundaries, and passes the Swap-The-Name test."""

S7_CHECK_USER_TEMPLATE = """Company: {company_name}
Email Subject: {subject}
Email Body:
{body}

Cited Evidence Items:
{evidence_json}

Tasks:
1. Swap-the-name Test: If you replace "{company_name}" with a random competitor and the email still makes complete sense, it FAILS (it's too generic).
2. Grounding Check: Does every assertion or metric actually exist in the cited evidence?
3. Person-Level Evidence Check (CRITICAL):
   - Any claim about the recipient (their bio, background, quotes, talks, or posts) MUST strictly be supported by a sender-provided item (source_type: "sdr_provided" or researcher: "sender_context").
   - A claim about the person can NEVER be supported by company-level evidence.
   - The email must NOT invent flattering references (e.g. praise for a talk, book, or award the text does not explicitly mention).
   - If a person claim is made without sender-provided evidence, flag it as unsupported.
4. Word Count Check: Count words in body (target 90-130).
Note: The sender is pitching an external solution capability to {company_name}. Focus strictly on grounding, lack of hallucinations, and specificity to {company_name}.

Output strictly in JSON:
{{
  "passed_swap_test": true,
  "swap_test_notes": "Why it passes or fails the swap-the-name test",
  "unsupported_claims": [],
  "word_count": 115,
  "invented_numbers_detected": false,
  "verdict": "pass | repair_needed | flagged",
  "repair_suggestion": "ONLY the complete revised email text (starting with Hi... and ending with Best,...) if you made a repair, or empty string. NEVER put commentary, explanations, or critique in this field."
}}"""
