import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agent.config import Settings


class StoreProtocol(Protocol):
    """The store interface, structurally: any class with these methods is a
    store — no inheritance required (PEP 544). Store (SQLite) and PostgresStore
    both conform; the type checkers verify it wherever an instance meets a
    StoreProtocol-typed seam."""

    def save_report(self, user_id: str, title: str, question: str, sql: str, report_md: str) -> str: ...
    def list_reports(self, user_id: str, search: str = "", created_on: str = "") -> list[dict]: ...
    def get_reports_by_ids(self, user_id: str, ids: list[str]) -> list[dict]: ...
    def delete_by_ids(self, user_id: str, ids: list[str]) -> int: ...
    def add_preference(self, user_id: str, note: str) -> None: ...
    def get_preferences(self, user_id: str, limit: int = 10) -> list[str]: ...
    def get_active_persona(self) -> dict | None: ...
    def set_active_persona(self, name: str) -> bool: ...
    def list_personas(self) -> list[dict]: ...


# Personas are diffs against the prompt's <style_defaults> — they should only
# say what they change, never restate the defaults.
DEFAULT_PERSONAS = {
    "professional": "Concise and businesslike. Keep commentary tight. No exclamation marks.",
    "enthusiastic": (
        "Warm, energetic and encouraging. Celebrate wins, frame problems as opportunities, "
        "keep sentences short and punchy. One exclamation mark per answer is plenty."
    ),
}


class Store:
    """SQLite app store. Every method that touches reports or preferences
    filters by user_id inside the SQL — ownership is enforced here, once,
    not in callers. Personas are company-wide (requirement: non-developers
    change the tone without redeployment)."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    report_md TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS personas (
                    name TEXT PRIMARY KEY,
                    instructions TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0
                )"""
            )
            for name, instructions in DEFAULT_PERSONAS.items():
                conn.execute("INSERT OR IGNORE INTO personas (name, instructions) VALUES (?, ?)", (name, instructions))
            active = conn.execute("SELECT COUNT(*) FROM personas WHERE is_active = 1").fetchone()[0]
            if not active:
                conn.execute("UPDATE personas SET is_active = 1 WHERE name = 'professional'")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_report(self, user_id: str, title: str, question: str, sql: str, report_md: str) -> str:
        report_id = uuid.uuid4().hex[:8]
        with closing(self._conn()) as conn, conn:
            conn.execute(
                "INSERT INTO reports (id, user_id, title, question, sql, report_md) VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, user_id, title, question, sql, report_md),
            )
        return report_id

    def list_reports(self, user_id: str, search: str = "", created_on: str = "") -> list[dict]:
        sql = "SELECT id, title, question, created_at FROM reports WHERE user_id = ?"
        params: list = [user_id]
        if search:
            sql += " AND (title LIKE ? OR question LIKE ? OR report_md LIKE ?)"
            like = f"%{search}%"
            params += [like, like, like]
        if created_on:
            sql += " AND date(created_at) = ?"
            params.append(created_on)
        sql += " ORDER BY created_at DESC"
        with closing(self._conn()) as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def get_reports_by_ids(self, user_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with closing(self._conn()) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    f"SELECT id, title, created_at FROM reports WHERE user_id = ? AND id IN ({placeholders})",
                    [user_id, *ids],
                )
            ]

    def delete_by_ids(self, user_id: str, ids: list[str]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with closing(self._conn()) as conn, conn:
            cursor = conn.execute(f"DELETE FROM reports WHERE user_id = ? AND id IN ({placeholders})", [user_id, *ids])
            return cursor.rowcount

    def add_preference(self, user_id: str, note: str) -> None:
        with closing(self._conn()) as conn, conn:
            conn.execute("INSERT INTO preferences (user_id, note) VALUES (?, ?)", (user_id, note))

    def get_preferences(self, user_id: str, limit: int = 10) -> list[str]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT note FROM preferences WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        return [row["note"] for row in reversed(rows)]

    def get_active_persona(self) -> dict | None:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT name, instructions FROM personas WHERE is_active = 1 LIMIT 1").fetchone()
        return dict(row) if row else None

    def set_active_persona(self, name: str) -> bool:
        # Existence check FIRST: the update sets is_active for every row, so
        # running it with an unknown name would deactivate all personas.
        with closing(self._conn()) as conn, conn:
            hit = conn.execute("SELECT COUNT(*) FROM personas WHERE name = ?", (name,)).fetchone()[0]
            if not hit:
                return False
            conn.execute("UPDATE personas SET is_active = (name = ?)", (name,))
        return True

    def list_personas(self) -> list[dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT name, is_active FROM personas ORDER BY name").fetchall()
        return [dict(row) for row in rows]


def make_store(settings: "Settings") -> StoreProtocol:
    """SQLite by default (zero-infra reviewer path, unit tests); Postgres when
    DATABASE_URL is set. Lazy import keeps psycopg optional on the SQLite path."""
    if settings.database_url:
        from agent.store_pg import PostgresStore

        return PostgresStore(settings.database_url)
    return Store(settings.sqlite_path)
