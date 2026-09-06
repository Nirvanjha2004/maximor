# SUBMIT.md — Devpost submission checklist (Track 1)

* **Selected track:** Track 1 — Automated Agent Engineering
* **Problem + users:** Finance teams drown in vendor invoices; new hires and
  static bots mis-file them (duplicates paid, risk flags missed, wrong
  rejections). EvolveAP is a triage agent that teaches itself the company's
  contextual rules from tool data.
* **Working project:** this repo, built during the hackathon with AO.
  `python run.py --mock --runs 3 --fresh` reproduces the loop offline;
  `python run.py --live --runs 1` validates with a real free model.
* **GitHub repo:** https://github.com/Nirvanjha2004/maximor (code + setup in README)
* **Demo video (3–5 min, public):** follow `DEMO.md` — must show the working
  end-to-end loop, the accuracy curve, and the AO dashboard + session count.
* **Architecture / tools / workflow / eval:**
  Worker (ReAct JSON tool loop, `agent/worker_or.py`) → Referee (deterministic
  grading vs `data/expected.json`, `agent/referee.py`) → Coach (LLM lessons,
  `agent/coach.py`) → Playbook (tag-routed memory, `agent/playbook.py`).
  Tools simulate a third-party ERP/MCP (`agent/tools.py`).
* **Measurable results:** mock 33.3% → 100% (tool calls 4.00 → 2.67); live
  86.7% → 93.3% (+6.7pp) at $0.00 on OpenRouter free models.
  Evidence: `results/run_*.json`, `results/summary.json`, `python report.py`.
* **Team members:** add every team member's name on the Devpost entry
  (all members must register individually; one project per team).
* **AO usage:** mandatory — demo must show how AO built the project, the AO
  sessions involved, and the end-to-end run. No pre-hackathon code.
