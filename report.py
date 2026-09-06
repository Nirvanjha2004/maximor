"""Print a markdown + ASCII summary of results/ for the README/video.

Usage: python report.py
Reads results/run_*.json and results/summary.json (if present).
"""
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def bar(pct, width=20):
    n = int(round(pct * width))
    return "#" * n + "-" * (width - n)


def main():
    runs = sorted(RESULTS.glob("run_*.json"),
                  key=lambda p: int(p.stem.split("_")[1]))
    if not runs:
        print("No results yet. Run: python run.py --mock --runs 3 --fresh")
        return
    print("| Run | Mode | Accuracy | Avg tools | Lessons (total) |")
    print("|-----|------|----------|-----------|-----------------|")
    for p in runs:
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"| {d['run']} | {d.get('mode','')} | {d['accuracy']:.1%} "
              f"({d['correct']}/{d['total']}) | {d.get('avg_tool_calls','?')} | "
              f"+{d.get('lessons_added',0)} ({d.get('total_lessons',0)}) |")
    print("\nAccuracy curve:")
    for p in runs:
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"  run {d['run']} {bar(d['accuracy'])} {d['accuracy']:.1%}")
    s = RESULTS / "summary.json"
    if s.exists():
        o = json.loads(s.read_text(encoding="utf-8"))
        print(f"\nGain: {o.get('first_accuracy',0):.1%} -> "
              f"{o.get('last_accuracy',0):.1%} (+{o.get('gain_pp',0)}pp) "
              f"| tokens={o.get('total_tokens_in',0)}in/"
              f"{o.get('total_tokens_out',0)}out | cost=$0.00")


if __name__ == "__main__":
    main()
