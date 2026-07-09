from agent.runtime import RuntimeContext
from agent.tools.schema import build_get_schema
from agent.tools.sql import build_run_sql


def build_tools(ctx: RuntimeContext) -> list:
    return [build_get_schema(ctx), build_run_sql(ctx)]
