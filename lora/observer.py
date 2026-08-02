#!/usr/bin/env python3
"""
ScreenMagnet development observer.

Feeds each development step to the local qwen3.5:4b model, asks it to explain
what happened in its own words, and appends the pair to a JSONL corpus.

The corpus is the raw material for a future LoRA fine-tune. This script does
NOT train anything -- Ollama is inference-only. See lora/README.md.

Usage:
    ./observer.py "step title" "what actually happened, in detail"
    ./observer.py --show          # print the corpus so far
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OLLAMA = "http://localhost:11434/api/generate"
MODEL = "qwen3.5:4b"
CORPUS = Path(__file__).parent / "corpus.jsonl"

SYSTEM = """You are observing a real software project being built, step by step.

The project is ScreenMagnet: a KDE Plasma system-tray app for a SteamOS machine
that mirrors the desktop to a TV (Samsung/LG via Miracast, Apple TV via AirPlay).
Linux has no built-in screen-mirroring sender, which is the gap this app fills.

For each development step you are given, explain in 3-5 sentences:
  1. What was done.
  2. WHY it was done -- the engineering reason, not just the action.
  3. What it means for the project going forward.

Be concrete and technical. Do not pad. Do not congratulate anyone. If a step
reveals a risk or a blocker, say so plainly."""


def ask(step: str, detail: str, timeout: int = 180) -> str:
    payload = json.dumps({
        "model": MODEL,
        "system": SYSTEM,
        "prompt": f"STEP: {step}\n\nWHAT HAPPENED:\n{detail}\n\nExplain this step:",
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"].strip()


def record(step: str, detail: str) -> str:
    try:
        explanation = ask(step, detail)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        explanation = f"[OBSERVER FAILED: {e}]"

    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "project": "ScreenMagnet",
            "step": step,
            "detail": detail,
            "explanation": explanation,
            "model": MODEL,
        }) + "\n")
    return explanation


def show() -> None:
    if not CORPUS.exists():
        print("corpus empty")
        return
    for line in CORPUS.open():
        d = json.loads(line)
        print(f"\n--- [{d['ts']}] {d['step']}")
        print(d["explanation"])


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--show":
        show()
    elif len(sys.argv) == 3:
        print(record(sys.argv[1], sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(1)
