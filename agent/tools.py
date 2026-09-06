"""The fake third-party AP system the worker agent accesses through tools.

This stands in for the "third party app access" (APIs / MCPs) in the hackathon
brief: the agent cannot see the underlying data, it can only query it through
the tool interface below, exactly like a real MCP server or REST API.
"""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

VALID_DECISIONS = {"APPROVE", "REJECT", "ESCALATE"}


def normalize_name(s: str) -> str:
    """Case/punctuation-insensitive name normalization (what a real AP system does)."""
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


class APSystem:
    """In-memory fake ERP: vendors, POs, policies, invoice inbox, processed history."""

    def __init__(self):
        self.vendors = json.loads((DATA / "vendors.json").read_text(encoding="utf-8"))
        self.pos = json.loads((DATA / "purchase_orders.json").read_text(encoding="utf-8"))
        self.policies = json.loads((DATA / "policies.json").read_text(encoding="utf-8"))
        self.invoices = json.loads((DATA / "invoices.json").read_text(encoding="utf-8"))
        self.history = json.loads((DATA / "invoice_history.json").read_text(encoding="utf-8"))
        self.decisions = {}  # invoice_id -> {"decision": ..., "reason": ...}

    # ---- internal lookups (not exposed to the agent directly) ----
    def find_vendor(self, name: str):
        n = normalize_name(name)
        for vid, v in self.vendors.items():
            candidates = [v["name"]] + list(v.get("aka", []))
            if n in [normalize_name(c) for c in candidates]:
                return vid, v
        return None, None

    def get_invoice(self, invoice_id: str):
        for inv in self.invoices:
            if inv["id"] == invoice_id:
                return inv
        return None

    # ---- tool implementations (exposed to the agent) ----
    def tool_list_invoices(self):
        return {"invoices": self.invoices}

    def tool_get_invoice(self, invoice_id: str):
        inv = self.get_invoice(invoice_id)
        return inv if inv else {"error": f"Invoice {invoice_id} not found"}

    def tool_lookup_vendor(self, vendor_name: str):
        vid, v = self.find_vendor(vendor_name)
        if not v:
            return {"found": False, "message": "Vendor not found in vendor master"}
        return {"found": True, "vendor_id": vid, "name": v["name"],
                "status": v["status"], "risk_flag": v["risk_flag"], "risk_note": v["risk_note"]}

    def tool_lookup_po(self, po_number: str):
        po = self.pos.get((po_number or "").strip().upper())
        if not po:
            return {"found": False, "message": f"PO {po_number} not found"}
        vendor_name = self.vendors.get(po["vendor_id"], {}).get("name")
        return {"found": True, **po, "vendor_name": vendor_name}

    def tool_lookup_invoice_history(self, vendor_name: str, amount):
        """Prior invoices already processed for this vendor+amount (duplicate check)."""
        vid, _ = self.find_vendor(vendor_name)
        if not vid:
            return {"matches": []}

        def _hist_vendor_id(h):
            h_vid, _ = self.find_vendor(h["vendor_name"])
            return h_vid

        matches = [h for h in self.history if _hist_vendor_id(h) == vid
                   and abs(float(h["amount"]) - float(amount)) < 0.005]
        return {"matches": matches}

    def tool_get_policies(self):
        return {"policies": self.policies}

    def tool_record_decision(self, invoice_id: str, decision: str, reason: str):
        if decision not in VALID_DECISIONS:
            return {"error": f"decision must be one of {sorted(VALID_DECISIONS)}"}
        if not self.get_invoice(invoice_id):
            return {"error": f"Invoice {invoice_id} not found"}
        self.decisions[invoice_id] = {"decision": decision, "reason": (reason or "")[:500]}

# ---- Anthropic tool schemas for the worker agent ----
TOOL_SPECS = [
    {"name": "list_invoices", "description": "List all invoices waiting in the AP inbox.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_invoice", "description": "Get the full details of one invoice by id.",
     "input_schema": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]}},
    {"name": "lookup_vendor", "description": "Look up a vendor by name (handles common name variants) in the vendor master. Returns risk flag if present.",
     "input_schema": {"type": "object", "properties": {"vendor_name": {"type": "string"}}, "required": ["vendor_name"]}},
    {"name": "lookup_po", "description": "Look up a purchase order by number. Returns vendor, amount and open/closed status.",
     "input_schema": {"type": "object", "properties": {"po_number": {"type": "string"}}, "required": ["po_number"]}},
    {"name": "lookup_invoice_history", "description": "Return prior invoices already processed for a vendor name + amount. Use this to detect duplicates.",
     "input_schema": {"type": "object", "properties": {"vendor_name": {"type": "string"}, "amount": {"type": "number"}}, "required": ["vendor_name", "amount"]}},
    {"name": "get_policies", "description": "Get the accounts-payable policy rulebook (POL-001..POL-007).",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "record_decision", "description": "Record your final triage decision for an invoice. decision: APPROVE | REJECT | ESCALATE. reason: short explanation citing the policy.",
     "input_schema": {"type": "object", "properties": {"invoice_id": {"type": "string"}, "decision": {"type": "string", "enum": ["APPROVE", "REJECT", "ESCALATE"]}, "reason": {"type": "string"}}, "required": ["invoice_id", "decision", "reason"]}},
]

TOOL_IMPLS = {
    "list_invoices": lambda ap, a: ap.tool_list_invoices(),
    "get_invoice": lambda ap, a: ap.tool_get_invoice(a.get("invoice_id", "")),
    "lookup_vendor": lambda ap, a: ap.tool_lookup_vendor(a.get("vendor_name", "")),
    "lookup_po": lambda ap, a: ap.tool_lookup_po(a.get("po_number", "")),
    "lookup_invoice_history": lambda ap, a: ap.tool_lookup_invoice_history(a.get("vendor_name", ""), a.get("amount", 0)),
    "get_policies": lambda ap, a: ap.tool_get_policies(),
    "record_decision": lambda ap, a: ap.tool_record_decision(a.get("invoice_id", ""), a.get("decision", ""), a.get("reason", "")),
}
