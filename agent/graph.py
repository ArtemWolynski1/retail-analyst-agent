import sqlite3
from pathlib import Path

from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.config import Settings
from agent.llm import build_chat_model
from agent.runtime import RuntimeContext
from agent.tools import build_tools


def open_checkpointer(settings: Settings) -> SqliteSaver:
    path = Path(settings.checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def build_agent(ctx: RuntimeContext, checkpointer: SqliteSaver, system_prompt: str, role: str = "agent"):
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
