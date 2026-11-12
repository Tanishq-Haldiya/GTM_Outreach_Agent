import asyncio
import json
import time
from typing import Dict, List, Set, Any
from app.db import insert_event

# In-memory subscriber registry: run_id -> set of asyncio.Queue
_subscribers: Dict[str, Set[asyncio.Queue]] = {}

def get_subscribers(run_id: str) -> Set[asyncio.Queue]:
    if run_id not in _subscribers:
        _subscribers[run_id] = set()
    return _subscribers[run_id]

async def subscribe(run_id: str) -> asyncio.Queue:
    queue = asyncio.Queue()
    get_subscribers(run_id).add(queue)
    return queue

def unsubscribe(run_id: str, queue: asyncio.Queue):
    subs = get_subscribers(run_id)
    if queue in subs:
        subs.remove(queue)
    if not subs and run_id in _subscribers:
        del _subscribers[run_id]

async def emit_event(run_id: str, stage: str, event_type: str, message: str, payload: dict = None, duration: float = 0.0):
    payload = payload or {}
    t = time.time()
    
    # 1. Persist to SQLite
    event_id = insert_event(run_id, stage, event_type, message, payload, duration)
    
    # 2. Fan out to active SSE listeners
    event_obj = {
        "id": event_id,
        "run_id": run_id,
        "stage": stage,
        "event_type": event_type,
        "message": message,
        "payload": payload,
        "timestamp": t,
        "duration": round(duration, 2)
    }
    
    subs = list(get_subscribers(run_id))
    for q in subs:
        try:
            await q.put(event_obj)
        except Exception:
            pass

def format_sse(data: dict) -> str:
    """Formats a dictionary as an SSE data payload."""
    event_id = data.get("id")
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}data: {json.dumps(data)}\n\n"
