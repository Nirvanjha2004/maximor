"""OpenRouter worker: ReAct-style JSON tool loop that works with ANY free chat model.

Instead of native function-calling (unsupported on many free models), the model
is asked to reply with exactly one JSON object per turn:
  {"call": {"tool": "<name>", "args": {...}}}
or a final decision:
  {"decision": "APPROVE|REJECT|ESCALATE", "reason": "...", "policy": "POL-00x"}

Tools are executed locally against APSystem (the fake third-party ERP/MCP).
Playbook lessons are injected per-invoice via tag routing (cheap memory).
"""
import json
import re
import time

from .llm import chat
from .playbook import observable_tags

TOOLS_HELP = """You can use these tools (one per turn). Reply with ONLY one JSON object per turn.
{"call": {"tool": "lookup_vendor", "args": {"vendor_name": "..."}}}
{"call": {"tool": "lookup_po", "args": {"po_number": "..."}}}
{"call": {"tool": "lookup_invoice_history", "args": {"vendor_name": "...", "amount": 0}}}
{"call": {"tool": "get_policies", "args": {}}}
When you have enough evidence, reply with ONLY:
{"decision": "APPROVE|REJECT|ESCALATE", "reason": "short reason", "policy": "POL-001..POL-007"}
Rules: POL-001 small<=500 auto-approve if known vendor+open PO. POL-002 over 500 needs open PO within 2%. POL-003 missing/invalid PO -> ESCALATE never REJECT. POL-004 same vendor+amount within 30 days -> REJECT else normal. POL-005 unknown vendor -> ESCALATE. POL-006 risk_flag -> ESCALATE. POL-007 closed PO -> ESCALATE."""

SYSTEM = ("You are an accounts-payable triage agent. Triage ONE invoice. "
          "Always verify with tools before deciding. " + TOOLS_HELP)


def _parse_json(text: str):
    """Extract first JSON object from free-form model text."""
    if not text:
        return None
    # Try raw parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Code fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Greedy brace scan
    start = text.find("{")
    while start != -1:
        depth, end = 0, -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
        start = text.find("{", start + 1)
    return None


def _exec_tool(ap, name, args):
    args = args or {}
    try:
        if name == "lookup_vendor":
            return ap.tool_lookup_vendor(args.get("vendor_name", ""))
        if name == "lookup_po":
            return ap.tool_lookup_po(args.get("po_number", ""))
        if name == "lookup_invoice_history":
            return ap.tool_lookup_invoice_history(
                args.get("vendor_name", ""), args.get("amount", 0))
        if name == "get_policies":
            return ap.tool_get_policies()
        if name == "list_invoices":
            return ap.tool_list_invoices()
        if name == "get_invoice":
            return ap.tool_get_invoice(args.get("invoice_id", ""))
        return {"error": f"unknown tool {name}"}
    except Exception as e:
        return {"error": str(e)[:300]}


def _rule_fallback(ap, invoice):
    """Deterministic policy engine used when the LLM fails to decide.

    This keeps live runs robust on flaky free models; the learning signal
    (accuracy per run) still comes from the referee, and the playbook still
    teaches the LLM path first.
    """
    from datetime import date
    vid, vendor = ap.find_vendor(invoice["vendor_name"])
    if not vendor:
        return "ESCALATE", "Vendor not found in master; onboarding required (POL-005).", "POL-005"
    if vendor.get("risk_flag"):
        return "ESCALATE", f"Vendor risk-flagged: {vendor.get('risk_note','review')} (POL-006).", "POL-006"
    po_num = (invoice.get("po_number") or "").strip()
    po = ap.pos.get(po_num.upper()) if po_num else None
    if not po_num or not po:
        return "ESCALATE", "Missing or invalid PO; human review required (POL-003).", "POL-003"
    if po.get("status") != "open":
        return "ESCALATE", f"PO {po_num} is {po.get('status')}; escalate to procurement (POL-007).", "POL-007"
    # duplicate check within 30 days
    amt = float(invoice["amount"])
    d1 = date.fromisoformat(invoice["invoice_date"])
    for h in ap.history:
        h_vid, _ = ap.find_vendor(h["vendor_name"])
        if h_vid == vid and abs(float(h["amount"]) - amt) < 0.005:
            d2 = date.fromisoformat(h["processed_date"])
            if (d1 - d2).days <= 30:
                return "REJECT", "Identical invoice processed within 30 days (POL-004).", "POL-004"
    if amt <= 500:
        return "APPROVE", "Small invoice, known vendor, valid open PO (POL-001).", "POL-001"
    po_amt = float(po["amount"])
    if po_amt and abs(amt - po_amt) / po_amt <= 0.02:
        return "APPROVE", f"Amount within 2% of PO {po_num} (POL-002).", "POL-002"
    return "ESCALATE", f"Amount differs >2% from PO {po_num}; controller review (POL-002).", "POL-002"


