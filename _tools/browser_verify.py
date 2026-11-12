"""Real-browser verification for the two protocol demo pages.

Drives Chromium via Playwright: types a question, clicks send, waits for the
streamed answer, asserts the counters advanced, and writes a screenshot.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    {
        "name": "AIChat-WeCall",
        "url": "http://127.0.0.1:18621/",
        "counter": "#frames",
        "shot": ROOT / "AIChat-WeCall" / "docs" / "demo-interactive.png",
    },
    {
        "name": "AskMeAnything-NovaAI",
        "url": "http://127.0.0.1:18622/",
        "counter": "#lines",
        "shot": ROOT / "AskMeAnything-NovaAI" / "docs" / "demo-interactive.png",
    },
]


def run(headless: bool = True) -> int:
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        for t in TARGETS:
            page = browser.new_page(viewport={"width": 1100, "height": 760})
            try:
                page.goto(t["url"], wait_until="networkidle", timeout=20000)
                mode = page.inner_text("#mode-tag")
                page.fill("#q", "playwright 验证：一句话介绍你自己")
                page.click("#send")
                page.wait_for_function(
                    f"() => parseInt(document.querySelector('{t['counter']}').textContent, 10) > 0",
                    timeout=20000,
                )
                frames = page.inner_text(t["counter"])
                ttfb = page.inner_text("#ttfb")
                body = page.inner_text("#log")[-220:]
                page.screenshot(path=str(t["shot"]), full_page=False)
                ok = int(frames) > 0 and ttfb != "-"
                print(f"{t['name']:24s} {'PASS' if ok else 'FAIL'} mode={mode} frames={frames} ttfb={ttfb}")
                print(f"  tail: {body.strip().splitlines()[-1][:120]}")
                failures += 0 if ok else 1
            except Exception as exc:
                print(f"{t['name']:24s} FAIL {type(exc).__name__}: {exc}")
                failures += 1
            finally:
                page.close()
        browser.close()
    return failures


if __name__ == "__main__":
    sys.exit(1 if run("--headful" not in sys.argv) else 0)