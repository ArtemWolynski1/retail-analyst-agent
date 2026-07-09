from langchain_core.tools import tool

from agent.bq import run_query
from agent.config import Settings
from agent.runtime import RuntimeContext, SchemaCache


def fetch_schema(client, settings: Settings) -> SchemaCache:
    sql = (
        f"SELECT table_name, column_name, data_type "
        f"FROM `{settings.bq_dataset}`.INFORMATION_SCHEMA.COLUMNS "
        f"ORDER BY table_name, ordinal_position"
    )
    tables: dict[str, list[tuple[str, str]]] = {}
    for row in run_query(client, sql, settings):
        tables.setdefault(row.table_name, []).append((row.column_name, row.data_type))
    summary = "\n".join(
        f"{name}({', '.join(f'{col} {dtype}' for col, dtype in cols)})" for name, cols in sorted(tables.items())
    )
    return SchemaCache(tables=tables, summary=summary)


def build_get_schema(ctx: RuntimeContext):
    @tool
    def get_schema(table: str = "") -> str:
        """Describe the tables and columns of the retail dataset.

        Args:
            table: a specific table name, or empty for an overview of all tables.
        """
        if not table:
            return ctx.schema.summary
        cols = ctx.schema.tables.get(table.strip().lower())
        if cols is None:
            return f"Unknown table '{table}'. Available: {', '.join(sorted(ctx.schema.tables))}."
        return "\n".join(f"{col}: {dtype}" for col, dtype in cols)

    return get_schema
