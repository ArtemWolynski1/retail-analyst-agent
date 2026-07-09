from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from agent.config import Settings


def build_chat_model(settings: Settings, role: str = "agent", include_thoughts: bool = False) -> BaseChatModel:
    """Per-role model choice is the right-sizing hook: the input guard can run a
    cheaper model than the analyst loop via env config alone.

    include_thoughts surfaces Gemini's reasoning summaries as content parts —
    debug/observability only, never shown to end users."""
    model_name = {
        "agent": settings.agent_model,
        "guard": settings.guard_model,
    }[role]
    return init_chat_model(f"google_genai:{model_name}", temperature=0, include_thoughts=include_thoughts)
