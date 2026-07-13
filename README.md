# Retail analyst agent

A CLI chat agent for non-technical retail managers. Ask questions in plain English
("why are users in Texas underspending compared to California?") — the agent plans and
runs BigQuery SQL against the `thelook_ecommerce` dataset, self-heals failed queries,
deterministically masks customer PII, and manages a saved-reports library with a
confirmation-gated delete flow.

Built with LangGraph / LangChain v1 and Gemini. Design details:
[docs/architecture.md](docs/architecture.md) · Live demo captures:
[docs/transcript.md](docs/transcript.md).

## Setup

Prerequisites: Python 3.12+ (developed on 3.14), the [gcloud CLI](https://cloud.google.com/sdk/docs/install),
a GCP project you own, and a free [Gemini API key](https://aistudio.google.com/apikey).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in GOOGLE_API_KEY and GOOGLE_CLOUD_PROJECT

gcloud auth application-default login
```

Validate the setup — each failing check prints the command that fixes it:

```bash
python -m agent.smoke
```

BigQuery usage stays inside the free tier: the dataset is public, every query runs
under a hard `MAX_BYTES_BILLED` cap (200 MB default), and is dry-run first.

Two first-time gotchas the validator will surface: your GCP project must have the
BigQuery API enabled (the error includes the enable link), and Google may require
2-Step Verification on your account before it allows Cloud console actions.

If `pip install` fails with `No matching distribution found for langchain==…`
after a wall of "Ignored the following versions…", your `python3` is older than
3.10 (macOS ships 3.9) — create the venv with an explicit newer interpreter,
e.g. `python3.12 -m venv .venv`.

## Run

```bash
python -m agent.cli --user alice
```

(The chat interface lands with the main build — see the architecture doc for the plan.)

## Run with Docker (optional)

The native setup above is the primary path. Docker packages Python for you, but it
can't replace the Google auth steps: you still need `.env` filled in and
`gcloud auth application-default login` run on the host — the container reuses the
host's credentials via a read-only mount.

```bash
docker compose build
docker compose run --rm agent agent.smoke        # setup validator
docker compose run --rm agent                    # chat REPL
docker compose run --rm agent agent.cli --user alice
docker compose run --rm agent pytest -m live     # prompt-policy evals (live model)
```

Saved reports and conversation state persist in `./.data` between runs.

## Development

Modern-stack tooling, all configured in `pyproject.toml`: [Ruff](https://docs.astral.sh/ruff/)
(lint + format), **mypy and Pyrefly** (both fully green), a committed
[uv](https://docs.astral.sh/uv/) lockfile, pre-commit hooks, and CI (GitHub
Actions) running the whole gauntlet on a Python 3.12 + 3.14 matrix — the same
pip install path reviewers use.

```bash
pip install -r requirements-dev.txt    # or, with uv: uv sync
ruff check . && ruff format .          # lint + format
mypy && pyrefly check agent/           # both type checkers
pytest                                 # offline suite (48 tests)
pre-commit install                     # optional: same gates on every commit
d2 --layout elk docs/diagrams/architecture.d2 docs/diagrams/architecture.svg  # regen diagram
```

## Project layout

```
agent/
├── cli.py       # chat REPL, typed-confirmation UX, /persona /reports commands
├── graph.py     # LangGraph agent wiring (create_agent + checkpointer)
├── context.py   # system prompt assembly: policy, schema, examples, persona, prefs
├── runtime.py   # RuntimeContext all tools close over (identity, budget, trace)
├── llm.py       # per-role model init (right-sizing hook)
├── bq.py        # BigQuery client: dry-run + byte-capped execution
├── config.py    # env-driven settings
├── smoke.py     # setup validator
├── trace.py     # JSON-lines session traces
├── tools/       # run_sql, get_schema, reports, remember_preference
├── safety/      # SQL guard, PII masker
└── store.py     # SQLite: reports, preferences, personas (hot-swappable)
```
