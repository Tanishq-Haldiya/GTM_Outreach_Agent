import json
import time
from collections import OrderedDict
from typing import Optional, Any
from app.db import get_db, ensure_db

_memory_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
_MAX_MEMORY_CACHE_ENTRIES = 512
_last_cache_cleanup = 0.0

def get_cached(key: str) -> Optional[Any]:
    now = time.time()
    memory_entry = _memory_cache.get(key)
    if memory_entry is not None:
        payload, expires_at = memory_entry
        if now < expires_at:
            _memory_cache.move_to_end(key)
            try:
                return json.loads(payload)
            except (TypeError, ValueError):
                _memory_cache.pop(key, None)
        else:
            _memory_cache.pop(key, None)

    ensure_db()
    conn = get_db()
    row = conn.execute(
        "SELECT payload, created_time, ttl_seconds FROM cache WHERE cache_key = ?",
        (key,)
    ).fetchone()
    conn.close()
    
    if not row:
        return None
        
    created, ttl = row["created_time"], row["ttl_seconds"]
    expires_at = created + ttl
    if now >= expires_at:
        # Expired
        return None
        
    try:
        payload = row["payload"]
        _memory_cache[key] = (payload, expires_at)
        _memory_cache.move_to_end(key)
        while len(_memory_cache) > _MAX_MEMORY_CACHE_ENTRIES:
            _memory_cache.popitem(last=False)
        return json.loads(payload)
    except Exception:
        return None

def set_cached(key: str, kind: str, payload: Any, ttl_seconds: float = 86400 * 3):
    global _last_cache_cleanup
    ensure_db()
    serialized = json.dumps(payload)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO cache (cache_key, kind, payload, created_time, ttl_seconds) VALUES (?, ?, ?, ?, ?)",
        (key, kind, serialized, time.time(), ttl_seconds)
    )
    now = time.time()
    if now - _last_cache_cleanup > 900:
        conn.execute("DELETE FROM cache WHERE created_time + ttl_seconds <= ?", (now,))
        _last_cache_cleanup = now
    conn.commit()
    conn.close()
    _memory_cache[key] = (serialized, now + ttl_seconds)
    _memory_cache.move_to_end(key)
    while len(_memory_cache) > _MAX_MEMORY_CACHE_ENTRIES:
        _memory_cache.popitem(last=False)
