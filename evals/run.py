"""L2 agent-level eval harness.

Drives the real agent path over evals/questions.yaml and grades each case two
ways: an independent number oracle (hard gate) and an LLM judge (advisory).
Writes evals/report.md. Costs live Gemini + BigQuery — run before deploy, not
in per-push CI.

    python evals/run.py [--out evals/report.md]
"""

import argparse
import json
import re
import sys
import uuid
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.bq import make_client, run_query  # noqa: E402
from agent.config import load_settings  # noqa: E402
from agent.context import build_system_prompt, load_instructions  # noqa: E402
from agent.graph import build_agent, open_checkpointer  # noqa: E402
from agent.llm import build_chat_model  # noqa: E402
from agent.runtime import RuntimeContext, TurnBudget, load_examples  # noqa: E402
from agent.store import Store  # noqa: E402
from agent.tools.schema import fetch_schema  # noqa: E402

SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}
NUM_RE = re.compile(r"-?\$?\s?([\d,]+(?:\.\d+)?)\s*([kmb])?", re.IGNORECASE)

JUDGE_PROMPT = """You are a strict QA reviewer for a data-analyst agent. Given a business \
question, the agent's answer, and the SQL it ran, score the answer.

Question: {question}
What a correct answer requires: {rubric}

SQL the agent executed:
{sqls}

Agent's answer:
{answer}

Respond with ONLY a JSON object, no prose:
{{"intent_match": bool, "grounded": bool, "honest": bool, "verdict": "pass" or "fail", "notes": "one sentence"}}
- intent_match: does it actually answer what was asked (right decomposition/definition)?
- grounded: is every figure supported by the SQL results (no invented numbers)?
- honest: does it avoid fabrication, correct false premises, and hedge undefined metrics?
- verdict: "pass" only if all three hold.
Judge material correctness, not pedantic phrasing. The dataset's latest data is the current date, so \
"this year" and "year to date" are equivalent. If the figures are right and grounded, do not fail on \
interpretive nuances that don't change the result."""


def extract_numbers(text: str) -> list[float]:
    out = []
    for digits, suffix in NUM_RE.findall(text):
        try:
            val = float(digits.replace(",", ""))
        except ValueError:
            continue
        if suffix:
            val *= SUFFIX[suffix.lower()]
        out.append(val)
    return out


def number_ok(answer: str, expected, tol: float) -> bool:
    if expected is None:
        return False
    expected = float(expected)
    for n in extract_numbers(answer):
        if expected == 0:
            if abs(n) < 1:
                return True
        elif abs(n - expected) / abs(expected) <= tol:
            return True
    return False


def build_ctx(settings, client, schema, store):
    return RuntimeContext(
        settings=settings,
        bq=client,
        user_id="eval",
        schema=schema,
        examples=load_examples(ROOT / "data" / "golden_examples.json"),
        store=store,
    )


def drive(ctx, checkpointer, question: str):
    ctx.budget = TurnBudget(turn_id=uuid.uuid4().hex[:8])
    prompt = build_system_prompt(
        ctx.schema.summary, ctx.examples, today=date.today().isoformat(), instructions=load_instructions()
    )
    agent = build_agent(ctx, checkpointer, prompt)
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}, "recursion_limit": ctx.settings.recursion_limit}
    result = agent.invoke({"messages": [{"role": "user", "content": question}]}, cfg)
    msgs = result["messages"]
    sqls = [
        (tc.get("args") or {}).get("sql", "")
        for m in msgs
        if getattr(m, "type", "") == "ai"
        for tc in (getattr(m, "tool_calls", None) or [])
        if tc.get("name") == "run_sql"
    ]
    answer = ""
    for m in reversed(msgs):
        if getattr(m, "type", "") == "ai" and not (getattr(m, "tool_calls", None) or []):
            c = m.content
            answer = (
                c
                if isinstance(c, str)
                else "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") != "thinking")
            )
            break
    return answer, sqls


def judge(model, case, answer, sqls):
    prompt = JUDGE_PROMPT.format(
        question=case["question"],
        rubric=case.get("rubric", ""),
        sqls="\n".join(sqls) or "(none)",
        answer=answer,
    )
    try:
        raw = model.invoke(prompt).content
        raw = raw if isinstance(raw, str) else str(raw)
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        return {
            "verdict": "error",
            "notes": f"judge parse failed: {e}",
            "intent_match": None,
            "grounded": None,
            "honest": None,
        }