def run_invoice_or(ap, invoice, playbook_text, max_turns=4) -> dict:
    t0 = time.time()
    tool_calls = 0
    tokens_in = tokens_out = 0
    history = [
        {"role": "system", "content": SYSTEM + (f"\n\n{playbook_text}" if playbook_text else "")},
        {"role": "user", "content": f"Triage this invoice JSON:\n{json.dumps(invoice)}\nStart with lookup_vendor, then lookup_po, get_policies, lookup_invoice_history as needed. One JSON per turn."},
    ]
    transcript = []
    for _ in range(max_turns):
        out = chat(history, max_tokens=600, temperature=0.1)
        u = out.get("usage", {}) or {}
        tokens_in += int(u.get("prompt_tokens", 0))
        tokens_out += int(u.get("completion_tokens", 0))
        parsed = _parse_json(out.get("text", ""))
        transcript.append({"model_text": (out.get("text", "") or "")[:600], "parsed": bool(parsed)})
        if not parsed:
            history.append({"role": "assistant", "content": out.get("text", "") or "..."})
            history.append({"role": "user", "content": 'Reply with ONLY one JSON object: {"call": {"tool": ..., "args": {...}}} or {"decision": ...}.'})
            continue
        if "decision" in parsed:
            dec = str(parsed.get("decision", "")).upper().strip()
            reason = str(parsed.get("reason", ""))[:400]
            if dec in ("APPROVE", "REJECT", "ESCALATE"):
                ap.decisions[invoice["id"]] = {"decision": dec, "reason": reason}
                break
            history.append({"role": "assistant", "content": json.dumps(parsed)})
            history.append({"role": "user", "content": "decision must be APPROVE, REJECT or ESCALATE. Try again with ONLY JSON."})
            continue
        call = parsed.get("call") or {}
        tool = call.get("tool", "")
        args = call.get("args", {}) or {}
        # Auto-fill common args from invoice to reduce LLM errors
        if tool == "lookup_vendor" and not args.get("vendor_name"):
            args["vendor_name"] = invoice["vendor_name"]
        if tool == "lookup_po" and not args.get("po_number"):
            args["po_number"] = invoice.get("po_number") or ""
        if tool == "lookup_invoice_history":
            args.setdefault("vendor_name", invoice["vendor_name"])
            args.setdefault("amount", invoice["amount"])
        result = _exec_tool(ap, tool, args)
        tool_calls += 1
        history.append({"role": "assistant", "content": json.dumps(parsed)})
        history.append({"role": "user", "content": f"Tool {tool} result:\n{json.dumps(result)[:1500]}\nNext: one more tool call OR final decision JSON."})
    else:
        pass
    decided = invoice["id"] in ap.decisions
    used_fallback = False
    if not decided:
        dec, reason, _ = _rule_fallback(ap, invoice)
        ap.decisions[invoice["id"]] = {"decision": dec, "reason": reason + " [rule-assist]"}
        used_fallback = True
    latency = round(time.time() - t0, 2)
    # Free models cost $0; track tokens as efficiency metric.
    return {"invoice_id": invoice["id"], "tool_calls": tool_calls,
            "latency_s": latency, "tokens_in": tokens_in,
            "tokens_out": tokens_out, "cost_usd": 0.0,
            "fallback": used_fallback, "model": ""}


def tags_for_invoice(ap, invoice):
    return observable_tags(ap, invoice)
