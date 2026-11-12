"""Viddo (com.energysh.quickarte) v4 AI API client.

Recovered from:
  com.energysh.quickart.server.ai.AIServiceSdk  -> appId YZ080, base aicup-v2
  com.energysh.aiservice.api.d                  -> envelope builder
  j2.h                                          -> RSA/ECB/PKCS1Padding, 117-byte chunks
  com.energysh.aiservice.api.AiFunAction        -> 50+ action tags

Envelope: decrypt = base64(RSA_PKCS1(json)), sign = optional, content = same json in clear.

Usage:
  python v4_client.py
  python v4_client.py --action texttoimage
"""
from __future__ import annotations

import argparse
import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://aicup-v2.magicutapp.com"
APP_ID = "YZ080"
PKG = "com.energysh.quickarte"
CHANNEL = "GOOGLEPLAY"

PUB_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC8lOG7IZvz23OkRhWL8k2ST657nhGN7nMfe3AiFvvZKzlV7TkgvNwy43C3"
    "To5WuS+TK71jLoed1zAm7zvt6PdIPQAVn3a+P55XYt92sUsUVARYm1liaste+btGQgaDWYWnDWE13H54uDd1hQ4QT8b+5hp"
    "5qHqVPdKNYdPmav9JYwIDAQAB"
)
PEM = b"-----BEGIN PUBLIC KEY-----\n" + PUB_B64.encode() + b"\n-----END PUBLIC KEY-----\n"
KEY = serialization.load_pem_public_key(PEM)


def rsa_b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    chunks = [KEY.encrypt(raw[i:i + 117], padding.PKCS1v15()) for i in range(0, len(raw), 117)]
    return base64.b64encode(b"".join(chunks)).decode()


def envelope(payload: dict) -> dict:
    return {"decrypt": rsa_b64(payload), "sign": "", "content": json.dumps(payload, separators=(",", ":"))}


def get_uuid(client: httpx.Client) -> str:
    r = client.post(f"{BASE}/v4/getUuid", json={"appId": APP_ID, "pkgName": PKG})
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(f"getUuid failed: {body}")
    return body["data"]


def upload(client: httpx.Client, payload: dict) -> dict:
    r = client.post(f"{BASE}/v4/upload", files={k: (None, v) for k, v in envelope(payload).items()})
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", default="texttovideo", help="AiFunAction functionTag, e.g. texttovideo / texttoimage / aichat")
    ap.add_argument("--prompt", default="a cat walking on the beach")
    args = ap.parse_args()

    with httpx.Client(headers={"User-Agent": "okhttp/4.12.0"}, timeout=30.0) as client:
        uid = get_uuid(client)
        print(f"uId = {uid}")
        payload = {
            "appTime": str(int(time.time() * 1000)),
            "priority": "99",
            "uId": uid,
            "pkgName": PKG,
            "requestType": args.action,
            "content": args.prompt,
            "prompt": args.prompt,
            "platFormId": "",
        }
        print("decrypt length:", len(rsa_b64(payload)))
        resp = upload(client, payload)
        print(json.dumps(resp, ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
