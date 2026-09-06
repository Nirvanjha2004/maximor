"""The Referee: deterministic, automatic scoring of every run.

Grades recorded decisions against fixed expected answers (never seen by the
worker agent), producing the accuracy metric and structured failure reports
that the Coach consumes.
"""
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load_expected():
    import json
    return json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def grade(ap) -> dict:
    """Grade all decisions in the AP system. Returns run results + failures."""
    expected = load_expected()
    results, failures = [], []
    for exp in expected:
        inv = ap.get_invoice(exp["invoice_id"])
        got = ap.decisions.get(exp["invoice_id"], {}).get("decision", "NO_DECISION")
        got_reason = ap.decisions.get(exp["invoice_id"], {}).get("reason", "")
        ok = got == exp["expected_decision"]
        row = {"invoice_id": exp["invoice_id"], "expected": exp["expected_decision"],
               "got": got, "correct": ok, "reason_tag": exp["reason_tag"],
               "agent_reason": got_reason}
        results.append(row)
        if not ok:
            failures.append(row)
    correct = sum(1 for r in results if r["correct"])
    return {"correct": correct, "total": len(results),
            "accuracy": round(correct / len(results), 4), "results": results,
            "failures": failures}
