# EvolveAP — a Self-Improving AP Triage Agent (Track 1: Automated Agent Engineering)

**Syndicate by Maximor · Track 1** — a system that designs, tests, and improves
specialized agents for tasks it has never seen before, with measurable gains.

> Layman version: we hired an intern (Worker), a teacher (Coach), an exam
> checker (Referee), and a notebook (Playbook). The intern triages invoices
> using company apps, fails, gets graded, the teacher writes lessons in the
> notebook, and next run the intern reads only the relevant pages — so
> accuracy goes up while tool-calls, tokens, and cost go down.

## The learning loop

```
Invoice inbox ──▶ WORKER (LLM + tools) ──▶ decisions
                        │                      │
              tag-routed playbook memory       ▼
                        │                  REFEREE (deterministic,
                        │                  grades vs expected.json)
                        │                      │
                        │                   failures
                        │                      ▼
                        ◀── PLAYBOOK ◀── COACH (LLM, writes tagged lessons)
                            memory grows
```

**Worker** (`agent/worker_or.py`) — ReAct JSON tool loop over a fake third-party
ERP/MCP (`agent/tools.py`): `lookup_vendor`, `lookup_po`,
`lookup_invoice_history`, `get_policies`. Works with any OpenRouter free chat
model (no native function-calling needed) + deterministic rule-assist fallback
so runs never break on flaky free tiers.

**Referee** (`agent/referee.py`) — deterministic evals: grades every decision
against `data/expected.json` (never shown to the worker). Reports accuracy +
failure rows by category (`name_variant`, `duplicate`, `risk_vendor`…).

**Coach** (`agent/coach.py`) — LLM coach reads failures, writes ≤4 short
tagged lessons per run; scripted fallback keeps the loop alive offline.

**Playbook** (`agent/playbook.py`) — growing memory (`results/playbook.json`).
Only lessons whose tags intersect an invoice's observable tags are injected —
this is the cost/speed control judges asked about.

## Measurable results

| Run | Mode | Accuracy | Avg tool calls | Lessons |
|-----|------|----------|----------------|---------|
| 1 | mock (pipeline self-test) | 33.3% (5/15) | 4.00 | +4 |
| 2 | mock | 80.0% (12/15) | 3.07 | +3 |
| 3 | mock | 100% (15/15) | 2.67 | +0 |
| 1 | **live (OpenRouter free model)** | **86.7% (13/15)** | 2.27 | +4 |
| 2 | **live** | **86.7% (13/15)** | 3.13 | +4 |
| 3 | **live** | **93.3% (14/15)** | 3.20 | +4 |

* Mock = offline pipeline self-test (simulated characteristic mistakes; proves
  the Try → Grade → Teach → Remember loop end-to-end with zero spend).
* Live = real free-model validation (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`,
  $0.00 cost, **86.7% → 93.3%, +6.7pp**). See `results/run_*.json` + `results/summary.json`.
  Run `python report.py` to reprint this table.

Tricky cases the memory learns: `ACME FREIGHT` vs `Acme Freight`
(name_variant), duplicate vs 30-day recurring billing, ±2% PO tolerance,
risk-flagged vendors, closed POs, missing/invalid POs.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # fill OPENROUTER_API_KEY (free at openrouter.ai)

python run.py --mock --runs 3 --fresh   # offline self-test, ~seconds
python run.py --live --runs 1           # real free model, ~5 min/run
```

Results land in `results/`: `run_<n>.json`, `playbook.json`,
`playbook_run_<n>.json`, `summary.json`.

## Repo map

* `run.py` — CLI orchestrator (mock/live, resume support)
* `agent/llm.py` — OpenRouter client with free-model fallbacks + reasoning-model handling
* `agent/worker_or.py` — live ReAct worker · `agent/worker.py` — Anthropic worker
* `agent/coach.py` — LLM coach · `agent/mock.py` — simulation + scripted coach
* `agent/referee.py` — deterministic grading · `agent/playbook.py` — tagged memory
* `agent/tools.py` — fake third-party AP system (stands in for MCP/REST APIs)
* `data/` — invoices, vendors, POs, policies (POL-001..007), history, expected answers

## Why this fits Track 1 (judges' questions)

* **How does it get better?** Referee → Coach → Playbook loop; accuracy curve + shrinking tool-calls prove it.
* **Self-reflection + growing memory?** `results/playbook_run_*.json` snapshots show the notebook thickening run over run.
* **Complex contextual logic from tools?** Duplicate-vs-recurring, tolerance math, risk flags — all learned from tool data, applied in later runs.
* **Cost/speed?** Tag-routed retrieval (only relevant lessons per invoice), free $0 models, token/tool/latency scoreboard per invoice.

Built with AO (Agent Orchestrator) from start to finish — see `DEMO.md` for the
3-minute video script including the AO sessions screen.
