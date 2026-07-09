from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from agent.config import Settings


def build_chat_model(settings: Settings, role: str = "agent") -> BaseChatModel:
    """Per-role model choice is the right-sizing hook: the input guard can run a
    cheaper model than the analyst loop via env config alone."""
    model_name = {
        "agent": settings.agent_model,
        "guard": settings.guard_model,
    }[role]
    return init_chat_model(f"google_genai:{model_name}", temperature=0)
