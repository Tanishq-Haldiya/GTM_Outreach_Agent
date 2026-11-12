"""Shared HTTP connection pools used by each active async event loop."""

import asyncio
import weakref
import httpx

_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def get_http_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        )
        _clients[loop] = client
    return client


async def close_http_client() -> None:
    loop = asyncio.get_running_loop()
    client = _clients.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()