def grade(case, answer, sqls, client, settings):
    """Hard gates → (passed, reasons[])."""
    reasons = []
    passed = True
    if case.get("oracle_sql"):
        rows = run_query(client, case["oracle_sql"], settings)
        # collect every scalar the oracle returns; each must appear in the answer.
        # A single SUM is one value; a per-month breakdown is several.
        expected = [r[0] for r in rows if r[0] is not None]
        tol = case.get("numeric_tolerance", 0.02)
        missing = [v for v in expected if not number_ok(answer, v, tol)]
        ok = not missing
        reasons.append(f"oracle={expected} → {'✓' if ok else '✗ missing ' + str(missing)}")
        passed = passed and ok
    inc = case.get("must_include_any")
    if inc:
        ok = any(t.lower() in answer.lower() for t in inc)
        reasons.append(f"must_include_any {inc} → {'✓' if ok else '✗'}")
        passed = passed and ok
    if case.get("must_not_match"):
        hit = re.search(case["must_not_match"], answer)
        ok = hit is None
        reasons.append(f"must_not_match → {'✓' if ok else '✗ matched ' + hit.group()}")
        passed = passed and ok
    return passed, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "report.md"))
    args = ap.parse_args()

    settings = load_settings()
    client = make_client(settings)
    schema = fetch_schema(client, settings)
    judge_model = build_chat_model(settings)
    store = Store(str(ROOT / ".data" / "eval.sqlite"))
    cases = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text())

    rows = []
    for case in cases:
        ctx = build_ctx(settings, client, schema, store)
        cp = open_checkpointer(settings)
        answer, sqls = drive(ctx, cp, case["question"])
        hard_pass, reasons = grade(case, answer, sqls, client, settings)
        verdict = judge(judge_model, case, answer, sqls)
        status = "PASS" if hard_pass and verdict.get("verdict") == "pass" else ("SOFT" if hard_pass else "FAIL")
        rows.append(
            {
                "case": case,
                "answer": answer,
                "sqls": sqls,
                "hard_pass": hard_pass,
                "reasons": reasons,
                "judge": verdict,
                "status": status,
            }
        )
        print(
            f"[{status}] {case['id']}: {'; '.join(reasons) or 'judge-only'} | judge={verdict.get('verdict')}",
            flush=True,
        )

    write_report(Path(args.out), rows)
    n_fail = sum(1 for r in rows if r["status"] == "FAIL")
    n_soft = sum(1 for r in rows if r["status"] == "SOFT")
    print(
        f"\n{len(rows)} cases: {sum(1 for r in rows if r['status'] == 'PASS')} pass, "
        f"{n_soft} soft (hard gate ok, judge flagged), {n_fail} fail. Report: {args.out}"
    )
    return 1 if n_fail else 0


def write_report(path: Path, rows):
    lines = [
        "# L2 eval report",
        "",
        "Agent-level evaluation: each case drives the real agent, then grades it with an "
        "**independently-authored number oracle** (hard gate) and an **LLM judge** (advisory). "
        "Numbers drift daily as the dataset regenerates, so the oracle runs live at eval time.",
        "",
        "Status: **PASS** = hard gates and judge agree · **SOFT** = hard gates passed but the "
        "advisory judge raised a concern — not a failure, because the deterministic oracle is "
        "authoritative and LLM judges are themselves fallible (a SOFT row can be a judge "
        "false-negative) · **FAIL** = a hard gate failed.",
        "",
        "| case | status | hard gates | judge |",
        "|---|---|---|---|",
    ]
    for r in rows:
        gates = "<br>".join(r["reasons"]) or "judge-only"
        j = r["judge"]
        jcell = f"{j.get('verdict')} — {j.get('notes', '')}"
        lines.append(f"| `{r['case']['id']}` | **{r['status']}** | {gates} | {jcell} |")
    lines += ["", "## Per-case detail", ""]
    for r in rows:
        lines.append(f"### {r['case']['id']} — {r['status']}")
        lines.append(f"**Q:** {r['case']['question']}")
        lines.append(f"**Answer:** {r['answer'][:400]}")
        if r["sqls"]:
            lines.append(f"**SQL:** `{r['sqls'][0][:200]}`")
        lines.append(f"**Judge:** {r['judge']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
