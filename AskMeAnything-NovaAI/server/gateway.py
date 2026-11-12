"""Now AI / Ask Me Anything protocol gateway (com.android.ntduc.chatgpt).

Reconstructed from DataRepository.startStreamNowAiServer:

  POST http://pass-gpt.nowtechai.com/api/v1/pass
  headers: Key: <client key>, TimeStamps: <epoch millis>
  body:    {"contents":[{"role":"user","content":"..."}]}
  stream:  newline-delimited JSON, each line {"status":"...","content":"..."}

Upstream was measured on 2026-11-12: pass-gpt.nowtechai.com answers 503 on every
route, server.nowtechai.com 503, checking.heratech.space parks on a domain-sale
page. The gateway therefore runs mock by default and keeps the exact wire shape.

The `Key` header value is produced by the client's ViewModel layer; the exact
algorithm was not recovered from the decompiled sources, so `NOWAI_KEY` accepts
whatever the caller supplies and forwards it verbatim.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

UPSTREAM = os.getenv("NOWAI_UPSTREAM", "http://pass-gpt.nowtechai.com/api/v1/pass")
MODE = os.getenv("NOWAI_MODE", "auto")
KEY = os.getenv("NOWAI_KEY", "demo-key")
UA = "ktor-client"

app = FastAPI(title="Now AI / Ask Me Anything protocol gateway")

STATS = {"requests": 0, "upstream_requests": 0, "upstream_errors": 0, "streams": 0, "started_at": time.time()}
STATE: dict = {"reachable": None, "last_probe": 0.0, "status": None}
OTHER_ENDPOINTS = {
    "server.nowtechai.com": "http://server.nowtechai.com/",
    "checking.heratech.space": "http://checking.heratech.space/",
}


async def probe_upstream() -> bool:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(
                UPSTREAM,
                headers={"Key": KEY, "TimeStamps": str(int(time.time() * 1000)), "User-Agent": UA},
                json={"contents": [{"role": "user", "content": "ping"}]},
            )
        STATE["reachable"] = r.status_code in (200, 201)
        STATE["status"] = r.status_code
    except Exception:
        STATE["reachable"] = False
    STATE["last_probe"] = time.time()
    return bool(STATE["reachable"])


async def effective_mode() -> str:
    if MODE == "mock":
        return "mock"
    if MODE == "real":
        return "real"
    if STATE["reachable"] is None or time.time() - STATE["last_probe"] > 60:
        await probe_upstream()
    return "real" if STATE["reachable"] else "mock"


def line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def mock_lines(contents: list[dict]) -> list[str]:
    last = contents[-1]["content"] if contents else ""
    seed = int(hashlib.sha256(last.encode()).hexdigest()[:8], 16)
    text = (
        f"本地 mock（seed={seed % 9973}）。上游 pass-gpt.nowtechai.com 在 2026-11-12 实测返回 503，"
        f"客户端协议保持原样：NDJSON 逐行 {{status, content}}。\n\n你问的是：{last[:200]}"
    )
    step = max(1, len(text) // 20)
    out = [line({"status": "processing", "content": text[i : i + step]}) for i in range(0, len(text), step)]
    out.append(line({"status": "done", "content": ""}))
    return out


async def stream_mock(contents: list[dict]):
    for payload in mock_lines(contents):
        yield payload
        await asyncio.sleep(0.02)


async def stream_real(contents: list[dict]):
    headers = {"Key": KEY, "TimeStamps": str(int(time.time() * 1000)), "Content-Type": "application/json", "User-Agent": UA}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=8.0)) as c:
        async with c.stream("POST", UPSTREAM, json={"contents": contents}, headers=headers) as r:
            STATS["upstream_requests"] += 1
            if r.status_code not in (200, 201):
                STATS["upstream_errors"] += 1
                yield line({"status": "error", "content": f"upstream HTTP {r.status_code}"})
                return
            async for chunk in r.aiter_lines():
                if chunk.strip():
                    yield chunk + "\n"


@app.get("/health")
async def health() -> JSONResponse:
    mode = await effective_mode()
    return JSONResponse(
        {"ok": True, "configured_mode": MODE, "effective": mode, "upstream": UPSTREAM, "upstream_state": STATE, "stats": STATS}
    )


@app.get("/stats")
async def stats() -> JSONResponse:
    return JSONResponse(STATS)


@app.post("/api/v1/pass")
async def pass_endpoint(request: Request):
    STATS["requests"] += 1
    STATS["streams"] += 1
    body = await request.json()
    contents = body.get("contents") or []
    if not contents:
        return JSONResponse({"status": "error", "content": "contents should not be empty"}, status_code=400)
    mode = await effective_mode()
    gen = stream_real(contents) if mode == "real" else stream_mock(contents)
    return StreamingResponse(gen, media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


@app.post("/v1/chat/completions")
async def openai_compat(request: Request):
    STATS["requests"] += 1
    body = await request.json()
    messages = body.get("messages") or []
    contents = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]
    mode = await effective_mode()
    if not body.get("stream"):
        text = "".join(json.loads(x).get("content", "") for x in mock_lines(contents)) if mode == "mock" else ""
        if mode == "real":
            async for chunk in stream_real(contents):
                try:
                    text += json.loads(chunk).get("content", "")
                except json.JSONDecodeError:
                    pass
        return JSONResponse(
            {
                "id": f"chatcmpl-{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.get("model", "nowai"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }
        )

    async def gen():
        src = stream_real(contents) if mode == "real" else stream_mock(contents)
        async for chunk in src:
            try:
                ev = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if ev.get("status") == "done":
                yield "data: [DONE]\n\n"
                return
            payload = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "model": body.get("model", "nowai"),
                "choices": [{"index": 0, "delta": {"content": ev.get("content", "")}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/endpoints")
async def endpoints() -> JSONResponse:
    return JSONResponse(
        {
            "primary": UPSTREAM,
            "secondary": OTHER_ENDPOINTS,
            "note": "All three hosts were dead on 2026-11-12; kept for re-probing.",
        }
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    with open(os.path.join(os.path.dirname(__file__), "demo.html"), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("NOWAI_HOST", "127.0.0.1"), port=int(os.getenv("NOWAI_PORT", "18622")))