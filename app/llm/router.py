import json
import re
import time
import asyncio
import logging
import contextvars
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any, List
from app.config import (
    GROQ_API_KEY, GROQ_FAST_MODEL, GROQ_FALLBACK_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL,
    NVIDIA_API_KEY, NVIDIA_MODEL, NVIDIA_HEAVY_MODEL, NVIDIA_REASONING_MODEL, NVIDIA_LIGHT_MODEL, NVIDIA_BASE_URL,
    LLM_FAST_TIMEOUT_SECONDS, LLM_LARGE_TIMEOUT_SECONDS,
    LLM_MAX_CONCURRENT_REQUESTS,
)

logger = logging.getLogger(__name__)

# Cooldown registry uses provider reset windows to avoid premature retry storms.
_model_cooldowns: Dict[str, float] = {}
_run_id_context = contextvars.ContextVar("llm_run_id", default=None)
_stage_context = contextvars.ContextVar("llm_stage", default=None)
_model_semaphores: Dict[str, asyncio.Semaphore] = {}
_model_budget_locks: Dict[str, asyncio.Lock] = {}
_model_budget_events: Dict[str, deque] = {}
_request_lane: Optional[asyncio.Semaphore] = None


def _get_request_lane() -> asyncio.Semaphore:
    """Serialize provider requests by default to keep concurrent agents quota-safe."""
    global _request_lane
    if _request_lane is None:
        _request_lane = asyncio.Semaphore(LLM_MAX_CONCURRENT_REQUESTS)
    return _request_lane


@contextmanager
def llm_stage_context(run_id: str, stage: str):
    run_token = _run_id_context.set(run_id)
    stage_token = _stage_context.set(stage)
    try:
        yield
    finally:
        _stage_context.reset(stage_token)
        _run_id_context.reset(run_token)


async def _reserve_model_budget(model: str, prompt_tokens: int) -> Optional[tuple]:
    """Pace estimated tokens against a realistic, configurable rolling minute budget."""
    import os
    default_limit = 35000 if "qwen" in model.lower() else 40000 if "gpt-oss" in model.lower() else 50000
    limit = int(os.getenv("LLM_TPM_" + re.sub(r"[^A-Za-z0-9]", "_", model).upper(), str(default_limit)))
    if limit <= 0:
        return
    if prompt_tokens > limit:
        return None
    lock = _model_budget_locks.setdefault(model, asyncio.Lock())
    events = _model_budget_events.setdefault(model, deque())
    async with lock:
        now = time.monotonic()
        while events and now - events[0][0] >= 60:
            events.popleft()
        used = sum(tokens for _, tokens in events)
        if used + prompt_tokens <= limit:
            reservation = (now, prompt_tokens)
            events.append(reservation)
            return reservation
        pause = max(0.05, 60 - (now - events[0][0]))
        if pause > 4:
            raise RuntimeError(f"Locally paced {model} request: estimated token budget is full; switching to the next provider.")
        await asyncio.sleep(pause)


async def _release_model_budget(model: str, reservation) -> None:
    if reservation is None:
        return
    lock = _model_budget_locks.setdefault(model, asyncio.Lock())
    async with lock:
        events = _model_budget_events.get(model)
        if events:
            try:
                events.remove(reservation)
            except ValueError:
                pass


_DURATION_TOKEN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(days?|d|hours?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
    re.IGNORECASE,
)


def _parse_duration_seconds(value: str) -> Optional[float]:
    """Parse provider durations such as ``14m25.5s`` or ``1h 2m``."""
    seconds = 0.0
    cursor = 0
    factors = {
        "d": 86400, "day": 86400, "days": 86400,
        "h": 3600, "hour": 3600, "hours": 3600,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    }
    for match in _DURATION_TOKEN.finditer(value or ""):
        if (value or "")[cursor:match.start()].strip(" \t,"):
            break
        seconds += float(match.group(1)) * factors[match.group(2).lower()]
        cursor = match.end()
    return seconds if seconds > 0 else None


