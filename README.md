# Retail analyst agent

A CLI chat agent for non-technical retail managers. Ask questions in plain English
("why are users in Texas underspending compared to California?") — the agent plans and
runs BigQuery SQL against the `thelook_ecommerce` dataset, self-heals failed queries,
deterministically masks customer PII, and manages a saved-reports library with a
confirmation-gated delete flow.

Built with LangGraph / LangChain v1 and Gemini. Design details: [docs/architecture.md](docs/architecture.md).

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
```

Saved reports and conversation state persist in `./.data` between runs.

## Project layout

```
agent/
├── cli.py       # chat REPL, confirmation UX
├── graph.py     # LangGraph agent wiring
├── llm.py       # per-role model init (right-sizing hook)
├── bq.py        # BigQuery client: dry-run + byte-capped execution
├── config.py    # env-driven settings
├── smoke.py     # setup validator
├── tools/       # run_sql, get_schema, reports, preferences
├── safety/      # SQL guard, PII masker, scope guard
├── persona.py   # DB-backed personas, hot-swappable
└── store.py     # SQLite: reports, prefs, personas
```
