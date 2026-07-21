import argparse
import time
import uuid
from datetime import date
from pathlib import Path

from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from agent.bq import make_client
from agent.config import load_settings
from agent.context import build_system_prompt, load_instructions, prompt_version
from agent.graph import build_agent, open_checkpointer
from agent.runtime import RuntimeContext, TurnBudget, load_examples
from agent.safety.pii import mask_text
from agent.store import make_store
from agent.tools.schema import fetch_schema
from agent.trace import Trace

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_examples.json"

HELP = """Commands:
  /reports         list your saved reports
  /persona [name]  show personas, or switch the active one (no restart needed)
  /new             start a fresh conversation
  /help            show this help
  /quit            exit
Anything else is a question for the analyst agent."""


def _is_thinking_part(part) -> bool:
    return isinstance(part, dict) and (part.get("type") in ("thinking", "reasoning") or part.get("thought") is True)


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
    model_calls = 0
    for m in messages:
        kind = getattr(m, "type", "")
        if kind == "ai":
            model_calls += 1
            tool_calls = getattr(m, "tool_calls", None) or []
            if debug:
                console.print(f"[dim]── model call {model_calls} ──[/dim]")
                thoughts = message_thoughts(m)
                if thoughts:
                    for thought in thoughts:
                        console.print(f"[yellow]🧠 {thought[:clip]}[/yellow]")
                else:
                    # Gemini decides per call whether to emit thought summaries;
                    # simple synthesis steps often skip thinking entirely.
                    console.print("[dim]🧠 (no thinking summary returned for this step)[/dim]")
            for call in tool_calls:
                args = str(call.get("args", {}))
                console.print(f"[dim]→ {call.get('name')}({args[:clip]})[/dim]")
            if debug and not tool_calls:
                console.print(f"[dim]↳ final answer produced at model call {model_calls}[/dim]")
        elif kind == "tool":
            name = getattr(m, "name", "") or "tool"
            text = message_text(m).replace("\n", " ⏎ ")
            console.print(f"[dim]← {name}: {text[:clip]}[/dim]")


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
    store = make_store(settings)
    retriever = None
    if settings.database_url:
        from agent.retrieval import TrioRetriever

        retriever = TrioRetriever(settings)
    trace = Trace(settings.log_dir)
    trace.event("session_start", user=args.user, model=settings.agent_model, examples=len(examples))
    ctx = RuntimeContext(
        settings=settings,
        bq=client,
        user_id=args.user,
        schema=schema,
        examples=examples,
        store=store,
        retriever=retriever,
        trace=trace,
        debug=args.debug,
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
        if question.startswith("/persona"):
            parts = question.split(maxsplit=1)
            if len(parts) == 1:
                for p in store.list_personas():
                    marker = "[green]● active[/green]" if p["is_active"] else "[dim]○[/dim]"
                    console.print(f"  {marker} {p['name']}")
            else:
                name = parts[1].strip()
                if store.set_active_persona(name):
                    console.print(f"[dim]Persona switched to '{name}' — takes effect on the next answer.[/dim]")
                else:
                    known = ", ".join(p["name"] for p in store.list_personas())
                    console.print(f"[red]Unknown persona '{name}'.[/red] Available: {known}")
            continue
        if question == "/reports":
            reports = store.list_reports(args.user)
            if not reports:
                console.print("[dim]No saved reports.[/dim]")
            else:
                table = Table(title=f"Saved reports — {args.user}")
                for col in ("id", "title", "created"):
                    table.add_column(col)
                for r in reports:
                    table.add_row(r["id"], r["title"], str(r["created_at"]))
                console.print(table)
            continue

        try:
            answer, new_messages = run_turn(ctx, checkpointer, thread_id, question, console, args.verbose)
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled.[/yellow]")
            continue
        except Exception as e:  # the REPL must survive anything a turn throws
            trace.event("turn_end", turn_id=ctx.budget.turn_id, status="error", error=str(e)[:200])
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
        answer, swept = mask_text(answer)
        if swept and args.verbose:
            console.print(f"[dim]output sweep masked {swept} PII value(s)[/dim]")
        console.print(Markdown(answer))

    console.print("[dim]bye[/dim]")
    return 0


TRANSIENT_BACKOFF_S = (5, 20)

FATAL_MARKERS = (
    "not found",
    "not_found",
    "404",
    "api key",
    "api_key",
    "permission",
    "unauthorized",
    "invalid argument",
)


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


def _handle_interrupts(agent, config, result, console: Console, trace=None, turn_id: str = ""):
    """Destructive-action gate: render the preview, require the exact typed
    phrase, resume the graph with the verdict. Anything but the phrase —
    including EOF — cancels."""
    while True:
        interrupts = result.get("__interrupt__") or []
        if not interrupts:
            return result
        payload = getattr(interrupts[0], "value", None) or {}
        if trace:
            trace.event(
                "interrupt_shown",
                turn_id=turn_id,
                action=payload.get("action", ""),
                items=len(payload.get("items", [])),
            )
        table = Table(title=f"⚠ Confirmation required: {payload.get('action', 'destructive action')}")
        for col in ("id", "title", "created"):
            table.add_column(col)
        for item in payload.get("items", []):
            table.add_row(str(item.get("id", "")), str(item.get("title", "")), str(item.get("created_at", "")))
        console.print(table)
        phrase = payload.get("phrase", "confirm")
        console.print(f"This is permanent. Type [bold]{phrase}[/bold] to proceed — anything else cancels.")
        try:
            entered = console.input("[bold red]confirm ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            entered = ""
        approved = entered == phrase
        if trace:
            trace.event("interrupt_decision", turn_id=turn_id, approved=approved)
        # Echo the previewed ids back so the tool deletes exactly the set the
        # user saw, immune to filter re-resolution on resume.
        previewed_ids = [str(item.get("id", "")) for item in payload.get("items", [])]
        result = agent.invoke(Command(resume={"approved": approved, "ids": previewed_ids}), config)


def run_turn(ctx, checkpointer, thread_id: str, question: str, console: Console, verbose: bool):
    ctx.budget = TurnBudget(turn_id=uuid.uuid4().hex[:8])
    started = time.monotonic()
    instructions = load_instructions()
    ctx.trace.event(
        "turn_start", turn_id=ctx.budget.turn_id, question=question[:150], prompt_version=prompt_version(instructions)
    )
    persona = ctx.store.get_active_persona() if ctx.store else None
    prefs = tuple(ctx.store.get_preferences(ctx.user_id)) if ctx.store else ()
    # Retrieval is a deterministic pre-step, not a tool: exemplars must shape
    # the FIRST SQL attempt. An empty or failing index degrades to the static
    # few-shots rather than breaking the turn.
    examples = ctx.examples
    if ctx.retriever:
        try:
            if ctx.settings.rerank_retrieval:
                from agent.retrieval import llm_rerank

                hits = llm_rerank(ctx.settings, question, ctx.retriever.retrieve(question, k=10), k=3)
            else:
                hits = ctx.retriever.retrieve(question)
        except Exception as e:
            ctx.trace.event("retrieval_error", turn_id=ctx.budget.turn_id, error=str(e)[:200])
            hits = []
        if hits:
            examples = [h.trio for h in hits]
            ctx.trace.event(
                "retrieval",
                turn_id=ctx.budget.turn_id,
                ids=[h.trio.id for h in hits],
                scores=[h.score for h in hits],
                dense_ranks=[h.dense_rank for h in hits],
                lexical_ranks=[h.lexical_rank for h in hits],
            )
    system_prompt = build_system_prompt(
        ctx.schema.summary,
        examples,
        persona_text=persona["instructions"] if persona else None,
        preference_notes=prefs,
        today=date.today().isoformat(),
        instructions=instructions,
    )
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
        ctx.trace.event(
            "model_error",
            turn_id=ctx.budget.turn_id,
            fatal=_is_fatal_model_error(first_error),
            error=str(first_error)[:200],
        )
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
            ctx.trace.event("fallback_switch", turn_id=ctx.budget.turn_id, model=ctx.settings.fallback_model)
            fallback = build_agent(ctx, checkpointer, system_prompt, role="fallback")
            result = attempt(fallback, first=False)
            agent = fallback

    result = _handle_interrupts(agent, config, result, console, trace=ctx.trace, turn_id=ctx.budget.turn_id)

    messages = result["messages"]
    new_messages = messages[prior:]
    answer = ""
    for m in reversed(new_messages):
        if getattr(m, "type", "") == "ai" and not (getattr(m, "tool_calls", None) or []):
            answer = message_text(m)
            break
    if not answer.strip():
        # Some models occasionally finish with an empty message after a tool
        # call. The tool output is already PII-masked, so showing it beats
        # showing nothing — and costs no extra model call.
        for m in reversed(new_messages):
            if getattr(m, "type", "") == "tool":
                answer = (
                    "Here is the raw query result (the model returned no summary):\n\n```\n" + message_text(m) + "\n```"
                )
                break
    ctx.trace.event(
        "turn_end",
        turn_id=ctx.budget.turn_id,
        status="ok",
        seconds=round(time.monotonic() - started, 2),
        sql_attempts=ctx.budget.sql_attempts,
        answer_chars=len(answer),
    )
    return answer.strip() or "(the agent produced no answer — try rephrasing)", new_messages


if __name__ == "__main__":
    raise SystemExit(main())
