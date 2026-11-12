"""Probe the vsAnalytics gateway recovered from Viddo (com.energysh.quickarte).

Base is hardcoded in ServiceApis.getAnaUrl: every relative path is appended to
https://analytics.enjoymobiserver.com/

GET without a body answers {"errorCode":"Failed in decoding inputData"}; POST with
the ServiceConfigs JSON body returns 200. This script measures both shapes.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid

import httpx

BASE = "https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1"
UA = "okhttp/4.12.0"

ENDPOINTS = [
    "clientDevice/registerNewDevice.html?osType=1",
    "clientDevice/activeDeviceReport.html?osType=1",
    "clientEvent/eventDataReport.html?osType=1",
    "qiniu/getUploadToken.html?osType=1",
    "feedbackRecordClient/getReportTypeList.html?osType=1",
]


def payload() -> dict:
    dev = str(uuid.uuid4())
    return {
        "appId": "",
        "appTime": int(time.time() * 1000),
        "appVersion": "4.0.4.1",
        "channelName": "GOOGLE_PLAY",
        "deviceUuid": dev,
        "isVip": "0",
        "lang": "en",
        "osVersion": "33",
        "osType": "1",
        "phoneBrand": "Google",
        "phoneModel": "Pixel 7",
        "pkgName": "com.energysh.quickarte",
        "uuid": dev,
        "version": "40401",
        "versionName": "4.0.4.1",
        "activeDuration": 0,
        "eventData": "[]",
    }


def pct(v: list[float], p: float) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    return s[min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))]


async def one(client: httpx.AsyncClient, path: str, method: str):
    t0 = time.perf_counter()
    url = f"{BASE}/{path}"
    try:
        if method == "POST":
            r = await client.post(url, json=payload())
        else:
            r = await client.get(url)
        body = (await r.aread()).decode("utf-8", "replace")
        return (time.perf_counter() - t0) * 1000, r.status_code, body[:160]
    except Exception as exc:
        return (time.perf_counter() - t0) * 1000, -1, f"{type(exc).__name__}: {exc}"[:160]


async def main() -> int:
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20.0) as client:
        print(f"gateway {BASE}\n")
        print(f"{'endpoint':52s} {'GET':>28s}  {'POST':>40s}")
        ok = 0
        for ep in ENDPOINTS:
            _, gs, gb = await one(client, ep, "GET")
            ms, ps, pb = await one(client, ep, "POST")
            if ps == 200:
                ok += 1
            print(f"{ep:52s} {str(gs):>28s}  {ms:6.0f}ms {ps} {pb[:60]}")
        print(f"\n{ok}/{len(ENDPOINTS)} endpoints accepted POST JSON")

        lat: list[float] = []
        fails = 0
        for _ in range(20):
            ms, st, _ = await one(client, ENDPOINTS[2], "POST")
            lat.append(ms)
            fails += st != 200
        print(f"eventDataReport x20: fail={fails} p50={statistics.median(lat):.0f}ms p95={pct(lat,95):.0f}ms")

        sample = await one(client, ENDPOINTS[1], "POST")
        print(f"\nregisterNewDevice sample body: {sample[2]}")
        return 0 if ok == len(ENDPOINTS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))