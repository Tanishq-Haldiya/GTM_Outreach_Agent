import pytest
from app.llm.router import _clean_json_string

def test_clean_json_string():
    raw_md = '```json\n{"status": "ok", "count": 5}\n```'
    assert _clean_json_string(raw_md) == '{"status": "ok", "count": 5}'

    raw_plain = '```\n{"status": "ok"}\n```'
    assert _clean_json_string(raw_plain) == '{"status": "ok"}'

    raw_direct = '{"status": "ok"}'
    assert _clean_json_string(raw_direct) == '{"status": "ok"}'