def _provider_retry_after_seconds(error: Exception) -> Optional[float]:
    """Extract a provider's retry window from HTTP headers or its error body."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(str(retry_after))
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass

    error_text = str(error)
    retry_match = re.search(r"(?:try again in|retry in)\s+(.+)", error_text, re.IGNORECASE)
    if retry_match:
        duration = _parse_duration_seconds(retry_match.group(1).split("Please try again", 1)[0])
        if duration is not None:
            return duration

    # Gemini errors can expose the backoff as a structured retryDelay field.
    delay_match = re.search(r"retryDelay[\"']?\s*[:=]\s*[\"']([^\"']+)", error_text, re.IGNORECASE)
    if delay_match:
        return _parse_duration_seconds(delay_match.group(1))
    return None

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

# Multi-key pool support for NVIDIA NIM
_nvidia_keys = [k.strip() for k in (NVIDIA_API_KEY or "").split(",") if k.strip()]
_current_nvidia_idx = 0

async def call_openai_compatible(
    provider_name: str,
    base_url: str,
    keys: List[str],
    model: str,
    prompt: str,
    system_prompt: str = "You are an expert enterprise operations analyst.",
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: int = 600,
    timeout: float = 75.0
) -> Dict[str, Any]:
    if not keys:
        raise RuntimeError(f"{provider_name} API key not configured")

    import httpx
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    num_keys = len(keys)
    last_err = None

    for attempt in range(num_keys):
        key = keys[attempt % num_keys]
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(endpoint, headers=headers, json=payload)
                if res.status_code in (404, 410):
                    _model_cooldowns[model] = time.time() + 3600.0
                    raise RuntimeError(f"{provider_name} model '{model}' returned HTTP {res.status_code}. Deprecated, EOL, or invalid model ID.")
                if res.status_code == 400 and json_mode and "json" in res.text.lower():
                    payload.pop("response_format", None)
                    res = await client.post(endpoint, headers=headers, json=payload)

                if res.status_code == 429 or res.status_code >= 500:
                    err_msg = f"{provider_name} HTTP {res.status_code}: {res.text}"
                    if attempt < num_keys - 1:
                        logger.warning(f"{provider_name} key #{attempt + 1} hit {res.status_code}; trying next key.")
                        continue
                    raise RuntimeError(err_msg)

                res.raise_for_status()
                data = res.json()
                msg = data["choices"][0]["message"]
                content = (msg.get("content") or "").strip()
                if not content and msg.get("reasoning_content"):
                    rc = msg.get("reasoning_content", "")
                    json_match = re.search(r'(\{.*\}|\[.*\])', rc, re.DOTALL)
                    if json_match:
                        content = json_match.group(1).strip()
                    else:
                        content = rc.strip()
                if not content:
                    raise RuntimeError(f"{provider_name} ({model}) returned an empty response body.")
                usage = data.get("usage", {})
                return {
                    "content": content,
                    "input_tokens": usage.get("prompt_tokens", 0) or 0,
                    "output_tokens": usage.get("completion_tokens", 0) or 0
                }
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if ("429" in err_str or "rate" in err_str or "503" in err_str) and attempt < num_keys - 1:
                continue
            raise e

    raise last_err or RuntimeError(f"All {provider_name} keys failed")

def _clean_json_string(text: str) -> str:
    """Strips markdown code fences and surrounding text from model JSON outputs."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if (candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]")):
            return candidate
    
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        return text

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        if first_bracket == -1 or first_brace < first_bracket:
            return text[first_brace:last_brace + 1].strip()

    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return text[first_bracket:last_bracket + 1].strip()

    return text


