from concurrent.futures import TimeoutError as FutureTimeoutError

from google.api_core import exceptions as gexc
from langchain_core.tools import tool

from agent.bq import dry_run, run_query
from agent.runtime import RuntimeContext
from agent.safety import sql_guard

CELL_MAX_CHARS = 80


def build_run_sql(ctx: RuntimeContext):
    @tool
    def run_sql(sql: str, purpose: str) -> str:
        """Execute one read-only BigQuery SELECT against the retail dataset and return the rows.

        Args:
            sql: a single SELECT statement (BigQuery SQL). Prefer fully-qualified
                table names like `bigquery-public-data.thelook_ecommerce.orders`.
            purpose: one line describing what this query is meant to find out.
        """
        settings = ctx.settings
        if ctx.budget.sql_attempts >= settings.sql_attempts_per_turn:
            return (
                "SQL budget for this question is exhausted. Summarize the findings you already have, "
                "or ask the user to refine the question."
            )
        ctx.budget.sql_attempts += 1

        guarded = sql_guard.validate(sql, settings)
        if not guarded.ok:
            return f"Query rejected: {guarded.error}"

        try:
            estimated = dry_run(ctx.bq, guarded.sql)
        except gexc.BadRequest as e:
            return f"BigQuery rejected the query: {e.message or e}. Fix the SQL and retry."
        except gexc.NotFound as e:
            return f"BigQuery could not find a referenced object: {e.message or e}. Check names with get_schema."

        if estimated > settings.max_bytes_billed:
            return (
                f"Query would scan {estimated / 1e6:.0f} MB, over the {settings.max_bytes_billed / 1e6:.0f} MB cap. "
                "Select fewer columns or narrow the date range."
            )

        try:
            rows = run_query(ctx.bq, guarded.sql, settings)
        except FutureTimeoutError:
            return "Query timed out after 30s. Simplify or narrow it."
        except gexc.GoogleAPICallError as e:
            return f"BigQuery error while executing: {e.message or e}. Fix the SQL and retry."

        return _render(rows, estimated, settings)

    return run_sql


def _render(rows, estimated_bytes: int, settings) -> str:
    if not rows:
        return (
            "The query ran successfully and returned 0 rows. If a mistaken filter is plausible, revise it once; "
            "otherwise report the absence of data honestly — it may be the correct answer."
        )
    columns = list(rows[0].keys())
    shown = rows[: settings.max_result_rows]
    lines = [" | ".join(columns)]
    for row in shown:
        lines.append(" | ".join(_cell(row[col]) for col in columns))
    footer = f"rows: {len(shown)} of {len(rows)} | scanned (est): {estimated_bytes / 1e6:.1f} MB"
    return "\n".join(lines) + "\n" + footer


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= CELL_MAX_CHARS else text[: CELL_MAX_CHARS - 1] + "…"
