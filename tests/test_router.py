import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.router import _clean_json_string, call_gemini, call_groq, _run_id_context, _stage_context

def test_clean_json_string():
    raw_md = '```json\n{"status": "ok", "count": 5}\n```'
    assert _clean_json_string(raw_md) == '{"status": "ok", "count": 5}'

    raw_plain = '```\n{"status": "ok"}\n```'
    assert _clean_json_string(raw_plain) == '{"status": "ok"}'

    raw_direct = '{"status": "ok"}'
    assert _clean_json_string(raw_direct) == '{"status": "ok"}'

def test_gemini_503_rotation_event():
    async def _test():
        mock_client1 = MagicMock()
        mock_client1.models.generate_content.side_effect = RuntimeError("ServerError: 503 UNAVAILABLE. High demand spike")
        mock_client2 = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"status": "success"}'
        mock_resp.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=15)
        mock_client2.models.generate_content.return_value = mock_resp

        run_token = _run_id_context.set("test_run_123")
        stage_token = _stage_context.set("S2")

        with patch("app.llm.router._gemini_clients", [mock_client1, mock_client2]), \
             patch("app.llm.router._current_gemini_idx", 0), \
             patch("app.events.emit_event", new_callable=AsyncMock) as mock_emit:
            
            result = await call_gemini("test prompt", json_mode=True, timeout=5.0)

            assert result["content"] == '{"status": "success"}'
            assert result["key_index"] == 2
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args[1]
            assert call_kwargs["event_type"] == "llm_key_rotation"
            assert call_kwargs["payload"]["provider"] == "gemini"
            assert call_kwargs["payload"]["status_code"] == 503
            assert call_kwargs["payload"]["reason"] == "high_demand"
            assert call_kwargs["payload"]["failed_key_index"] == 1
            assert call_kwargs["payload"]["next_key_index"] == 2

        _run_id_context.reset(run_token)
        _stage_context.reset(stage_token)

    asyncio.run(_test())

@pytest.mark.anyio
async def test_mistral_large_2_minute_timeout():
    from app.llm.router import call_llm
    with patch("app.llm.router._nvidia_keys", ["dummy_nvidia_key"]), \
         patch("app.llm.router.NVIDIA_HEAVY_MODEL", "mistralai/mistral-large-4-1t-a52b"), \
         patch("app.llm.router._model_cooldowns", {}), \
         patch("app.llm.router.call_openai_compatible", new_callable=AsyncMock) as mock_nvidia:
        
        mock_nvidia.return_value = {"content": "mistral output", "input_tokens": 10, "output_tokens": 20, "key_index": 1}
        
        # When calling with large_context (which includes NVIDIA_HEAVY_MODEL if configured)
        # and gemini_keys are empty so it selects nvidia:
        with patch("app.llm.router._gemini_keys", []):
            res = await call_llm("Analyze operations", task_type="large_context")
            assert res == "mistral output"
            mock_nvidia.assert_called_once()
            assert mock_nvidia.call_args[1]["timeout"] == 120.0

def test_groq_429_rotation_event():
    async def _test():
        mock_client1 = MagicMock()
        mock_client1.chat.completions.create.side_effect = RuntimeError("429 rate limit exceeded")
        mock_client2 = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="groq success"))]
        mock_resp.usage = MagicMock(prompt_tokens=8, completion_tokens=12)
        mock_client2.chat.completions.create.return_value = mock_resp

        run_token = _run_id_context.set("test_run_456")
        stage_token = _stage_context.set("S1")

        with patch("app.llm.router._groq_clients", [mock_client1, mock_client2]), \
             patch("app.llm.router._current_groq_idx", 0), \
             patch("app.events.emit_event", new_callable=AsyncMock) as mock_emit:
            
            result = await call_groq("test prompt", timeout=5.0)

            assert result["content"] == "groq success"
            assert result["key_index"] == 2
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args[1]
            assert call_kwargs["event_type"] == "llm_key_rotation"
            assert call_kwargs["payload"]["provider"] == "groq"
            assert call_kwargs["payload"]["status_code"] == 429
            assert call_kwargs["payload"]["reason"] == "rate_limit"

        _run_id_context.reset(run_token)
        _stage_context.reset(stage_token)

    asyncio.run(_test())

def test_mistral_timeout_sync_wrapper():
    asyncio.run(test_mistral_large_2_minute_timeout())


