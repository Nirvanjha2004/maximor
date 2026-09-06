"""Coach: turns refereed failures into playbook lessons.

Prefers an LLM coach (OpenRouter free model) that reads failure rows and
writes short, tagged, actionable lessons. Falls back to the scripted coach
from mock.py when the LLM is unavailable, so the loop never breaks.
"""
import json
from pathlib import Path

from .llm import chat
from .mock import LESSON_TEMPLATES, LESSONS_PER_RUN

DATA = Path(__file__).resolve().parent.parent / "data"

COACH_SYSTEM = """You are the Coach for an accounts-payable triage agent. Given failed invoices (expected vs got + policy context), write short reusable lessons.
Reply with ONLY a JSON array, max 4 items, each: {"lesson": "<one or two sentences, imperative, cites POL-00x>", "tags": ["<subset of: small_amount,tolerance,missing_po,invalid_po,closed_po,risk_vendor,unknown_vendor,name_variant,duplicate,recurring>"]}.
Lessons must be general rules, not invoice-specific. No other text."""


def _scripted(failures, tag_fn):
    from .mock import coach_mock
    return coach_mock(failures, tag_fn, 0)


def coach_llm(failures, tag_fn, invoices_by_id, max_lessons=LESSONS_PER_RUN):
    if not failures:
        return []
    # Group failures for a compact prompt
    rows = []
    for f in failures[:12]:
        inv = invoices_by_id.get(f["invoice_id"], {})
        rows.append({
            "invoice": {k: inv.get(k) for k in ("id", "vendor_name", "amount", "po_number", "invoice_date")},
            "expected": f.get("expected"), "got": f.get("got"),
            "category": f.get("reason_tag"), "agent_reason": (f.get("agent_reason") or "")[:160],
        })
    prompt = ("Failures:\n" + json.dumps(rows, indent=1) +
              "\nWrite lessons that would prevent these failures.")
    out = chat([{"role": "system", "content": COACH_SYSTEM},
                {"role": "user", "content": prompt}],
               max_tokens=900, temperature=0.2)
    import re
    text = out.get("text", "") or ""
    try:
        start = text.find("[")
        end = text.rfind("]") + 1
        lessons = json.loads(text[start:end])
        clean = []
        for item in lessons[:max_lessons]:
            lesson = str(item.get("lesson", "")).strip()
            tags = [t for t in (item.get("tags") or []) if isinstance(t, str)]
            if lesson:
                clean.append({"lesson": lesson[:320], "tags": sorted(set(tags))})
        if clean:
            return clean
    except Exception:
        pass
    # LLM output unusable -> scripted fallback keeps loop alive
    return _scripted(failures, tag_fn)


def ensure_tags(lessons, failures, tag_fn, invoices_by_id):
    """Guarantee every lesson carries routable tags (union of observable tags)."""
    from .playbook import TAG_VOCAB, REASON_TAGS
    allowed = set(TAG_VOCAB) | set(REASON_TAGS)
    for lesson, f in zip(lessons, failures):
        tags = {t for t in lesson.get("tags", []) if t in allowed}
        tags.add(f.get("reason_tag", ""))
        inv = invoices_by_id.get(f["invoice_id"])
        if inv:
            try:
                from .tools import APSystem
                # tag_fn already bound; just call it
                tags |= set(tag_fn(inv))
            except Exception:
                pass
        lesson["tags"] = sorted(t for t in tags if t in allowed)
    # Fill generic template text if LLM returned empty lesson strings
    for lesson in lessons:
        if not lesson.get("lesson"):
            tag = (lesson.get("tags") or ["po_match"])[0]
            lesson["lesson"] = LESSON_TEMPLATES.get(tag, tag.replace("_", " "))
    return lessons
