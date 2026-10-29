# Isobar — Study Navigator Agent

An AI agent that decides what a student should study next, built around the
objective: "Maximise expected academic mark per unit of effort, while investing
deeper understanding when it has meaningful future value."

## Repository structure

```
study-navigator/
├── .env.example
├── .gitignore
├── agents-cli-manifest.yaml
├── deploy_manifest.json
├── Dockerfile
├── README.md
├── requirements.txt
├── backend/
│   ├── main.py
│   └── static/
│       └── index.html
├── docs/
│   ├── AGENTS.md
│   ├── ANOMALIES.md
│   └── BENCHMARK.md
├── evals/
│   ├── cost_analysis.py
│   ├── cost_analysis_report.json
│   ├── eval_config.json
│   ├── eval_report.json
│   ├── golden.json
│   ├── redteam.json
│   └── run_eval.py
├── scripts/
│   ├── deploy_eval_gated.py
│   └── verify_cross_session_memory.py
├── study_agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py
│   ├── db.py
│   ├── guardrails.py
│   ├── study_context.json
│   ├── tools.py
│   └── pipeline/
│       ├── __init__.py
│       ├── extractor.py
│       ├── orchestrator.py
│       ├── planner.py
│       ├── presenter.py
│       ├── reducer.py
│       ├── schema.py
│       └── tracer.py
├── tests/
│   ├── test_completion_and_revert.py
│   ├── test_harness.py
│   ├── test_memory.py
│   ├── test_metrics.py
│   ├── test_milestone2.py
│   ├── test_milestone3.py
│   ├── test_multi_turn_persistence.py
│   ├── test_persistence.py
│   ├── test_pipeline_stages.py
│   ├── test_redteam.py
│   └── test_scale_pillar.py
└── traces/
    └── .gitkeep

```


## Architecture

A 4-stage deterministic pipeline, one shared event taxonomy throughout:

**Extractor → Reducer → Planner → Presenter**

- **Extractor** (`study_agent/pipeline/extractor.py`): turns a raw message into
  a structured event. Fast regex-matching for known phrasings; falls back to an
  LLM call only when nothing matches, keeping the common case instant and free
  of network dependency.
- **Reducer** (`reducer.py`): the only part of the system that writes to
  persistent storage. Deterministic, not LLM-driven.
- **Planner** (`planner.py`): decides the next action from the reduced state
  and ground-truth academic metrics (`tools.py`).
- **Presenter** (`presenter.py`): formats the decision for chat and the UI.

## What's solid (Build, Scale)

- Multi-turn intent routing: confirm / reject / modify / revert all handled
  correctly, covered by an active regression suite (`test_harness.py`)
- Durable session persistence via `DatabaseSessionService` — confirmed to
  survive a full server restart
- Active-session guard: the agent won't stack a second proposal while one is
  already running, for both explicit check-ins and free-text input

## Govern — what exists now, and the design history behind it

An earlier version of this agent used a flexible, LLM-driven classification
approach, with a red-team adversarial eval set (`evals/redteam.json`) and five
behavioral rubrics (`evals/eval_config.json`): unapproved-action prevention,
grounded metrics use, competing-priority reasoning, fatigue-first
prioritization, and scoped execution. The architecture featured:

- **Human-in-the-Loop Confirmation Gate**: State changes (applying interventions, logging lecture progress, marking tasks complete) are staged and require explicit student confirmation before SQLite persistence.
- **Whitelist-by-Design Input Parsing**: The 4-stage pipeline uses a strict event taxonomy. Unrecognized or adversarial prompts (e.g. jailbreaks, cheating queries) fail to trigger tool actions and safely degrade to a clarifying fallback prompt without executing arbitrary model output.
- **ADK Guardrail & Model Armor Bridge**: `study_agent/guardrails.py` provides callback-level heuristic sanitization and Google Cloud Model Armor integration for ADK-compatible endpoints (`/api/adk`), verified by `tests/test_redteam.py`.

However, this became too non-deterministic in practice, with the same input could classify differently across runs. Due to time constraints, the live system was rebuilt around a deterministic regex-first pipeline with an LLM fallback only for unmatched input for a reliability tradeoff.

What's live today:

- Confirmation gates before every state-mutating action: applying an
  intervention, logging lecture progress, and marking a task complete all
  require an explicit confirm turn before anything is written to the database
- A keyword-level safety check on the one path that writes free-text user
  input to persistent storage (student preferences).

**Not rebuilt yet**: General content-safety screening across all input, and a live-running version of the richer original eval rubrics — `evals/run_eval.py` still targets the earlier ADK agent interface (`agent.py`), not the current pipeline, so those rubrics remain accurate specifications rather than currently-executing checks.

## Optimise — what exists now

- The extraction layer logs, per turn, whether it resolved via regex (no model
  call) or the LLM fallback, plus latency — see `extraction_method` and
  `elapsed_time_ms` in trace logs
- A golden eval set (`test_harness.py`) with a rubric guarding four specific
  behaviors: a safety rule, a required-confirmation rule, a format rule, and a
  refusal, each demonstrated to actually fail when its guarded behavior is
  deliberately broken

## Known limitations

- Planner logic is currently hardcoded to two specific modules (AI, DB) rather
  than generalizing over an arbitrary course load
- Completing a study block doesn't capture how many lectures it covered, so
  lecture-deficit tracking only updates from an explicit progress report, not
  from session completion alone
- New module registration isn't implemented as its own event type yet
- Some casual phrasing ("yeah let's go") and non-numeric durations ("half an
  hour") aren't reliably recognized — these degrade safely to a clarifying
  question to avoid a wrong action
- No weighted decision mechanism: the objective calls for balancing immediate
  mark impact against future subject relevance, but the planner's priority
  order is a fixed if/elif chain (urgent coursework marks at risk, then lecture
  deficit) that never actually weighs the two against each other. A module
  with low marks at risk but high future relevance will never be prioritized
  over one with marks at risk but low relevance — the "future value" half of
  the stated objective isn't implemented as a weighing mechanism, only
  referenced in generated rationale text.

## Feedbacks I would appreciate having on

1. How to generalize deterministic planning logic beyond two hardcoded modules
2. I deliberately traded a flexible, LLM-driven classification approach for a
   deterministic regex-first one because the flexible version was too
   non-deterministic to trust — I still have the original eval rubrics from
   that version (`evals/`). Is there a middle path that recovers more of that
   behavioral coverage without losing determinism for the common case?
3. Tooling or patterns for catching incomplete event-handling across files
   systematically — I hit the same bug shape repeatedly during development: an
   event type correctly defined in the schema, correctly extracted, but
   silently missing a handler in one sibling file
4. A realistic, low-latency way to add general safety screening without a
   network call on every turn
5. The gap I'd most want feedback on: translating intent into working code
   with an AI coding agent. Nearly every real bug this project had the same
   shape — the intended behavior was correctly described somewhere (a comment,
   a prompt, my own mental model) but the generated code implemented something
   narrower or different, and nothing surfaced the gap until I went looking.
   What practice closes this reliably?