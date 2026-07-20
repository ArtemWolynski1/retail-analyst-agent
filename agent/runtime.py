import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from google.cloud import bigquery

from agent.config import Settings
from agent.store import StoreProtocol
from agent.trace import Trace

if TYPE_CHECKING:
    from agent.retrieval import TrioRetriever


@dataclass
class TurnBudget:
    sql_attempts: int = 0
    turn_id: str = ""


@dataclass(frozen=True)
class SchemaCache:
    tables: dict[str, list[tuple[str, str]]]
    summary: str


@dataclass(frozen=True)
class Trio:
    id: str
    question: str
    sql: str
    analyst_notes: str
    tables_used: tuple[str, ...]


@dataclass
class RuntimeContext:
    """Per-session context all tools close over.

    Identity lives here and only here — tool schemas never expose a user_id
    parameter, so the model cannot act as anyone but the session user.
    """

    settings: Settings
    bq: bigquery.Client
    user_id: str
    schema: SchemaCache
    examples: list[Trio]
    store: StoreProtocol | None = None
    retriever: "TrioRetriever | None" = None
    budget: TurnBudget = field(default_factory=TurnBudget)
    trace: Trace = field(default_factory=lambda: Trace(None))
    debug: bool = False


def load_examples(path: Path) -> list[Trio]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [
        Trio(
            id=t["id"],
            question=t["question"],
            sql=t["sql"],
            analyst_notes=t["analyst_notes"],
            tables_used=tuple(t.get("tables_used", ())),
        )
        for t in raw
    ]
