from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from agent.config import Settings

ALLOWED_TABLES = {
    "orders",
    "order_items",
    "products",
    "users",
    "events",
    "inventory_items",
    "distribution_centers",
}

# Errors are phrased for the model: name the violated rule and how to proceed,
# so the agent loop can self-correct instead of flailing.
FORBIDDEN_NODES = [
    getattr(exp, name)
    for name in ("Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "TruncateTable", "Grant")
    if hasattr(exp, name)
]

DEFAULT_LIMIT = 1000


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str
    error: str | None = None


def validate(sql: str, settings: Settings) -> GuardResult:
    dataset_project, _, dataset_name = settings.bq_dataset.partition(".")
    try:
        statements = [s for s in sqlglot.parse(sql, read="bigquery") if s is not None]
    except sqlglot.errors.ParseError as e:
        return GuardResult(False, sql, f"SQL failed to parse: {e}. Rewrite the query and retry.")

    if len(statements) != 1:
        return GuardResult(False, sql, "Exactly one statement per run_sql call. Split or merge your query.")

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.Union)):
        return GuardResult(False, sql, "Only read-only SELECT statements are allowed. Rewrite as a SELECT.")

    for node_type in FORBIDDEN_NODES:
        if list(root.find_all(node_type)):
            return GuardResult(
                False, sql, f"Statement contains a forbidden {node_type.__name__.upper()} operation. Only SELECT is allowed."
            )

    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            return GuardResult(
                False,
                sql,
                f"Table '{table.name}' is not accessible. Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}. "
                "Use get_schema to inspect their columns.",
            )
        if table.catalog and table.catalog != dataset_project:
            return GuardResult(False, sql, f"Only the `{dataset_project}` project is accessible.")
        if table.db and table.db != dataset_name:
            return GuardResult(False, sql, f"Only the `{dataset_name}` dataset is accessible.")
        # Auto-qualify bare names so the model may write `orders` and still hit
        # the configured dataset (the client has no default dataset configured).
        if not table.db:
            table.set("db", exp.to_identifier(dataset_name))
        if not table.catalog:
            table.set("catalog", exp.to_identifier(dataset_project))

    if isinstance(root, exp.Select) and not root.args.get("limit"):
        root = root.limit(DEFAULT_LIMIT)

    return GuardResult(True, root.sql(dialect="bigquery"))
