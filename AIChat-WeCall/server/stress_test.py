"""Round-1 load test for the AIChat protocol gateway.

Runs: health probe, single SSE round trip, concurrency sweep, error paths.
Reports p50 / p95 / max and pass-fail per scenario. No external dependency
beyond httpx.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx

BASE = "http://127.0.0.1:18621"


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def report(name: str, latencies: list[float], ok: int, fail: int, extra: str = "") -> bool:
    if latencies:
        print(
            f"{name:34s} n={ok+fail:<4d} ok={ok:<4d} fail={fail:<4d} "
            f"p50={pct(latencies,50):7.1f}ms p95={pct(latencies,95):7.1f}ms max={max(latencies):7.1f}ms {extra}"
        )
    else:
        print(f"{name:34s} n={ok+fail:<4d} ok={ok:<4d} fail={fail:<4d} (no timings) {extra}")
    return fail == 0


async def health_burst(client: httpx.AsyncClient, n: int) -> tuple[list[float], int, int]:
    lat: list[float] = []
    ok = fail = 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            r = await client.get("/health")
            lat.append((time.perf_counter() - t0) * 1000)
            ok += r.status_code == 200
            fail += r.status_code != 200
        except Exception:
            fail += 1
    return lat, ok, fail


async def stream_once(client: httpx.AsyncClient, query: str) -> tuple[float, bool, int, str]:
    t0 = time.perf_counter()
    frames = 0
    conv = ""
    try:
        async with client.stream(
            "POST", "/chat_stream", json={"query": query, "model": 3, "conversation": []}, timeout=30.0
        ) as r:
            if r.status_code != 200:
                return (time.perf_counter() - t0) * 1000, False, 0, f"http {r.status_code}"
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    frames += 1
                    ev = json.loads(line[6:])
                    if ev.get("event") == "end":
                        conv = ev.get("conversation_id", "")
        return (time.perf_counter() - t0) * 1000, True, frames, conv
    except Exception as exc:
        return (time.perf_counter() - t0) * 1000, False, frames, str(exc)


async def concurrency_sweep(client: httpx.AsyncClient, levels: list[int]) -> bool:
    all_ok = True
    for level in levels:
        lat: list[float] = []
        ok = fail = 0
        t0 = time.perf_counter()

        async def one(i: int) -> None:
            nonlocal ok, fail
            ms, fine, frames, _ = await stream_once(client, f"load test {level}-{i}")
            lat.append(ms)
            if fine and frames >= 2:
                ok += 1
            else:
                fail += 1

        await asyncio.gather(*(one(i) for i in range(level)))
        wall = (time.perf_counter() - t0) * 1000
        all_ok &= report(f"chat_stream concurrency c={level}", lat, ok, fail, f"wall={wall:.0f}ms")
    return all_ok


async def error_paths(client: httpx.AsyncClient) -> bool:
    all_ok = True
    cases = [
        ("empty query -> 500", {"query": "", "model": 3, "conversation": []}, 500),
        ("missing query -> 500", {"model": 3, "conversation": []}, 500),
    ]
    for name, payload, want in cases:
        r = await client.post("/chat_stream", json=payload)
        body = await r.aread()
        good = r.status_code == want
        all_ok &= good
        print(f"{name:34s} {'PASS' if good else 'FAIL'} status={r.status_code} body={body.decode()[:90]}")
    r = await client.post("/chat_role", json={"query": "hi"})
    good = r.status_code == 500 and b"response_mode" in await r.aread()
    all_ok &= good
    print(f"{'chat_role needs response_mode':34s} {'PASS' if good else 'FAIL'} status={r.status_code}")
    r = await client.get("/v1/models")
    good = r.status_code == 200 and len(r.json()["data"]) >= 5
    all_ok &= good
    print(f"{'models catalogue':34s} {'PASS' if good else 'FAIL'} status={r.status_code}")
    return all_ok


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--health-n", type=int, default=200)
    ap.add_argument("--concurrency", default="1,4,8,16")
    args = ap.parse_args()

    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]
    results: list[bool] = []

    async with httpx.AsyncClient(base_url=args.base, timeout=60.0) as client:
        h = (await client.get("/health")).json()
        print(f"gateway mode={h['configured_mode']} effective={h['effective']} upstream={h['upstream']}")
        st = h["upstream_state"]
        print(
            f"server_alive={st.get('server_alive')} ({st.get('server_latency_ms')}ms) "
            f"ai_channel_alive={st.get('ai_channel_alive')} (bytes={st.get('ai_probe_bytes')})\n"
        )

        lat, ok, fail = await health_burst(client, args.health_n)
        results.append(report("health", lat, ok, fail))

        ms, fine, frames, info = await stream_once(client, "say hi")
        print(f"{'chat_stream single':34s} {'PASS' if fine and frames >= 2 else 'FAIL'} {ms:.1f}ms frames={frames} conv={info}")
        results.append(fine and frames >= 2)

        results.append(await concurrency_sweep(client, levels))
        results.append(await error_paths(client))

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))