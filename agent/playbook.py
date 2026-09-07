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
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                raw = []
            # Backfill ExpeL-style bookkeeping for lessons written before voting.
            for i, l in enumerate(raw):
                l.setdefault("importance", 2)
                l.setdefault("successes", 0)
                l.setdefault("failures", 0)
                l.setdefault("added_run", l.get("added_run", 0))
                l.setdefault("last_used_run", l.get("added_run", 0))
                l.setdefault("id", f"L{i + 1:02d}")
            self.lessons = raw

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=2), encoding="utf-8")

    def add_lessons(self, lessons, run_no: int) -> int:
        """Append new lessons (ExpeL-style voting dedup, capped). Returns added.

        Duplicate lesson text UPVOTEs the existing lesson (importance +1)
        instead of creating a copy; brand-new lessons start at importance 2.
        Lessons DOWNVOTEd to 0 are pruned; when over MAX_LESSONS the lowest
        importance / oldest lessons are evicted first.
        """
        added = 0
        by_key = {normalize_name(l["lesson"])[:60]: l for l in self.lessons}
        for l in lessons:
            lesson = (l.get("lesson") or "").strip()
            if not lesson:
                continue
            key = normalize_name(lesson)[:60]
            tags = [t for t in (l.get("tags") or []) if t in TAG_VOCAB or t in REASON_TAGS]
            if key in by_key:
                # Duplicate idea -> reinforce instead of duplicating (ExpeL UPVOTE).
                existing = by_key[key]
                existing["importance"] = int(existing.get("importance", 2)) + 1
                merged = sorted(set(existing.get("tags", [])) | set(tags))
                existing["tags"] = merged
                existing["last_used_run"] = run_no
                continue
            by_key[key] = {
                "id": f"L{len(self.lessons) + added + 1:02d}",
                "lesson": lesson,
                "tags": sorted(set(tags)),
                "added_run": run_no,
                "last_used_run": run_no,
                "importance": 2,
                "successes": 0,
                "failures": 0,
            }
            added += 1
        # Rebuild list preserving insertion order, then enforce cap by eviction.
        self.lessons = list(by_key.values())
        if len(self.lessons) > MAX_LESSONS:
            self.lessons.sort(key=lambda l: (int(l.get("importance", 0)),
                                             int(l.get("last_used_run", 0))))
            self.lessons = self.lessons[len(self.lessons) - MAX_LESSONS:]
        # Renumber IDs to stay stable and readable.
        for i, l in enumerate(self.lessons):
            l["id"] = f"L{i + 1:02d}"
        return added

    def apply_outcome(self, lesson_ids, correct: bool, run_no: int):
        """ExpeL-style credit assignment: lessons that helped get UPVOTEd.

        Called once per invoice after the Referee grades. Correct decisions
        reinforce the lessons used; incorrect ones DOWNVOTE them. Lessons at
        importance 0 are pruned immediately so bad advice cannot propagate
        (cf. Reflexion/ExpeL memory-quality warnings).
        """
        if not lesson_ids:
            return
        keep = []
        ids = set(lesson_ids)
        for l in self.lessons:
            if l.get("id") not in ids:
                keep.append(l)
                continue
            l["last_used_run"] = run_no
            if correct:
                l["importance"] = int(l.get("importance", 2)) + 1
                l["successes"] = int(l.get("successes", 0)) + 1
            else:
                l["importance"] = int(l.get("importance", 2)) - 1
                l["failures"] = int(l.get("failures", 0)) + 1
            if int(l["importance"]) > 0:
                keep.append(l)
            # else: pruned — bad memory is worse than no memory.
        self.lessons = keep
        for i, l in enumerate(self.lessons):
            l["id"] = f"L{i + 1:02d}"

    def score(self, lesson, tags: set, current_run: int) -> float:
        """Generative-Agents-style score: relevance + importance + recency."""
        overlap = len(set(lesson.get("tags", [])) & tags)
        if overlap == 0:
            return 0.0
        importance = int(lesson.get("importance", 2))
        recency = max(0, 3 - (current_run - int(lesson.get("last_used_run", 0))))
        return 2.0 * overlap + 0.5 * importance + 0.25 * recency

    def relevant(self, tags: set, current_run: int = 0, top_k: int = 0) -> list:
        """Load lessons whose tags intersect the invoice tags, ranked by score.

        Tag overlap is still the hard filter (cost/speed control), but ranking
        by score() puts the most relevant + proven + recent lessons first.
        top_k=0 means no limit (backward compatible); pass top_k to bound
        prompt size per invoice.
        """
        if not tags:
            return []
        scored = [(self.score(l, tags, current_run), l)
                  for l in self.lessons if set(l["tags"]) & tags]
        scored.sort(key=lambda p: (-p[0], p[1].get("id", "")))
        lessons = [l for _, l in scored]
        return lessons[:top_k] if top_k else lessons

    def render(self, tags: set, current_run: int = 0, top_k: int = 0) -> str:
        rel = self.relevant(tags, current_run=current_run, top_k=top_k)
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
