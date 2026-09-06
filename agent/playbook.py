"""The playbook: the agent's growing memory of lessons learned from failures.

This is the "memory growing" evidence for Track 1: lessons are written by the
Coach after each run, tagged, and only *relevant* lessons are injected into the
next run's prompt (tag-based retrieval keeps cost and speed under control).
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"

# Tag vocabulary used for retrieval routing.
TAG_VOCAB = [
    "small_amount", "tolerance", "missing_po", "invalid_po", "closed_po",
    "risk_vendor", "unknown_vendor", "name_variant", "duplicate", "recurring",
]

# Failure categories (allowed as lesson tags so the mock pipeline can route them).
REASON_TAGS = [
    "small_auto", "name_variant", "tolerance_breach", "po_match", "missing_po",
    "risk_vendor", "recurring_legit", "closed_po", "unknown_vendor", "duplicate",
]


MAX_LESSONS = 40


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def observable_tags(ap, inv) -> set:
    """Derive routing tags for an invoice from *observable* features only.

    This mirrors how a production memory system routes which memories to load:
    cheap, local checks on the task inputs - no peeking at expected answers.
    """
    tags = set()
    vid, vendor = ap.find_vendor(inv["vendor_name"])

    if not vendor:
        tags.update({"unknown_vendor", "name_variant"})
    elif vendor.get("risk_flag"):
        tags.add("risk_vendor")

    po = ap.pos.get((inv.get("po_number") or "").strip().upper())
    if not inv.get("po_number"):
        tags.add("missing_po")
    elif not po:
        tags.update({"missing_po", "invalid_po"})
    elif po.get("status") != "open":
        tags.add("closed_po")

    if float(inv["amount"]) <= 500:
        tags.add("small_amount")
    else:
        tags.add("tolerance")

    # duplicate / recurring routing via prior history
    if vid:
        for h in ap.history:
            h_vid, _ = ap.find_vendor(h["vendor_name"])
            if h_vid == vid and abs(float(h["amount"]) - float(inv["amount"])) < 0.005:
                d1 = date.fromisoformat(inv["invoice_date"])
                d2 = date.fromisoformat(h["processed_date"])
                if (d1 - d2).days <= 30:
                    tags.add("duplicate")
                else:
                    tags.add("recurring")
    return tags


class Playbook:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else RESULTS / "playbook.json"
        self.lessons = []
        if self.path.exists():
            self.lessons = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=2), encoding="utf-8")

    def add_lessons(self, lessons, run_no: int) -> int:
        """Append new lessons (deduped, capped). Returns count actually added."""
        added = 0
        seen = {normalize_name(l["lesson"])[:60] for l in self.lessons}
        for l in lessons:
            lesson = (l.get("lesson") or "").strip()
            if not lesson:
                continue
            key = normalize_name(lesson)[:60]
            if key in seen:
                continue
            seen.add(key)
            tags = [t for t in (l.get("tags") or []) if t in TAG_VOCAB or t in REASON_TAGS]
            self.lessons.append({
                "id": f"L{len(self.lessons) + 1:02d}",
                "lesson": lesson,
                "tags": sorted(set(tags)),
                "added_run": run_no,
            })
            added += 1
            if len(self.lessons) >= MAX_LESSONS:
                break
        return added

    def relevant(self, tags: set) -> list:
        """Only load lessons whose tags intersect this invoice's observable tags."""
        if not tags:
            return []
        return [l for l in self.lessons if set(l["tags"]) & tags]

    def render(self, tags: set) -> str:
        rel = self.relevant(tags)
        if not rel:
            return ""
        lines = ["=== AP PLAYBOOK - lessons learned from previous runs (follow these) ==="]
        for l in rel:
            lines.append(f"[{l['id']}] {l['lesson']}")
        lines.append("=== END PLAYBOOK ===")
        return "\n".join(lines)

    def snapshot(self, run_no: int):
        RESULTS.mkdir(parents=True, exist_ok=True)
        snap = RESULTS / f"playbook_run_{run_no}.json"
        snap.write_text(json.dumps({"run": run_no, "total_lessons": len(self.lessons),
                                    "lessons": self.lessons}, indent=2), encoding="utf-8")
