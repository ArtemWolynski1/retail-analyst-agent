"""Setup validator: checks env vars, BigQuery access, and the Gemini key.

Run `python -m agent.smoke` after following the README setup. Each failing
check prints the exact command that fixes it.
"""

import sys

from agent.config import Settings, load_settings

OK = "✓"
FAIL = "✗"


def main() -> int:
    settings = load_settings()
    failures = 0

    if settings.gcp_project:
        print(f"{OK} GOOGLE_CLOUD_PROJECT = {settings.gcp_project}")
    else:
        failures += 1
        print(f"{FAIL} GOOGLE_CLOUD_PROJECT is not set — copy .env.example to .env and fill it in")

    if settings.google_api_key:
        print(f"{OK} GOOGLE_API_KEY is set")
    else:
        failures += 1
        print(f"{FAIL} GOOGLE_API_KEY is not set — create one at https://aistudio.google.com/apikey")

    if settings.gcp_project:
        failures += check_bigquery(settings)
    if settings.google_api_key:
        failures += check_gemini(settings)

    print()
    if failures:
        print(f"{failures} check(s) failed — fix the items above, then re-run: python -m agent.smoke")
        return 1
    print("All checks passed — the agent has everything it needs.")
    return 0


def check_bigquery(settings: Settings) -> int:
    # Imports stay inside the checks so one broken dependency or credential
    # doesn't mask the result of the other check.
    from agent.bq import make_client, run_query

    sql = f"SELECT table_id, row_count FROM `{settings.bq_dataset}.__TABLES__` ORDER BY table_id"
    try:
        client = make_client(settings)
        rows = run_query(client, sql, settings)
    except Exception as exc:
        print(f"{FAIL} BigQuery: {exc}")
        print("  Fix: gcloud auth application-default login")
        return 1
    counts = {row.table_id: row.row_count for row in rows}
    for table in ("orders", "order_items", "products", "users"):
        print(f"{OK} BigQuery {settings.bq_dataset}.{table}: {counts.get(table, 0):,} rows")
    return 0


def check_gemini(settings: Settings) -> int:
    from agent.llm import build_chat_model

    try:
        reply = build_chat_model(settings).invoke("Reply with exactly: ok")
    except Exception as exc:
        print(f"{FAIL} Gemini ({settings.agent_model}): {exc}")
        print("  Fix: verify GOOGLE_API_KEY and the model names in .env")
        return 1
    print(f"{OK} Gemini {settings.agent_model} replied: {reply.content!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
