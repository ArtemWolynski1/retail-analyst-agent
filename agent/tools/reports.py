from langchain_core.tools import tool
from langgraph.types import interrupt

from agent.runtime import RuntimeContext
from agent.store import Store


def resolve_delete_targets(
    store: Store, user_id: str, ids: list[str] | None, search: str, created_on: str
) -> list[dict] | None:
    """None means 'no criteria given' — distinct from 'criteria matched nothing'."""
    if ids:
        return store.get_reports_by_ids(user_id, ids)
    if search or created_on:
        return store.list_reports(user_id, search=search, created_on=created_on)
    return None


def build_report_tools(ctx: RuntimeContext) -> list:
    @tool
    def save_report(title: str, question: str, sql: str, report_markdown: str) -> str:
        """Save a finished analysis to the user's report library.

        Args:
            title: short descriptive title.
            question: the user's original question.
            sql: the main SQL query behind the analysis.
            report_markdown: the full report text as shown to the user.
        """
        report_id = ctx.store.save_report(ctx.user_id, title, question, sql, report_markdown)
        return f"Saved as report {report_id} ('{title}')."

    @tool
    def list_reports(search: str = "", created_on: str = "") -> str:
        """List the user's saved reports. Users only ever see their own reports.

        Args:
            search: optional substring matched against title, question and content.
            created_on: optional date filter in YYYY-MM-DD format.
        """
        reports = ctx.store.list_reports(ctx.user_id, search=search, created_on=created_on)
        if not reports:
            return "No saved reports match."
        return "\n".join(f"{r['id']} | {r['title']} | {r['created_at']}" for r in reports)

    @tool
    def delete_reports(ids: list[str] | None = None, search: str = "", created_on: str = "") -> str:
        """Delete saved reports after the user confirms. Express the user's request
        directly — never ask them for report ids. Examples: "delete the reports we
        made today" → created_on=<today>; "delete all reports about Client X" →
        search="Client X". The platform previews the matches and asks the user to
        confirm before anything is deleted.

        Args:
            ids: exact report ids, when already known.
            search: substring filter over title, question and content.
            created_on: date filter in YYYY-MM-DD format.
        """
        matched = resolve_delete_targets(ctx.store, ctx.user_id, ids, search, created_on)
        if matched is None:
            return "Give explicit ids or a filter (search and/or created_on) so I know what to delete."
        if not matched:
            return "No deletable reports matched (users can only delete their own reports)."
        phrase = f"delete {len(matched)} report" + ("s" if len(matched) != 1 else "")
        decision = interrupt(
            {
                "action": "delete saved reports",
                "items": [{"id": r["id"], "title": r["title"], "created_at": r["created_at"]} for r in matched],
                "phrase": phrase,
            }
        )
        if not (isinstance(decision, dict) and decision.get("approved")):
            return "The user cancelled the deletion. Nothing was deleted."
        # Delete the ids the gate previewed (echoed back in the resume payload),
        # not a re-resolved filter: pre-interrupt code re-runs on resume, and a
        # filter could match a different set by then. Preview == deletion, always.
        approved_ids = [str(i) for i in decision.get("ids") or []] or [r["id"] for r in matched]
        deleted = ctx.store.delete_by_ids(ctx.user_id, approved_ids)
        return f"Deleted {deleted} report(s)."

    return [save_report, list_reports, delete_reports]
