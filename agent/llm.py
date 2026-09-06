"""Unified LLM client for OpenRouter free models (stdlib only, no extra deps).

Handles reasoning-style free models that return content=null + reasoning text:
we concatenate all text fields and let callers parse JSON from anywhere.
Falls back across OPENROUTER_FALLBACKS on 429/404/5xx or empty replies.
"""
import json
import time
import urllib.request
import urllib.error

from .config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_FALLBACKS,
    OPENROUTER_MODEL,
)


def _ordered_models(preferred=None):
    seen = []
    for m in ([preferred or OPENROUTER_MODEL] + list(OPENROUTER_FALLBACKS)):
        if m and m not in seen:
            seen.append(m)
    return seen


def _extract_text(message: dict) -> str:
    parts = []
    for key in ("content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
                elif isinstance(item, dict):
                    t = item.get("text") or item.get("content")
                    if isinstance(t, str) and t.strip():
                        parts.append(t)
    # Some providers put text under reasoning_details
    for det in message.get("reasoning_details") or []:
        if isinstance(det, dict):
            t = det.get("text")
            if isinstance(t, str) and t.strip() and t not in parts:
                parts.append(t)
    # Deduplicate while preserving order
    out, seen = [], set()
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "\n".join(out)


def chat(messages, max_tokens=800, temperature=0.2, preferred_model=None,
         timeout=90) -> dict:
    """Call OpenRouter chat. Returns {text, model, usage, error}."""
    if not OPENROUTER_API_KEY:
        return {"text": "", "model": "", "usage": {}, "error": "missing OPENROUTER_API_KEY"}
    base = (OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1").rstrip("/")
    last_err = ""
    for model in _ordered_models(preferred_model):
        body = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            base + "/chat/completions", data=body,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Nirvanjha2004/maximor",
                "X-Title": "EvolveAP Track1 Syndicate",
            })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            msg = data["choices"][0]["message"]
            text = _extract_text(msg)
            usage = data.get("usage", {}) or {}
            if text.strip():
                return {"text": text, "model": model, "usage": usage, "error": ""}
            last_err = f"{model}: empty reply"
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:300]
            except Exception:
                detail = str(e)[:300]
            last_err = f"{model}: HTTP {e.code} {detail}"
            if e.code in (429,):
                time.sleep(2)
            continue
        except Exception as e:
            last_err = f"{model}: {str(e)[:300]}"
            continue
    return {"text": "", "model": "", "usage": {}, "error": last_err}
