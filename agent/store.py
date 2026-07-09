import sqlite3
import uuid
from contextlib import closing
from pathlib import Path


class Store:
    """SQLite app store. Every method that touches reports filters by user_id
    inside the SQL — ownership is enforced here, once, not in callers."""

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
            cursor = conn.execute(
                f"DELETE FROM reports WHERE user_id = ? AND id IN ({placeholders})", [user_id, *ids]
            )
            return cursor.rowcount
