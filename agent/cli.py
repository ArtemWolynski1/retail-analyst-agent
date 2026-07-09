import argparse
import time
import uuid
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from agent.bq import make_client
from agent.config import load_settings
from agent.context import build_system_prompt
from agent.graph import build_agent, open_checkpointer
from agent.runtime import RuntimeContext, TurnBudget, load_examples
from agent.tools.schema import fetch_schema

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_examples.json"

HELP = """Commands:
  /new    start a fresh conversation
  /help   show this help
  /quit   exit
Anything else is a question for the analyst agent."""


def _is_thinking_part(part) -> bool:
    return isinstance(part, dict) and (
        part.get("type") in ("thinking", "reasoning") or part.get("thought") is True
    )


def message_text(message) -> str:
    """Visible text only — thinking parts must never reach the rendered answer."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
            if not _is_thinking_part(part)
        )
    return str(content)


def message_thoughts(message) -> list[str]:
    content = getattr(message, "content", "")
    if not isinstance(content, list):
        return []
    thoughts = []
    for part in content:
        if _is_thinking_part(part):
            text = part.get("thinking") or part.get("reasoning") or part.get("text") or ""
            if text.strip():
                thoughts.append(text.strip())
    return thoughts


def print_verbose_trace(console: Console, messages: list, debug: bool = False) -> None:
    clip = 2000 if debug else 300
    for m in messages:
        if getattr(m, "type", "") == "ai":
            if debug:
                for thought in message_thoughts(m):
                    console.print(f"[yellow]🧠 {thought[:clip]}[/yellow]")
            for call in getattr(m, "tool_calls", None) or []:
                args = str(call.get("args", {}))
                console.print(f"[dim]→ {call.get('name')}({args[:clip]})[/dim]")
        elif getattr(m, "type", "") == "tool":
            text = message_text(m).replace("\n", " ⏎ ")
            console.print(f"[dim]← {text[:clip]}[/dim]")


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent.cli", description="Retail analyst chat agent")
    parser.add_argument("--user", default="manager", help="acting user id (owns saved reports and preferences)")
    parser.add_argument("--verbose", action="store_true", help="show tool calls and results")
    parser.add_argument(
        "--debug", action="store_true", help="verbose plus the model's reasoning summaries, untruncated traces"
    )
    args = parser.parse_args()
    if args.debug:
        args.verbose = True

    console = Console()
    settings = load_settings()
    if not settings.gcp_project or not settings.google_api_key:
        console.print("[red]Missing configuration.[/red] Run: python -m agent.smoke")
        return 1

    client = make_client(settings)
    with console.status("Loading dataset schema…"):
        schema = fetch_schema(client, settings)
    examples = load_examples(EXAMPLES_PATH)
    ctx = RuntimeContext(
        settings=settings, bq=client, user_id=args.user, schema=schema, examples=examples, debug=args.debug
    )
    checkpointer = open_checkpointer(settings)
    thread_id = uuid.uuid4().hex

    console.print(
        f"[bold]Retail analyst agent[/bold] — user [cyan]{args.user}[/cyan], "
        f"model {settings.agent_model}, {len(examples)} analyst examples loaded. /help for commands."
    )

    while True:
        try:
            question = console.input("\n[bold cyan]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question in ("/quit", "/exit"):
            break
        if question == "/help":
            console.print(HELP)
            continue
        if question == "/new":
            thread_id = uuid.uuid4().hex
            console.print("[dim]Started a fresh conversation.[/dim]")
            continue

        try:
            answer, new_messages = run_turn(ctx, checkpointer, thread_id, question, console, args.verbose)
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled.[/yellow]")
            continue
        except Exception as e:  # the REPL must survive anything a turn throws
            if _is_provider_error(e):
                console.print(
                    "[red]The AI model is unavailable right now (rate limit or outage).[/red] "
                    "Your conversation is saved — try again in a minute."
                )
            else:
                console.print(f"[red]Something went wrong:[/red] {e}")
            continue

        if args.verbose:
            print_verbose_trace(console, new_messages, debug=args.debug)
        console.print(Markdown(answer))

    console.print("[dim]bye[/dim]")
    return 0


TRANSIENT_BACKOFF_S = (5, 20)

FATAL_MARKERS = ("not found", "not_found", "404", "api key", "api_key", "permission", "unauthorized", "invalid argument")


def _is_provider_error(exc: Exception) -> bool:
    module = type(exc).__module__ or ""
    if module.startswith(("google.api_core", "google.genai", "langchain_google_genai")):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("429", "quota", "rate limit", "resource exhausted", "unavailable", "overloaded", "deadline")
    )


def _is_fatal_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in FATAL_MARKERS)


def _resume_input(agent, config, payload):
    """After a mid-turn failure, continue from the checkpoint instead of
    re-running the turn: invoke(None) resumes exactly where the graph died,
    with already-executed tools not re-run. Falls back to the original payload
    when the failure happened before the question was checkpointed."""
    messages = agent.get_state(config).values.get("messages", [])
    if not messages:
        return payload
    last = messages[-1]
    if getattr(last, "type", "") == "ai" and not (getattr(last, "tool_calls", None) or []):
        return payload
    return None


def run_turn(ctx, checkpointer, thread_id: str, question: str, console: Console, verbose: bool):
    ctx.budget = TurnBudget()
    system_prompt = build_system_prompt(ctx.schema.summary, ctx.examples)
    agent = build_agent(ctx, checkpointer, system_prompt)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": ctx.settings.recursion_limit}

    prior = len(agent.get_state(config).values.get("messages", []))
    payload = {"messages": [{"role": "user", "content": question}]}

    def attempt(active_agent, first: bool):
        inp = payload if first else _resume_input(active_agent, config, payload)
        if verbose:
            return active_agent.invoke(inp, config)
        with console.status("analyzing…"):
            return active_agent.invoke(inp, config)

    result = None
    try:
        result = attempt(agent, first=True)
    except KeyboardInterrupt:
        raise
    except Exception as first_error:
        if not _is_provider_error(first_error):
            raise
        if not _is_fatal_model_error(first_error):
            for delay in TRANSIENT_BACKOFF_S:
                reason = str(first_error).replace("\n", " ")[:110]
                console.print(f"[yellow]Model hiccup ({reason}) — retrying in {delay}s…[/yellow]")
                time.sleep(delay)
                try:
                    result = attempt(agent, first=False)
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as retry_error:
                    if not _is_provider_error(retry_error):
                        raise
                    first_error = retry_error
        if result is None:
            console.print(
                f"[yellow]Primary model unavailable — switching to fallback ({ctx.settings.fallback_model}).[/yellow]"
            )
            fallback = build_agent(ctx, checkpointer, system_prompt, role="fallback")
            result = attempt(fallback, first=False)

    messages = result["messages"]
    new_messages = messages[prior:]
    answer = ""
    for m in reversed(new_messages):
        if getattr(m, "type", "") == "ai" and not (getattr(m, "tool_calls", None) or []):
            answer = message_text(m)
            break
    return answer or "(the agent produced no final answer)", new_messages


if __name__ == "__main__":
    raise SystemExit(main())
