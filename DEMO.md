# DEMO.md — 3-minute video script (do NOT record last-minute)

Total: ~3:00. Record screen + voiceover. Show AO dashboard with session count
at 2:30 (mandatory — projects without AO evidence are disqualified).

## 0:00–0:25 — Problem + idea (layman)
> "Every company drowns in vendor invoices. New hires mis-file them: they pay
> duplicates, miss risk flags, reject things they should escalate. We built
> EvolveAP: an invoice clerk that TEACHES ITSELF. An intern, a teacher, an
> exam checker, and a notebook — looping until it stops making mistakes."

Show: invoice inbox (`data/invoices.json`, 15 invoices) + policy rulebook
(`data/policies.json`, POL-001..007).

## 0:25–1:10 — Run 1 fails (the before)
Run: `python run.py --mock --runs 1 --fresh` (fast) — show terminal:
`accuracy=33.33% (5/15)`, FAIL lines: `ACME FREIGHT → ESCALATE (want APPROVE)`,
`duplicate → APPROVE (want REJECT)`, `risk vendor → APPROVE (want ESCALATE)`.
Say: "Day one intern. It has tools — vendor lookup, PO lookup, history,
policies — but no memory, so it guesses."

## 1:10–1:55 — The learning system (the how)
Show the four files + diagram:
1. **Referee** grades deterministically vs hidden answers (`results/run_1.json`).
2. **Coach** writes ≤4 tagged lessons (open `results/playbook.json` — 4 lessons).
3. **Playbook** injects only relevant lessons per invoice (tag routing = cheap).
4. Re-run: `python run.py --mock --runs 2` → 80% → 100%, avg tool calls
   4.00 → 2.67. Open `results/summary.json` + `playbook_run_*.json` snapshots.
Say: "Outputs get better through self-reflection and growing memory — exactly
what Track 1 asks for."

## 1:55–2:30 — Real-model proof (the credibility)
Show `python report.py` output: live **86.7% → 100% (+13.3pp) over 7 runs,
$0.00 cost** on OpenRouter free models. Tell the honest dip story — run 4 fell
to 80% on noisy coach lessons, the quality filter + voting fixed it, run 7 hit
15/15. Pick three invoices: INV-1001 APPROVE (POL-001), INV-1006 ESCALATE
(risk_flag POL-006), INV-1012 REJECT (duplicate caught via PO-linked vendor
resolution — `Byte Foods` is not in the vendor master).
Say: "Mock proves the loop; live proves it works with a real model for free —
and the dips prove the self-correction is real, not cherry-picked."

## 2:30–2:50 — AO build process (mandatory)
Screen-record AO dashboard: sessions used, orchestrator + workers, branches.
Say: "Built end-to-end in AO — N sessions across worker, coach, and docs.
AO ran the fleet while we kept the loop tight."

## 2:50–3:00 — Close
> "EvolveAP: give any agent third-party tools + a grading rubric, and it gets
> measurably better — 33% to 100% in three mock runs, 86.7% to 100% live,
> cheaper each time, all for $0.00. Code, evals, and playbook snapshots are
> on GitHub. Thank you."

Checklist before upload: track = Track 1, problem/users, repo link, video link,
architecture + eval method, metrics screenshot, team names.