def _robust_json_parse(text: str, provider: str = "", model: str = "") -> Any:
    """Parses JSON with multi-strategy recovery for markdown fences, unclosed quotes, and prefaces."""
    cleaned = _clean_json_string(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try extracting outermost object
    m_obj = re.search(r"(\{[\s\S]*\})", text)
    if m_obj:
        try:
            return json.loads(m_obj.group(1))
        except Exception:
            pass

    # Try extracting outermost array
    m_arr = re.search(r"(\[[\s\S]*\])", text)
    if m_arr:
        try:
            return json.loads(m_arr.group(1))
        except Exception:
            pass

    # Try repairing unclosed quotes or brackets if truncated
    repaired = cleaned
    if repaired.count('"') % 2 != 0:
        repaired += '"'
    if repaired.startswith("{") and not repaired.endswith("}"):
        repaired += "}"
    elif repaired.startswith("[") and not repaired.endswith("]"):
        repaired += "]"
    try:
        return json.loads(repaired)
    except Exception:
        pass

    prov_info = f" from {provider} ({model})" if provider else ""
    raise RuntimeError(f"JSONDecodeError{prov_info}: Unable to parse valid JSON from response. Raw output preview: {text[:200]}")

async def call_groq(
    prompt: str,
    system_prompt: str = "You are an expert enterprise research and B2B strategy analyst.",
    model: str = GROQ_FAST_MODEL,
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: int = 450,
    timeout: float = 15.0
) -> Dict[str, Any]:
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
            effective_max_tokens = max(max_tokens, 1200) if "gpt-oss" in model.lower() else max_tokens
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
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
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError(f"Groq {model} returned an empty response body.")
            usage = getattr(resp, "usage", None)
            # Update current index to the successful key for next time
            _current_groq_idx = key_idx
            return {"content": content, "input_tokens": getattr(usage, "prompt_tokens", 0) or 0, "output_tokens": getattr(usage, "completion_tokens", 0) or 0}
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if ("429" in err_str or "rate limit" in err_str or "tpd" in err_str or "itpm" in err_str or "otpm" in err_str) and attempt < num_keys - 1:
                logger.warning(f"Groq key #{key_idx + 1} rate limited; trying the next configured key.")
                continue
            raise e

    raise last_err or RuntimeError("All Groq keys in pool failed")

async def call_gemini(
    prompt: str,
    system_prompt: str = "You are an expert enterprise research and B2B strategy analyst.",
    model: str = GEMINI_MODEL,
    temperature: float = 0.2,
    json_mode: bool = False,
    max_tokens: int = 450,
    timeout: float = 20.0
) -> Dict[str, Any]:
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
                max_output_tokens=max_tokens,
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
            text = (resp.text or "").strip()
            if not text:
                raise RuntimeError(f"Gemini {model} returned an empty response body.")
            usage = getattr(resp, "usage_metadata", None)
            _current_gemini_idx = key_idx
            return {"content": text, "input_tokens": getattr(usage, "prompt_token_count", 0) or 0, "output_tokens": getattr(usage, "candidates_token_count", 0) or 0}
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if ("429" in err_str or "503" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "unavailable" in err_str or "limit" in err_str) and attempt < num_keys - 1:
                logger.warning(f"Gemini key #{key_idx + 1} error ({type(e).__name__}: {e}); trying the next configured key.")
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
    
    # Resilient multi-provider routing based on task intensity:
    # Heavy tasks (S3, S6): NVIDIA Nemotron (or Gemma/70B) -> Groq gpt-oss-120b -> Gemini Flash -> Groq fast
    # Heavy tasks (S2 extraction, S3 discovery): Gemini Flash (4 rotating keys) -> NVIDIA NIM -> Groq fallback
    # Fast tasks (S0, S1, S5, S6, S7): Groq fast/qwen -> Gemini Flash -> NVIDIA light
    if task_type == "large_context":
        candidate_providers = []
        if _gemini_keys:
            candidate_providers.append(("gemini", GEMINI_MODEL))
        if _nvidia_keys:
            candidate_providers.append(("nvidia", NVIDIA_HEAVY_MODEL))
            if NVIDIA_REASONING_MODEL and NVIDIA_REASONING_MODEL != NVIDIA_HEAVY_MODEL:
                candidate_providers.append(("nvidia", NVIDIA_REASONING_MODEL))
        if _groq_keys and GROQ_FALLBACK_MODEL:
            candidate_providers.append(("groq", GROQ_FALLBACK_MODEL))
        if _groq_keys and GROQ_FAST_MODEL and GROQ_FAST_MODEL != GROQ_FALLBACK_MODEL:
            candidate_providers.append(("groq", GROQ_FAST_MODEL))
        max_output_tokens = 3000
    else:
        candidate_providers = []
        if _groq_keys and GROQ_FAST_MODEL:
            candidate_providers.append(("groq", GROQ_FAST_MODEL))
        if _gemini_keys:
            candidate_providers.append(("gemini", GEMINI_MODEL))
        if _nvidia_keys:
            candidate_providers.append(("nvidia", NVIDIA_LIGHT_MODEL))
        max_output_tokens = 1000

    # Filter out models currently under active rate-limit cooldown
    providers = []
    for prov, model_name in candidate_providers:
        cooldown_until = _model_cooldowns.get(model_name, 0)
        if now < cooldown_until:
            logger.info(f"Skipping cooled-down provider {prov} ({model_name}, cooldown remaining: {int(cooldown_until - now)}s)")
            continue
        providers.append((prov, model_name))

    # If all providers are cooling down, fail over to stage fallbacks instead of
    # immediately retrying a provider before its stated reset time.
    if not providers:
        retry_in = min(_model_cooldowns.get(model_name, now) - now for _, model_name in candidate_providers) if candidate_providers else 5
        raise RuntimeError(
            f"All LLM providers are cooling down; next provider is available in "
            f"approximately {max(1, int(retry_in))} seconds."
        )

    last_error = None
    for provider, model_name in providers:
        # Give NVIDIA models the full time they need without timing out (up to 75s) as requested
        if provider == "nvidia":
            attempt_timeout = max(provider_timeout, 75.0)
        elif provider == "gemini":
            attempt_timeout = max(25.0, provider_timeout)
        else:
            attempt_timeout = min(provider_timeout, 25.0)

        try:
            estimated_tokens = max(1, int((len(prompt) + len(system_prompt)) / 3.2))
            reservation = await _reserve_model_budget(model_name, estimated_tokens + max_output_tokens)
            semaphore = _model_semaphores.setdefault(model_name, asyncio.Semaphore(1))
            try:
                async with _get_request_lane():
                    if provider == "groq":
                        async with semaphore:
                            response = await call_groq(
                                prompt, system_prompt, model=model_name,
                                temperature=temperature, json_mode=json_mode,
                                max_tokens=max_output_tokens, timeout=attempt_timeout,
                            )
                    elif provider == "gemini":
                        async with semaphore:
                            response = await call_gemini(
                                prompt, system_prompt, model=model_name,
                                temperature=temperature, json_mode=json_mode,
                                max_tokens=max_output_tokens, timeout=attempt_timeout,
                            )
                    elif provider == "nvidia":
                        async with semaphore:
                            response = await call_openai_compatible(
                                "NVIDIA NIM", NVIDIA_BASE_URL, _nvidia_keys, model=model_name,
                                prompt=prompt, system_prompt=system_prompt,
                                temperature=temperature, json_mode=json_mode,
                                max_tokens=max_output_tokens, timeout=attempt_timeout,
                            )
                    else:
                        raise RuntimeError(f"Unsupported provider: {provider}")
            except Exception:
                await _release_model_budget(model_name, reservation)
                raise

            raw = response["content"]
            run_id = _run_id_context.get()
            if run_id:
                try:
                    from app.db import record_llm_usage
                    record_llm_usage(run_id, _stage_context.get(), provider, model_name, response["input_tokens"], response["output_tokens"])
                    from app.events import emit_event
                    await emit_event(run_id, _stage_context.get() or "llm", "llm_usage", "Model request completed.", payload={
                        "provider": provider, "model": model_name,
                        "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                    })
                except Exception as usage_err:
                    logger.debug("Could not persist model usage: %s", usage_err)

            if json_mode:
                return _robust_json_parse(raw, provider=provider, model=model_name)
            return raw
        except Exception as e:
            err_str = str(e).lower()
            # If all keys for this provider were exhausted:
            retry_after = _provider_retry_after_seconds(e)
            if "locally paced" in err_str or "estimated token budget is full" in err_str:
                _model_cooldowns[model_name] = time.time() + 8.0
                logger.info("Local token budget for %s full; pausing for 8 seconds and switching provider.", model_name)
            elif "429" in err_str or "rate limit" in err_str or "tpd" in err_str or "tokens per day" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                cooldown_secs = min(45.0, max(10.0, retry_after + 2.0)) if retry_after is not None else 30.0
                _model_cooldowns[model_name] = time.time() + cooldown_secs
                logger.warning(
                    "All keys for %s (%s) are rate limited; cooling down for %d seconds before retrying.",
                    provider, model_name, int(cooldown_secs),
                )
            elif "503" in err_str or "unavailable" in err_str:
                cooldown_secs = min(30.0, max(10.0, retry_after + 2.0)) if retry_after is not None else 15.0
                _model_cooldowns[model_name] = time.time() + cooldown_secs
                logger.warning(
                    "Provider %s (%s) is temporarily unavailable; cooling down for %d seconds.",
                    provider, model_name, int(cooldown_secs),
                )
            else:
                err_display = f"{type(e).__name__}: {e}" if str(e).strip() else type(e).__name__
                logger.warning(f"Provider {provider} ({model_name}) error: {err_display}. Switching immediately to next provider.")
            last_error = e

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
