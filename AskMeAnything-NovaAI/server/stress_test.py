"""Round-1 load test for the Now AI / Ask Me Anything protocol gateway.

Same scenario set as the AIChat harness, but the stream is newline-delimited
JSON ({"status","content"}) instead of SSE frames.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx

BASE = "http://127.0.0.1:18622"


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def report(name: str, lat: list[float], ok: int, fail: int, extra: str = "") -> bool:
    print(
        f"{name:30s} n={ok+fail:<4d} ok={ok:<4d} fail={fail:<4d} "
        f"p50={pct(lat,50):7.1f}ms p95={pct(lat,95):7.1f}ms max={max(lat) if lat else 0:7.1f}ms {extra}"
    )
    return fail == 0


async def health_burst(client: httpx.AsyncClient, n: int):
    lat, ok, fail = [], 0, 0
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


async def stream_once(client: httpx.AsyncClient, q: str):
    t0 = time.perf_counter()
    lines, status = 0, ""
    try:
        async with client.stream("POST", "/api/v1/pass", json={"contents": [{"role": "user", "content": q}]}, timeout=30.0) as r:
            if r.status_code != 200:
                return (time.perf_counter() - t0) * 1000, False, 0, f"http {r.status_code}"
            async for raw in r.aiter_lines():
                if not raw.strip():
                    continue
                lines += 1
                status = json.loads(raw).get("status", "")
        return (time.perf_counter() - t0) * 1000, True, lines, status
    except Exception as exc:
        return (time.perf_counter() - t0) * 1000, False, lines, str(exc)


async def sweep(client: httpx.AsyncClient, levels: list[int]) -> bool:
    ok_all = True
    for level in levels:
        lat, ok, fail = [], 0, 0
        t0 = time.perf_counter()

        async def one(i: int):
            nonlocal ok, fail
            ms, fine, lines, _ = await stream_once(client, f"load {level}-{i}")
            lat.append(ms)
            if fine and lines >= 2:
                ok += 1
            else:
                fail += 1

        await asyncio.gather(*(one(i) for i in range(level)))
        ok_all &= report(f"pass concurrency c={level}", lat, ok, fail, f"wall={(time.perf_counter()-t0)*1000:.0f}ms")
    return ok_all


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--health-n", type=int, default=100)
    ap.add_argument("--concurrency", default="1,8,16")
    args = ap.parse_args()

    results: list[bool] = []
    async with httpx.AsyncClient(base_url=args.base, timeout=60.0) as client:
        h = (await client.get("/health")).json()
        print(f"gateway mode={h['configured_mode']} effective={h['effective']} upstream={h['upstream']}")
        print(f"upstream_state={h['upstream_state']}\n")

        lat, ok, fail = await health_burst(client, args.health_n)
        results.append(report("health", lat, ok, fail))

        ms, fine, lines, st = await stream_once(client, "say hi")
        good = fine and lines >= 2
        print(f"{'pass single':30s} {'PASS' if good else 'FAIL'} {ms:.1f}ms lines={lines} status={st}")
        results.append(good)

        results.append(await sweep(client, [int(x) for x in args.concurrency.split(",") if x.strip()]))

        r = await client.post("/api/v1/pass", json={"contents": []})
        good = r.status_code == 400
        print(f"{'empty contents -> 400':30s} {'PASS' if good else 'FAIL'} status={r.status_code}")
        results.append(good)

        r = await client.get("/v1/chat/completions")
        print(f"{'chat completions route':30s} {'PASS' if r.status_code in (405, 200) else 'FAIL'} status={r.status_code}")
        results.append(r.status_code in (405, 200))

    passed = sum(1 for x in results if x)
    print(f"\n{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))