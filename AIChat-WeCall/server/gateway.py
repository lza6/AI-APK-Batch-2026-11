"""AIChat (com.ai.assistant.powerful.chat.bot v1.9.1) protocol gateway.

Reconstructed from the client's OkHttp call sites:
  POST /chat_stream   body {query, model, conversation:[{question,answer}]}
                      SSE, each event data = {content, conversation_id, event}
  POST /chat_role     body {query, user, id, conversationId, response_mode}
  GET  /prompts/get_new?lang=<lang>   DES-CBC encrypted bot catalogue

The upstream AI channel was measured on 2026-11-12 and returns HTTP 201 with an
empty SSE body (chat_stream) or closes after ~20 s with no bytes (chat_role),
so `effective` resolves to mock unless AICHAT_MODE=real is forced.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

UPSTREAM = os.getenv("AICHAT_UPSTREAM", "https://chatai.wecall.info")
MODE = os.getenv("AICHAT_MODE", "auto")  # auto | real | mock
UA = "okhttp/4.12.0"

# Recovered from z4/b.java (doGetKey) and z4/a.java (doGetIV): eight fragments each,
# joined then split on "&#", each parsed and XORed with 65280.
DES_KEY = os.getenv("AICHAT_DES_KEY", "20190826")
DES_IV = os.getenv("AICHAT_DES_IV", "00514321")

app = FastAPI(title="AIChat protocol gateway")

STATS: dict[str, Any] = {
    "requests": 0,
    "upstream_requests": 0,
    "upstream_errors": 0,
    "streams": 0,
    "started_at": time.time(),
}
MODEL_NAMES = {1: "standard", 2: "standard-pro", 3: "default", 4: "plus", 5: "max"}
UPSTREAM_STATE: dict[str, Any] = {
    "server_alive": None,       # GET /health answers
    "ai_channel_alive": None,   # POST /chat_stream emits at least one byte
    "last_probe": 0.0,
    "server_latency_ms": None,
    "ai_probe_latency_ms": None,
    "ai_probe_bytes": None,
}


async def probe_upstream() -> bool:
    """Two-stage probe. A live web server with a dead AI channel is the common case
    for this app: /health returns 200 while /chat_stream answers 201 with zero bytes."""
    async with httpx.AsyncClient(timeout=8.0) as c:
        try:
            t0 = time.perf_counter()
            r = await c.get(f"{UPSTREAM}/health", headers={"User-Agent": UA})
            UPSTREAM_STATE["server_alive"] = r.status_code == 200
            UPSTREAM_STATE["server_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception:
            UPSTREAM_STATE["server_alive"] = False

        ai_alive, nbytes, latency = False, 0, None
        if UPSTREAM_STATE["server_alive"]:
            try:
                t0 = time.perf_counter()
                payload = {"query": "ping", "model": 3, "conversation": []}
                headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "text/event-stream", "User-Agent": UA}
                async with c.stream("POST", f"{UPSTREAM}/chat_stream", json=payload, headers=headers) as sr:
                    async for chunk in sr.aiter_bytes():
                        nbytes += len(chunk)
                        if nbytes >= 1:
                            break
                latency = round((time.perf_counter() - t0) * 1000, 1)
                ai_alive = nbytes > 0
            except Exception:
                ai_alive = False
        UPSTREAM_STATE["ai_channel_alive"] = ai_alive
        UPSTREAM_STATE["ai_probe_bytes"] = nbytes
        UPSTREAM_STATE["ai_probe_latency_ms"] = latency
    UPSTREAM_STATE["last_probe"] = time.time()
    return bool(UPSTREAM_STATE["ai_channel_alive"])


async def effective_mode() -> str:
    if MODE == "mock":
        return "mock"
    if MODE == "real":
        return "real"
    if UPSTREAM_STATE["ai_channel_alive"] is None or time.time() - UPSTREAM_STATE["last_probe"] > 60:
        await probe_upstream()
    return "real" if UPSTREAM_STATE["ai_channel_alive"] else "mock"


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def mock_answer(query: str, model: int) -> str:
    """Deterministic local answer so the demo page has something to stream."""
    seed = int(hashlib.sha256(f"{query}{model}".encode()).hexdigest()[:8], 16)
    flavour = MODEL_NAMES.get(model, "default")
    openers = [
        "Here is the local mock reply",
        "Mock stream from the protocol gateway",
        "Deterministic local answer",
    ]
    return (
        f"{openers[seed % len(openers)]} (model={model}, profile={flavour}).\n\n"
        f"You asked: {query.strip()[:200]}\n\n"
        "This text is produced by the gateway, not by the AIChat upstream. The client wire format is "
        "preserved: every chunk is an SSE `data:` frame carrying {content, conversation_id, event} "
        "and the final frame sets event=\"end\". Swap AICHAT_MODE=real once the upstream AI channel "
        "starts answering again."
    )


async def stream_mock(query: str, model: int) -> Any:
    conv_id = hashlib.md5(f"{query}{time.time()}".encode()).hexdigest()[:16]
    text = mock_answer(query, model)
    step = max(1, len(text) // 24)
    for i in range(0, len(text), step):
        yield sse({"event": "message", "content": text[i : i + step], "conversation_id": conv_id})
        await asyncio.sleep(0.012)
    yield sse({"event": "end", "content": "", "conversation_id": conv_id})


async def stream_real(query: str, model: int, conversation: list[dict[str, str]]) -> Any:
    payload = {"query": query, "model": model, "conversation": conversation}
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "text/event-stream", "User-Agent": UA}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as c:
        async with c.stream("POST", f"{UPSTREAM}/chat_stream", json=payload, headers=headers) as r:
            STATS["upstream_requests"] += 1
            if r.status_code != 200:
                detail = (await r.aread()).decode("utf-8", "replace")[:400]
                STATS["upstream_errors"] += 1
                yield sse({"event": "error", "content": detail, "conversation_id": ""})
                yield sse({"event": "end", "content": "", "conversation_id": ""})
                return
            produced = False
            async for line in r.aiter_lines():
                if line:
                    produced = True
                    yield line + "\n"
            if not produced:
                STATS["upstream_errors"] += 1
                yield sse({"event": "error", "content": "upstream returned an empty SSE stream", "conversation_id": ""})
                yield sse({"event": "end", "content": "", "conversation_id": ""})


@app.get("/health")
async def health() -> JSONResponse:
    mode = await effective_mode()
    return JSONResponse(
        {
            "ok": True,
            "configured_mode": MODE,
            "effective": mode,
            "upstream": UPSTREAM,
            "upstream_state": UPSTREAM_STATE,
            "stats": STATS,
        }
    )


@app.get("/stats")
async def stats() -> JSONResponse:
    return JSONResponse(STATS)


@app.get("/v1/models")
async def models() -> JSONResponse:
    return JSONResponse(
        {"object": "list", "data": [{"id": f"aichat-{k}", "object": "model", "profile": v} for k, v in MODEL_NAMES.items()]}
    )


@app.post("/chat_stream")
async def chat_stream(request: Request) -> StreamingResponse:
    STATS["requests"] += 1
    STATS["streams"] += 1
    body = await request.json()
    query = (body.get("query") or "").strip()
    model = int(body.get("model") or 3)
    conversation = body.get("conversation") or []
    if not query:
        # Mirrors the upstream's own validation message.
        return JSONResponse(
            {"statusCode": 500, "message": "Request parameter check error:query should not be empty"}, status_code=500
        )
    mode = await effective_mode()
    gen = stream_real(query, model, conversation) if mode == "real" else stream_mock(query, model)
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/chat_role")
async def chat_role(request: Request) -> StreamingResponse:
    STATS["requests"] += 1
    STATS["streams"] += 1
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"statusCode": 500, "message": "Request parameter check error:query should not be empty"}, status_code=500)
    if not body.get("response_mode"):
        return JSONResponse({"statusCode": 500, "message": "Request parameter check error:response_mode should not be empty"}, status_code=500)
    mode = await effective_mode()
    gen = stream_real(query, 3, []) if mode == "real" else stream_mock(query, 3)
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/prompts/get_new")
async def prompts(lang: str = "en", source: str = "local") -> JSONResponse:
    STATS["requests"] += 1
    if source == "upstream":
        # The live endpoint still serves the encrypted catalogue; decrypt it with the
        # recovered DES material, which also proves the key derivation.
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{UPSTREAM}/prompts/get_new", params={"lang": lang}, headers={"User-Agent": UA})
            plain = des_decrypt(r.text.strip())
            bots = json.loads(plain)
            return JSONResponse({"lang": lang, "source": "upstream", "count": len(bots), "bots": bots,
                                 "cipher_len": len(r.text.strip()), "plain_len": len(plain)})
        except Exception as exc:
            return JSONResponse({"source": "upstream", "error": f"{type(exc).__name__}: {exc}"}, status_code=502)
    for candidate in (
        os.path.join(os.path.dirname(__file__), "bots.json"),
        os.path.join(os.path.dirname(__file__), "..", "work", "assets", "bots.json"),
    ):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                bots = json.load(f)
            break
    else:
        bots = []
    return JSONResponse({"lang": lang, "source": "local", "count": len(bots), "bots": bots,
                         "note": "assets/bots.json plaintext; upstream serves the same list DES-CBC encrypted"})


def des_decrypt(b64_text: str, key: str = DES_KEY, iv: str = DES_IV) -> str:
    from base64 import b64decode

    from Crypto.Cipher import DES
    from Crypto.Util.Padding import unpad

    cipher = DES.new(key.encode("utf-8"), DES.MODE_CBC, iv.encode("utf-8"))
    return unpad(cipher.decrypt(b64decode(b64_text)), DES.block_size).decode("utf-8")


@app.post("/v1/chat/completions")
async def openai_compat(request: Request) -> Any:
    """OpenAI-shaped wrapper over the native protocol, so existing clients can point here."""
    STATS["requests"] += 1
    body = await request.json()
    messages = body.get("messages") or []
    query = messages[-1].get("content", "") if messages else ""
    conversation = [
        {"question": messages[i].get("content", ""), "answer": messages[i + 1].get("content", "")}
        for i in range(0, max(0, len(messages) - 2), 2)
    ]
    model = int(body.get("model") or 3)
    mode = await effective_mode()
    if not body.get("stream"):
        text = mock_answer(query, model) if mode == "mock" else await collect_real(query, model, conversation)
        return JSONResponse(
            {
                "id": f"chatcmpl-{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"aichat-{model}",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }
        )

    async def gen() -> Any:
        async for frame in (stream_real(query, model, conversation) if mode == "real" else stream_mock(query, model)):
            if not frame.startswith("data: "):
                continue
            event = json.loads(frame[6:])
            if event.get("event") == "end":
                yield "data: [DONE]\n\n"
                return
            chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "model": f"aichat-{model}",
                "choices": [{"index": 0, "delta": {"content": event.get("content", "")}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def collect_real(query: str, model: int, conversation: list[dict[str, str]]) -> str:
    parts: list[str] = []
    async for frame in stream_real(query, model, conversation):
        if frame.startswith("data: "):
            try:
                parts.append(json.loads(frame[6:]).get("content", ""))
            except json.JSONDecodeError:
                pass
    return "".join(parts) or "(upstream returned no content)"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    with open(os.path.join(os.path.dirname(__file__), "demo.html"), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("AICHAT_HOST", "127.0.0.1"), port=int(os.getenv("AICHAT_PORT", "18621")))