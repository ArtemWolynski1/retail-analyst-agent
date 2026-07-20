import sqlite3
from pathlib import Path

from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.config import Settings
from agent.llm import build_chat_model
from agent.runtime import RuntimeContext
from agent.tools import build_tools


def open_checkpointer(settings: Settings) -> BaseCheckpointSaver:
    if settings.database_url:
        # PostgresSaver requires an autocommit dict_row connection for setup()
        # (it runs its own DDL/migrations); prepare_threshold=0 keeps it
        # compatible with transaction-pooling proxies like pgbouncer.
        from typing import cast

        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import DictRow, dict_row

        # cast: psycopg's connect() overloads resolve to a Row union the
        # checkers can't narrow, but row_factory=dict_row guarantees DictRow.
        conn = cast(
            "Connection[DictRow]",
            Connection.connect(settings.database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row),
        )
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    path = Path(settings.checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def build_agent(ctx: RuntimeContext, checkpointer: BaseCheckpointSaver, system_prompt: str, role: str = "agent"):
    """Rebuilt every turn: the system prompt carries persona/prefs, and per-turn
    assembly is what makes them hot-reloadable without restarts. Conversation
    state survives rebuilds — it lives in the checkpointer, keyed by thread_id.
    The same property powers failover: a fallback-model agent resumes the exact
    checkpointed state the primary died in."""
    return create_agent(
        build_chat_model(ctx.settings, role=role, include_thoughts=ctx.debug),
        tools=build_tools(ctx),
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )
