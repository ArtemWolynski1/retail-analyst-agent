import uuid

from psycopg import connect
from psycopg.rows import dict_row

from agent.store import DEFAULT_PERSONAS


class PostgresStore:
    """Postgres twin of Store — same public interface, production dialect.

    Dialect differences from the SQLite version, each deliberate:
    - timestamps are TIMESTAMPTZ in UTC (SQLite used localtime — a bug not
      worth porting);
    - ILIKE instead of LIKE: SQLite's LIKE is case-insensitive by default,
      Postgres's is not, and search should behave identically on both backends;
    - one connection per operation mirrors the SQLite store; a server would
      hold a psycopg_pool.ConnectionPool behind the same interface.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    report_md TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, created_at)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS preferences (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS personas (
                    name TEXT PRIMARY KEY,
                    instructions TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE
                )"""
            )
            for name, instructions in DEFAULT_PERSONAS.items():
                conn.execute(
                    "INSERT INTO personas (name, instructions) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, instructions),
                )
            active = conn.execute("SELECT COUNT(*) AS n FROM personas WHERE is_active").fetchone()["n"]
            if not active:
                conn.execute("UPDATE personas SET is_active = TRUE WHERE name = 'professional'")

    def _conn(self):
        # Context-manager use commits on success and rolls back on exception,
        # matching the SQLite store's `with closing(...) as conn, conn:` idiom.
        return connect(self.dsn, row_factory=dict_row)

    def save_report(self, user_id: str, title: str, question: str, sql: str, report_md: str) -> str:
        report_id = uuid.uuid4().hex[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO reports (id, user_id, title, question, sql, report_md) VALUES (%s, %s, %s, %s, %s, %s)",
                (report_id, user_id, title, question, sql, report_md),
            )
        return report_id

    def list_reports(self, user_id: str, search: str = "", created_on: str = "") -> list[dict]:
        sql = "SELECT id, title, question, created_at FROM reports WHERE user_id = %s"
        params: list = [user_id]
        if search:
            sql += " AND (title ILIKE %s OR question ILIKE %s OR report_md ILIKE %s)"
            like = f"%{search}%"
            params += [like, like, like]
        if created_on:
            # Dates compare in UTC — the same day boundary the timestamps use.
            sql += " AND created_at::date = %s::date"
            params.append(created_on)
        sql += " ORDER BY created_at DESC"
        with self._conn() as conn:
            return list(conn.execute(sql, params))

    def get_reports_by_ids(self, user_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        with self._conn() as conn:
            return list(
                conn.execute(
                    "SELECT id, title, created_at FROM reports WHERE user_id = %s AND id = ANY(%s)",
                    (user_id, ids),
                )
            )

    def delete_by_ids(self, user_id: str, ids: list[str]) -> int:
        if not ids:
            return 0
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM reports WHERE user_id = %s AND id = ANY(%s)", (user_id, ids))
            return cursor.rowcount

    def add_preference(self, user_id: str, note: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT INTO preferences (user_id, note) VALUES (%s, %s)", (user_id, note))

    def get_preferences(self, user_id: str, limit: int = 10) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT note FROM preferences WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit)
            ).fetchall()
        return [row["note"] for row in reversed(rows)]

    def get_active_persona(self) -> dict | None:
        with self._conn() as conn:
            return conn.execute("SELECT name, instructions FROM personas WHERE is_active LIMIT 1").fetchone()

    def set_active_persona(self, name: str) -> bool:
        # Existence check FIRST — same reasoning as the SQLite store: the
        # update touches every row, an unknown name would deactivate all.
        with self._conn() as conn:
            hit = conn.execute("SELECT COUNT(*) AS n FROM personas WHERE name = %s", (name,)).fetchone()["n"]
            if not hit:
                return False
            conn.execute("UPDATE personas SET is_active = (name = %s)", (name,))
        return True

    def list_personas(self) -> list[dict]:
        with self._conn() as conn:
            return list(conn.execute("SELECT name, is_active FROM personas ORDER BY name"))
