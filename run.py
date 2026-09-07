"""EvolveAP learning loop runner (Track 1: Automated Agent Engineering).

Modes:
  python run.py --mock --runs 3        # offline pipeline self-test, no API key
  python run.py --live --runs 3        # OpenRouter free models (needs OPENROUTER_API_KEY)
  python run.py --live --runs 3 --fresh  # wipe results/playbook and start over

Each run: Worker triages all invoices (with tag-routed playbook memory)
  -> Referee grades vs expected.json
  -> Coach writes lessons -> Playbook grows.
Saves results/run_<n>.json, playbook snapshots, and results/summary.json.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.tools import APSystem
from agent.playbook import Playbook, observable_tags
from agent.referee import grade
from agent.mock import run_invoice_mock, coach_mock
from agent.coach import coach_llm, ensure_tags

RESULTS = ROOT / "results"


def load_invoices():
    return json.loads((ROOT / "data" / "invoices.json").read_text(encoding="utf-8"))


def run_loop(mode="mock", runs=3, fresh=False, max_lessons=4):
    from agent import config as cfg
    if fresh and RESULTS.exists():
        import shutil
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    playbook = Playbook()
    invoices = load_invoices()
    invoices_by_id = {inv["id"]: inv for inv in invoices}
    # Resume numbering when not fresh: continue after highest existing run_*.json
    start_no = 1
    summaries = []
    if not fresh:
        existing = sorted([int(p.stem.split("_")[1]) for p in RESULTS.glob("run_*.json")
                           if p.stem.split("_")[1].isdigit()], reverse=False)
        if existing and mode != "mock":
            start_no = max(existing) + 1
            # preload prior summaries for overall stats
            for n in existing:
                try:
                    d = json.loads((RESULTS / f"run_{n}.json").read_text(encoding="utf-8"))
                    summaries.append({k: d[k] for k in (
                        "run", "mode", "accuracy", "correct", "total", "failures",
                        "lessons_added", "total_lessons", "avg_tool_calls",
                        "tokens_in", "tokens_out", "cost_usd", "timestamp") if k in d})
                except Exception:
                    pass
    total_in = total_out = total_tools = 0
    t_start = time.time()

    for run_no in range(start_no, start_no + runs):
        ap = APSystem()
        per_invoice = []
        # Voyager-style curriculum: easy invoices first so early lessons compound.
        # Within-run order does not affect that run's accuracy (memory updates
        # after the run), but it stabilises which lessons get reinforced first.
        def _curriculum_key(inv):
            amt = float(inv.get("amount", 0))
            po = (inv.get("po_number") or "").strip()
            return (0 if amt <= 500 else 1, 0 if po else 1, inv.get("id", ""))
        ordered = sorted(invoices, key=_curriculum_key)
        for inv in ordered:
            tags = observable_tags(ap, inv)
            pb_text = playbook.render(tags, current_run=run_no)
            retrieved = playbook.relevant(tags, current_run=run_no)
            if mode == "mock":
                from agent.referee import load_expected
                tag = next(e["reason_tag"] for e in load_expected()
                           if e["invoice_id"] == inv["id"])
                m = run_invoice_mock(ap, inv, pb_text, retrieved, tag)
            else:
                from agent.worker_or import run_invoice_or
                m = run_invoice_or(ap, inv, pb_text)
            m["playbook_lessons_used"] = len(retrieved)
            m["playbook_lesson_ids"] = [l.get("id") for l in retrieved]
            per_invoice.append(m)
            total_in += m.get("tokens_in", 0)
            total_out += m.get("tokens_out", 0)
            total_tools += m.get("tool_calls", 0)
        graded = grade(ap)
        # Fine-grained credit assignment: only lessons decisive for the graded
        # outcome (tags contain the invoice's reason_tag) earn a vote; merely
        # injected lessons are skipped instead of free-riding.
        correct_by_id = {r["invoice_id"]: r["correct"] for r in graded["results"]}
        tag_by_id = {r["invoice_id"]: r.get("reason_tag", "") for r in graded["results"]}
        vote_totals = {"upvoted": 0, "downvoted": 0, "skipped": 0, "pruned": 0}
        for m in per_invoice:
            st = playbook.apply_outcome(m.get("playbook_lesson_ids", []),
                                        bool(correct_by_id.get(m["invoice_id"], False)),
                                        run_no,
                                        reason_tag=tag_by_id.get(m["invoice_id"], ""))
            for k in vote_totals:
                vote_totals[k] += st.get(k, 0)
        if playbook.migrated_pruned or playbook.migrated_edited:
            print(f"   playbook: pruned {playbook.migrated_pruned} + edited "
                  f"{playbook.migrated_edited} POL-contradicting lesson(s) on load")
        # Coach step (Reflexion-style: give the coach the failed thought trace
        # so lessons fix the credit-assignment point, not just the outcome).
        failures = graded["failures"]
        thoughts_by_id = {m["invoice_id"]: m.get("thoughts", []) or []
                          for m in per_invoice}
        for f in failures:
            th = thoughts_by_id.get(f["invoice_id"], [])
            if th and "thought_trace" not in f:
                f["thought_trace"] = th[:3]
        if mode == "mock":
            lessons = coach_mock(failures, lambda inv: observable_tags(APSystem(), inv), run_no)[:max_lessons]
        else:
            # Fresh APSystem for tag derivation (observable features only)
            tag_ap = APSystem()
            raw = coach_llm(failures, lambda inv: observable_tags(tag_ap, inv),
                            invoices_by_id, max_lessons=max_lessons)
            lessons = ensure_tags(raw, failures, lambda inv: observable_tags(tag_ap, inv),
                                  invoices_by_id)[:max_lessons]
        added = playbook.add_lessons(lessons, run_no) if failures else 0
        filtered = list(playbook.last_filtered) if failures else []
        if filtered:
            print(f"   coach filter: rejected {len(filtered)} POL-contradicting lesson(s)")
            for fl in filtered[:3]:
                print(f"      REJECTED [{fl['reason']}] {(fl['lesson'])[:100]}")
        playbook.save()
        playbook.snapshot(run_no)
        avg_tools = round(sum(m["tool_calls"] for m in per_invoice) / len(per_invoice), 2)
        vote_line = (f"votes +{vote_totals['upvoted']}/-{vote_totals['downvoted']} "
                     f"skip {vote_totals['skipped']} prune {vote_totals['pruned']}")
        summary = {
            "run": run_no, "mode": mode,
            "accuracy": graded["accuracy"], "correct": graded["correct"],
            "total": graded["total"], "failures": len(failures),
            "lessons_added": added, "total_lessons": len(playbook.lessons),
            "lessons_filtered": len(filtered), "votes": vote_totals,
            "avg_tool_calls": avg_tools,
            "tokens_in": sum(m.get("tokens_in", 0) for m in per_invoice),
            "tokens_out": sum(m.get("tokens_out", 0) for m in per_invoice),
            "cost_usd": round(sum(m.get("cost_usd", 0.0) for m in per_invoice), 6),
            "results": graded["results"],
            "new_lessons": lessons if failures else [],
            "per_invoice": per_invoice,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (RESULTS / f"run_{run_no}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append({k: summary[k] for k in (
            "run", "mode", "accuracy", "correct", "total", "failures",
            "lessons_added", "total_lessons", "avg_tool_calls",
            "tokens_in", "tokens_out", "cost_usd", "timestamp")})
        print(f"[run {run_no}] accuracy={graded['accuracy']:.2%} "
              f"({graded['correct']}/{graded['total']}) "
              f"failures={len(failures)} +{added} lessons "
              f"(total {len(playbook.lessons)}) avg_tools={avg_tools} {vote_line}")
        for f in failures[:6]:
            print(f"   FAIL {f['invoice_id']}: got={f['got']} want={f['expected']} [{f['reason_tag']}]")

    overall = {
        "mode": mode, "runs": runs,
        "started": summaries[0]["timestamp"] if summaries else "",
        "finished": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - t_start, 1),
        "first_accuracy": summaries[0]["accuracy"] if summaries else 0,
        "last_accuracy": summaries[-1]["accuracy"] if summaries else 0,
        "gain_pp": round(((summaries[-1]["accuracy"] - summaries[0]["accuracy"]) * 100), 1) if len(summaries) > 1 else 0,
        "total_tokens_in": total_in, "total_tokens_out": total_out,
        "total_tool_calls": total_tools,
        "total_cost_usd": 0.0,
        "model": cfg.OPENROUTER_MODEL if mode == "live" else "mock-simulation",
        "runs_summary": summaries,
    }
    (RESULTS / "summary.json").write_text(json.dumps(overall, indent=2), encoding="utf-8")
    print(f"\nDone: {overall['first_accuracy']:.2%} -> {overall['last_accuracy']:.2%} "
          f"(+{overall['gain_pp']}pp) tokens={total_in}in/{total_out}out cost=$0.00 (free models)")
    return overall


def main():
    p = argparse.ArgumentParser(description="EvolveAP learning-loop runner")
    p.add_argument("--mock", action="store_true", help="offline simulation (no API key)")
    p.add_argument("--live", action="store_true", help="OpenRouter free models")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--fresh", action="store_true", help="wipe results/ first")
    p.add_argument("--max-lessons", type=int, default=4)
    a = p.parse_args()
    mode = "live" if a.live else "mock"
    run_loop(mode=mode, runs=a.runs, fresh=a.fresh, max_lessons=a.max_lessons)


if __name__ == "__main__":
    main()
