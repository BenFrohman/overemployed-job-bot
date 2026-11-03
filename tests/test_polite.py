# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""PoliteClient: conditional requests, retries/backoff, per-host limits. Mocked HTTP only."""
import asyncio

import httpx
import pytest

from app.polite import FetchError, PoliteClient, host_key


def make(handler, **kw):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    kw.setdefault("min_interval", 0)
    c = PoliteClient(user_agent="test-agent", transport=httpx.MockTransport(handler), sleep=fake_sleep,
                     backoff=1.0, **kw)
    return c, sleeps


def test_etag_cache_and_304():
    seen = []

    def handler(req):
        seen.append(req.headers.get("if-none-match"))
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json={"n": 1}, headers={"ETag": '"v1"'})

    async def go():
        c, _ = make(handler)
        async with c:
            a = await c.get_json("https://x.example/a")
            b = await c.get_json("https://x.example/a")
            return a, b, c.stats
    a, b, stats = asyncio.run(go())
    assert a == b == {"n": 1} and seen == [None, '"v1"'] and stats["not_modified"] == 1


def test_retries_honor_retry_after_then_succeed():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if calls["n"] == 2:
            raise httpx.ConnectTimeout("t", request=req)
        return httpx.Response(200, json=[1])

    async def go():
        c, sleeps = make(handler, retries=3)
        async with c:
            return await c.get_json("https://x.example/r"), sleeps
    data, sleeps = asyncio.run(go())
    assert data == [1] and calls["n"] == 3
    assert sleeps[0] == 7.0 and 2.0 <= sleeps[1] <= 2.5  # Retry-After, then exponential backoff


def test_gives_up_and_404():
    async def go():
        c, _ = make(lambda req: httpx.Response(503), retries=2)
        async with c:
            with pytest.raises(FetchError):
                await c.get_json("https://x.example/down")
            assert c.stats["requests"] == 3
        c2, _ = make(lambda req: httpx.Response(404))
        async with c2:
            assert await c2.get_json("https://x.example/gone", allow_404=True) is None
            with pytest.raises(FetchError):
                await c2.get_json("https://x.example/gone")
    asyncio.run(go())


def test_per_host_concurrency_and_spacing():
    active = {"now": 0, "max": 0}

    async def handler(req):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.01)
        active["now"] -= 1
        return httpx.Response(200, json={})

    async def go():
        c = PoliteClient(user_agent="t", transport=httpx.MockTransport(handler), per_host_concurrency=2,
                         min_interval=0.0)
        async with c:
            await asyncio.gather(*(c.get_json(f"https://{i}.recruitee.com/api/offers/", use_cache=False)
                                   for i in range(8)))
        # min_interval spacing is applied per host
        c2 = PoliteClient(user_agent="t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                          min_interval=0.05)
        loop = asyncio.get_running_loop()
        async with c2:
            t0 = loop.time()
            await asyncio.gather(*(c2.get_json("https://y.example/", use_cache=False) for _ in range(3)))
            return loop.time() - t0
    elapsed = asyncio.run(go())
    assert active["max"] == 2  # all *.recruitee.com share one host budget
    assert elapsed >= 0.09
    assert host_key("https://acme.recruitee.com/api") == "recruitee.com"
    assert host_key("https://api.lever.co/v0") == "api.lever.co"
