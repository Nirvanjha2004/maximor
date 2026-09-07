"""Mock worker + scripted coach.

MOCK MODE exists ONLY to validate the end-to-end learning pipeline offline
(no API key, no spend). It simulates a worker with realistic, characteristic
failure modes whose errors disappear once the playbook contains the relevant
lesson. Results under mock mode are pipeline self-tests - run --live for real
measurable results.

The mock worker "knows" the expected reason_tag (from expected.json) only to
decide WHICH characteristic mistake it would make without a playbook lesson;
the live worker needs none of this.
"""
import json
from pathlib import Path

from .playbook import observable_tags
from .referee import load_expected

DATA = Path(__file__).resolve().parent.parent / "data"

# Without a relevant lesson, the sloppy worker makes these characteristic mistakes.
SLOPPY_MISTAKE = {
    "name_variant": "ESCALATE",       # treats name variant as unknown vendor
    "missing_po": "REJECT",           # rejects instead of escalating (POL-003)
    "risk_vendor": "APPROVE",         # misses the risk flag
    "closed_po": "APPROVE",           # approves against a closed PO
    "unknown_vendor": "APPROVE",      # small amount, never heard of them, pays anyway
    "duplicate": "APPROVE",           # never checks history
    "recurring_legit": "REJECT",      # over-eager duplicate rejection
    "tolerance_breach": "APPROVE",    # never compares amounts to the PO
    "small_auto": None,               # gets it right
    "po_match": None,                 # gets it right
}

SLOPPY_REASON = {
    "name_variant": "Vendor not found in vendor master, escalated for onboarding.",
    "missing_po": "No PO provided, rejected.",
    "risk_vendor": "PO matches, approved.",
    "closed_po": "PO found, approved.",
    "unknown_vendor": "Small amount, approved.",
    "duplicate": "Vendor and PO valid, approved.",
    "recurring_legit": "Matching invoice found in history, rejected as duplicate.",
    "tolerance_breach": "Vendor and PO valid, approved.",
    "small_auto": "Small invoice, known vendor, valid open PO (POL-001).",
    "po_match": "PO matches within tolerance (POL-002).",
}

LESSON_TEMPLATES = {
    "name_variant": ("Normalize vendor names before lookup: the vendor master matches "
                     "case/punctuation variants and aliases (e.g. 'ACME FREIGHT', 'bytefoods'). "
                     "Always call lookup_vendor with the invoice name even if it looks unfamiliar."),
    "tolerance_breach": ("For invoices over $500, compare the invoice amount to the PO amount: "
                         "approve only if within +/-2%, otherwise ESCALATE (POL-002). Never skip this check."),
    "missing_po": ("A missing or invalid PO means ESCALATE for human review, never REJECT (POL-003)."),
    "risk_vendor": ("If lookup_vendor returns risk_flag=true, ESCALATE regardless of amount or PO "
                    "match (POL-006)."),
    "closed_po": ("If the PO exists but its status is not 'open', ESCALATE to procurement; never "
                  "approve against a closed PO (POL-007)."),
    "unknown_vendor": ("If lookup_vendor returns found=false, ESCALATE for vendor onboarding even for "
                       "small amounts; never approve or reject (POL-005)."),
    "duplicate": ("Call lookup_invoice_history for vendor+amount: if the same amount was processed "
                  "1-30 days BEFORE the invoice date, REJECT as duplicate (POL-004). Same-day rows "
                  "are the same record, not a duplicate."),
    "recurring_legit": ("A history match older than 30 days is legitimate recurring billing: process it "
                        "normally per the other policies, do NOT reject as duplicate (POL-004)."),
    "small_auto": ("Small invoices (<= $500) with a known vendor and valid open PO are auto-approved "
                   "(POL-001), unless the vendor is unknown or risk-flagged."),
    "po_match": ("Verify the PO is open and the amount is within tolerance before approving (POL-002)."),
}

LESSONS_PER_RUN = 4  # the coach writes at most this many new lessons per run


def run_invoice_mock(ap, invoice, playbook_text, lessons_retrieved, reason_tag):
    """Simulated worker: correct iff the playbook taught this failure category."""
    learned = any(reason_tag in l["tags"] for l in lessons_retrieved)
    mistake = SLOPPY_MISTAKE.get(reason_tag)
    if learned or mistake is None:
        expected = next(e["expected_decision"] for e in load_expected()
                        if e["invoice_id"] == invoice["id"])
        decision, reason = expected, "Correct per policy (learned via playbook)." if learned \
            else SLOPPY_REASON.get(reason_tag, "Correct per policy.")
    else:
        decision, reason = mistake, SLOPPY_REASON.get(reason_tag, "")
    ap.decisions[invoice["id"]] = {"decision": decision, "reason": reason}
    # Simulated cost profile: learned agents make fewer wasted tool calls.
    n_lessons = len([x for x in playbook_text.splitlines() if x.startswith("[")]) if playbook_text else 0
    tool_calls = 2 if learned else 4
    return {"invoice_id": invoice["id"], "tool_calls": tool_calls,
            "latency_s": round(0.8 + 0.3 * tool_calls, 2),
            "tokens_in": 800 + 250 * tool_calls + 30 * n_lessons,
            "tokens_out": 150, "cost_usd": 0.0,
            "thoughts": [f"Mock plan for {reason_tag}: {'apply playbook' if learned else 'sloppy shortcut'}"],
            "trace": {"thoughts": [], "tool_notes": {}, "refined": False}}


def coach_mock(failures, tag_fn, run_no):
    """Scripted coach: groups failures by category, prioritizes by frequency."""
    groups = {}
    for f in failures:
        groups.setdefault(f["reason_tag"], []).append(f)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[1][0]["invoice_id"]))
    lessons = []
    for tag, fs in ordered[:LESSONS_PER_RUN]:
        tags = set()
        for f in fs:
            inv = next(i for i in json.loads((DATA / "invoices.json").read_text(encoding="utf-8"))
                       if i["id"] == f["invoice_id"])
            tags |= tag_fn(inv)
        lessons.append({"lesson": LESSON_TEMPLATES.get(tag, tag.replace("_", " ")),
                        "tags": sorted(tags | {tag})})
    return lessons
