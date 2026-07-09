import argparse
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


def message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def print_verbose_trace(console: Console, messages: list) -> None:
    for m in messages:
        if getattr(m, "type", "") == "ai":
            for call in getattr(m, "tool_calls", None) or []:
                args = str(call.get("args", {}))
                console.print(f"[dim]→ {call.get('name')}({args[:300]})[/dim]")
        elif getattr(m, "type", "") == "tool":
            text = message_text(m).replace("\n", " ⏎ ")
            console.print(f"[dim]← {text[:300]}[/dim]")


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent.cli", description="Retail analyst chat agent")
    parser.add_argument("--user", default="manager", help="acting user id (owns saved reports and preferences)")
    parser.add_argument("--verbose", action="store_true", help="show tool calls and results")
    args = parser.parse_args()

    console = Console()
    settings = load_settings()
    if not settings.gcp_project or not settings.google_api_key:
        console.print("[red]Missing configuration.[/red] Run: python -m agent.smoke")
        return 1

    client = make_client(settings)
    with console.status("Loading dataset schema…"):
        schema = fetch_schema(client, settings)
    examples = load_examples(EXAMPLES_PATH)
    ctx = RuntimeContext(settings=settings, bq=client, user_id=args.user, schema=schema, examples=examples)
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
            console.print(f"[red]Something went wrong:[/red] {e}")
            continue

        if args.verbose:
            print_verbose_trace(console, new_messages)
        console.print(Markdown(answer))

    console.print("[dim]bye[/dim]")
    return 0


def run_turn(ctx, checkpointer, thread_id: str, question: str, console: Console, verbose: bool):
    ctx.budget = TurnBudget()
    system_prompt = build_system_prompt(ctx.schema.summary, ctx.examples)
    agent = build_agent(ctx, checkpointer, system_prompt)
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": ctx.settings.recursion_limit}

    prior = agent.get_state(config).values.get("messages", [])
    payload = {"messages": [{"role": "user", "content": question}]}
    if verbose:
        result = agent.invoke(payload, config)
    else:
        with console.status("analyzing…"):
            result = agent.invoke(payload, config)

    messages = result["messages"]
    new_messages = messages[len(prior) :]
    answer = ""
    for m in reversed(new_messages):
        if getattr(m, "type", "") == "ai" and not (getattr(m, "tool_calls", None) or []):
            answer = message_text(m)
            break
    return answer or "(the agent produced no final answer)", new_messages


if __name__ == "__main__":
    raise SystemExit(main())
