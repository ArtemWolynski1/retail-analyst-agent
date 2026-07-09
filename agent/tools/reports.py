from langchain_core.tools import tool
from langgraph.types import interrupt

from agent.runtime import RuntimeContext


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
    def delete_reports(ids: list[str]) -> str:
        """Permanently delete saved reports by their exact ids (from list_reports).

        The platform shows the user a preview and requires explicit confirmation
        before anything is deleted — do not ask for confirmation yourself.

        Args:
            ids: the report ids to delete.
        """
        # Resolve to owned rows only; the deletion below targets this resolved
        # set, so the previewed set and the deleted set are the same by
        # construction (interrupt() re-runs this code on resume).
        matched = ctx.store.get_reports_by_ids(ctx.user_id, ids)
        if not matched:
            return "No deletable reports matched those ids (users can only delete their own reports)."
        phrase = f"delete {len(matched)} report" + ("s" if len(matched) != 1 else "")
        decision = interrupt({"action": "delete saved reports", "items": matched, "phrase": phrase})
        if not (isinstance(decision, dict) and decision.get("approved")):
            return "The user cancelled the deletion. Nothing was deleted."
        deleted = ctx.store.delete_by_ids(ctx.user_id, [r["id"] for r in matched])
        return f"Deleted {deleted} report(s)."

    return [save_report, list_reports, delete_reports]
