from langchain_core.tools import tool

from agent.runtime import RuntimeContext


def build_memory_tools(ctx: RuntimeContext) -> list:
    if ctx.store is None:
        raise ValueError("memory tools require a configured store")
    store = ctx.store

    @tool
    def remember_preference(note: str) -> str:
        """Store a durable preference about how this user wants analyses presented.

        Call this once when the user expresses a lasting preference (format,
        level of detail, tone) — not for one-off requests.

        Args:
            note: the preference as one short sentence, e.g. "Prefers bullet
                points over tables".
        """
        store.add_preference(ctx.user_id, note)
        return f"Preference noted: {note}"

    return [remember_preference]
