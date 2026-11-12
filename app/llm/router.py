import json
import re
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List
from app.config import (
    GROQ_API_KEY, GROQ_FAST_MODEL, GROQ_FALLBACK_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL,
    LLM_FAST_TIMEOUT_SECONDS, LLM_LARGE_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# Cooldown registry: if a model hits rate limits or quota, cool down for N seconds to avoid stalling
_model_cooldowns: Dict[str, float] = {}

# Multi-key pool support for Groq (supports single key or comma-separated keys: "key1,key2")
_groq_clients = []
_current_groq_idx = 0
_groq_keys = [k.strip() for k in (GROQ_API_KEY or "").split(",") if k.strip()]
if _groq_keys:
    try:
        import groq
        for k in _groq_keys:
            _groq_clients.append(groq.Groq(api_key=k, max_retries=0))
    except Exception as e:
        logger.warning(f"Could not initialize Groq client pool: {e}")

# Multi-key pool support for Gemini
_gemini_clients = []
_current_gemini_idx = 0
_gemini_keys = [k.strip() for k in (GEMINI_API_KEY or "").split(",") if k.strip()]
if _gemini_keys:
    try:
        from google import genai
        from google.genai import types
        for k in _gemini_keys:
            _gemini_clients.append(
                genai.Client(
                    api_key=k,
                    http_options=types.HttpOptions(timeout=int(LLM_LARGE_TIMEOUT_SECONDS * 1000)),
                )
            )
    except Exception as e:
        logger.warning(f"Could not initialize Gemini client pool: {e}")

def _get_groq_client():
    global _current_groq_idx
    if not _groq_clients:
        return None
    return _groq_clients[_current_groq_idx % len(_groq_clients)]

def _rotate_groq_key():
    global _current_groq_idx
    if len(_groq_clients) > 1:
        _current_groq_idx = (_current_groq_idx + 1) % len(_groq_clients)
        logger.info(f"Rotated to next Groq API key in pool (index {_current_groq_idx})")

def _get_gemini_client():
    global _current_gemini_idx
    if not _gemini_clients:
        return None
    return _gemini_clients[_current_gemini_idx % len(_gemini_clients)]

def _rotate_gemini_key():
    global _current_gemini_idx
    if len(_gemini_clients) > 1:
        _current_gemini_idx = (_current_gemini_idx + 1) % len(_gemini_clients)
        logger.info(f"Rotated to next Gemini API key in pool (index {_current_gemini_idx})")

def _clean_json_string(text: str) -> str:
    """Strips markdown code fences and whitespace from model JSON outputs."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

async def call_groq(
    prompt: str,
    system_prompt: str = "You are an expert enterprise research and B2B strategy analyst.",
    model: str = GROQ_FAST_MODEL,
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: int = 450,
    timeout: float = 15.0
) -> str:
    global _current_groq_idx
    if not _groq_clients:
        raise RuntimeError("Groq client not configured")

    # If json_mode is required, ensure system prompt mentions JSON to pass Groq's validator
    sys_content = system_prompt
    if json_mode and "json" not in sys_content.lower():
        sys_content = f"{sys_content}\nOutput strictly in valid JSON format."

    num_keys = len(_groq_clients)
    start_idx = _current_groq_idx
    last_err = None

    for attempt in range(num_keys):
        key_idx = (start_idx + attempt) % num_keys
        client = _groq_clients[key_idx]

        def _call(cl=client):
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                return cl.chat.completions.create(**kwargs, timeout=timeout)
            except Exception as e:
                # If 400 json_validate_failed, retry without response_format
                if "json_validate_failed" in str(e).lower() or "failed to validate json" in str(e).lower():
                    logger.info(f"Groq {model} JSON schema validator failed; retrying without response_format.")
                    kwargs.pop("response_format", None)
                    return cl.chat.completions.create(**kwargs, timeout=timeout)
                raise e

        try:
            resp = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
            content = resp.choices[0].message.content or ""
            # Update current index to the successful key for next time
            _current_groq_idx = key_idx
            return content.strip()
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if ("429" in err_str or "rate limit" in err_str or "tpd" in err_str or "itpm" in err_str or "otpm" in err_str) and attempt < num_keys - 1:
                logger.warning(f"Groq key #{key_idx + 1} rate limited. Retrying immediately with key #{(key_idx + 1) % num_keys + 1}...")
                continue
            raise e

    raise last_err or RuntimeError("All Groq keys in pool failed")

async def call_gemini(
    prompt: str,
    system_prompt: str = "You are an expert enterprise research and B2B strategy analyst.",
    model: str = GEMINI_MODEL,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: float = 20.0
) -> str:
    global _current_gemini_idx
    if not _gemini_clients:
        raise RuntimeError("Gemini client not configured")

    full_prompt = f"{system_prompt}\n\nTask:\n{prompt}"
    if json_mode:
        full_prompt += "\n\nCRITICAL: Output ONLY valid, parsable JSON."

    num_keys = len(_gemini_clients)
    start_idx = _current_gemini_idx
    last_err = None

    for attempt in range(num_keys):
        key_idx = (start_idx + attempt) % num_keys
        client = _gemini_clients[key_idx]

        def _call(cl=client):
            from google.genai import types
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=3072,
            )
            if json_mode:
                config.response_mime_type = "application/json"
            
            return cl.models.generate_content(
                model=model,
                contents=full_prompt,
                config=config
            )

        try:
            resp = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
            text = resp.text or ""
            _current_gemini_idx = key_idx
            return text.strip()
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if ("429" in err_str or "503" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "unavailable" in err_str) and attempt < num_keys - 1:
                logger.warning(f"Gemini key #{key_idx + 1} hit rate limit / 503 spike. Retrying immediately with key #{(key_idx + 1) % num_keys + 1}...")
                continue
            raise e

    raise last_err or RuntimeError("All Gemini keys in pool failed")

async def call_llm(
    prompt: str,
    system_prompt: str = "You are an expert enterprise operations analyst.",
    task_type: str = "fast", # "fast" (S1, S5, S6, S7) or "large_context" (S2, S3)
    json_mode: bool = False,
    temperature: float = 0.2,
    max_retries: int = 1,
    timeout: Optional[float] = None,
) -> Any:
    """
    Resilient multi-model router with active rate-limit cooldown tracking and instant failover.
    Each provider automatically rotates across its configured multi-key pool before declaring failure.
    """
    now = time.time()
    provider_timeout = timeout or (
        LLM_LARGE_TIMEOUT_SECONDS if task_type == "large_context" else LLM_FAST_TIMEOUT_SECONDS
    )
    
    # Model hierarchy:
    # Large context tasks (S2 extract, S3 discover): Gemini pool -> Groq pool
    # Fast tasks (S1 resolve, S5 solution, S6 draft, S7 QA): Groq pool -> Gemini pool
    if task_type == "large_context":
        candidate_providers = [
            ("gemini", GEMINI_MODEL),
            ("groq", GROQ_FAST_MODEL),
        ]
        if GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL != GROQ_FAST_MODEL:
            candidate_providers.append(("groq", GROQ_FALLBACK_MODEL))
        groq_max_tokens = 1200
    else:
        candidate_providers = [
            ("groq", GROQ_FAST_MODEL),
            ("gemini", GEMINI_MODEL),
        ]
        if GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL != GROQ_FAST_MODEL:
            candidate_providers.append(("groq", GROQ_FALLBACK_MODEL))
        groq_max_tokens = 450

    # Filter out models currently under active rate-limit cooldown
    providers = []
    for prov, model_name in candidate_providers:
        cooldown_until = _model_cooldowns.get(model_name, 0)
        if now < cooldown_until:
            logger.info(f"Skipping cooled-down provider {prov} ({model_name}, cooldown remaining: {int(cooldown_until - now)}s)")
            continue
        providers.append((prov, model_name))

    # If all providers are in cooldown, reset cooldowns to give them another shot
    if not providers:
        providers = candidate_providers

    last_error = None
    deadline = asyncio.get_running_loop().time() + provider_timeout
    for provider, model_name in providers:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            if provider == "groq":
                raw = await call_groq(prompt, system_prompt, model=model_name, temperature=temperature, json_mode=json_mode, max_tokens=groq_max_tokens, timeout=remaining)
            else:
                raw = await call_gemini(prompt, system_prompt, model=model_name, temperature=temperature, json_mode=json_mode, timeout=remaining)

            if json_mode:
                cleaned = _clean_json_string(raw)
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError as je:
                    match = re.search(r'(\{.*\}|\[.*\])', cleaned, re.DOTALL)
                    if match:
                        return json.loads(match.group(1))
                    raise je
            return raw
        except Exception as e:
            err_str = str(e).lower()
            # If all keys for this provider were exhausted:
            if "429" in err_str or "rate limit" in err_str or "tpd" in err_str or "tokens per day" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                # Extract wait seconds if provided
                delay_match = re.search(r'(?:try again in|retry in)\s+([\d.]+)\s*s', err_str)
                cooldown_secs = float(delay_match.group(1)) + 2.0 if delay_match else 30.0
                cooldown_secs = min(max(cooldown_secs, 10.0), 60.0)

                _model_cooldowns[model_name] = time.time() + cooldown_secs
                logger.warning(f"All keys for {provider} ({model_name}) rate limited ({e}). Cooling down for {int(cooldown_secs)}s. Failing over immediately.")
            elif "503" in err_str or "unavailable" in err_str:
                _model_cooldowns[model_name] = time.time() + 15.0
                logger.warning(f"Provider {provider} ({model_name}) 503 spike. Cooling down for 15s. Switching immediately.")
            else:
                logger.warning(f"Provider {provider} ({model_name}) error: {e}. Switching immediately to next provider.")
            last_error = e

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
