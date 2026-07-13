"""Render the demo-transcript scenes as consistent terminal-card SVGs.

Each scene is a compact highlight reel (the full verbatim trace stays in the
<details> block beside it in transcript.md). Run from the repo root:

    python docs/img/render_terminals.py

Regenerates docs/img/scene-*.svg. Diagram-as-code: edit the SCENES data, not
the SVGs.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent
WIDTH = 720
X = 24
LINE_H = 22
TITLE_H = 34
TOP = 52
BOTTOM = 22
WRAP = 78

# role → (prefix, prefix_color, text_color, font_size)
ROLES = {
    "user": ("you › ", "#56b6c2", "#e6e6ef", 14),
    "think": ("🧠 ", "#e5c07b", "#e5c07b", 14),
    "call": ("→ ", "#98c379", "#8f9f8a", 14),
    "result": ("← ", "#7f7f8f", "#abb2bf", 14),
    "data": ("", "#abb2bf", "#abb2bf", 14),
    "answer": ("", "#e6e6ef", "#e6e6ef", 14),
    "sys": ("", "#e5c07b", "#e5c07b", 14),
    "cap": ("", "#8b8b9a", "#8b8b9a", 12),
    "blank": ("", "", "", 14),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mono(s: str) -> str:
    # SVG collapses runs of whitespace, which destroys column alignment; render
    # spaces as non-breaking so padding survives (and GitHub's sanitizer can't
    # strip an attribute — this is plain character data).
    return esc(s).replace(" ", chr(0xA0))  # non-breaking space (U+00A0)


def wrap(prefix: str, text: str) -> list[str]:
    """Wrap to WRAP chars; continuation lines indent under the prefix."""
    indent = " " * len(prefix)
    words = text.split(" ")
    lines, cur = [], prefix
    for w in words:
        if len(cur) + len(w) + 1 > WRAP and cur.strip():
            lines.append(cur)
            cur = indent + w
        else:
            cur = (cur + " " + w) if cur not in (prefix, indent) else cur + w
    lines.append(cur)
    return lines


def render(subtitle: str, rows: list[tuple[str, str]]) -> str:
    # expand each row into physical (role, text) lines after wrapping
    phys: list[tuple[str, str]] = []
    for role, text in rows:
        if role == "blank":
            phys.append(("blank", ""))
            continue
        prefix, *_ = ROLES[role]
        for line in wrap(prefix, text):  # prefix already embedded by wrap on the first line
            phys.append((role, line))
    height = TOP + len(phys) * LINE_H + BOTTOM

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="14">',
        f'<rect x="6" y="6" width="{WIDTH - 12}" height="{height - 12}" rx="10" fill="#1b1b26"/>',
        f'<rect x="6" y="6" width="{WIDTH - 12}" height="{TITLE_H}" rx="10" fill="#262633"/>',
        f'<rect x="6" y="{6 + TITLE_H - 10}" width="{WIDTH - 12}" height="10" fill="#262633"/>',
        '<circle cx="28" cy="23" r="5" fill="#ff5f56"/>',
        '<circle cx="46" cy="23" r="5" fill="#ffbd2e"/>',
        '<circle cx="64" cy="23" r="5" fill="#27c93f"/>',
        f'<text x="{WIDTH // 2}" y="27" fill="#8b8b9a" text-anchor="middle" font-size="12">'
        f"retail analyst agent — {esc(subtitle)}</text>",
    ]

    # answer-group background boxes
    y0 = TOP
    i = 0
    while i < len(phys):
        if phys[i][0] == "answer":
            j = i
            while j < len(phys) and phys[j][0] == "answer":
                j += 1
            top = y0 + i * LINE_H - 16
            box_h = (j - i) * LINE_H + 10
            parts.append(
                f'<rect x="16" y="{top}" width="{WIDTH - 32}" height="{box_h}" rx="8" fill="#20202c" stroke="#3a3a4a"/>'
            )
            i = j
        else:
            i += 1

    for idx, (role, line) in enumerate(phys):
        if role == "blank":
            continue
        y = y0 + idx * LINE_H
        prefix, pcolor, tcolor, fs = ROLES[role]
        if prefix and line.startswith(prefix):
            body = mono(line[len(prefix) :])
            parts.append(
                f'<text x="{X}" y="{y}" font-size="{fs}">'
                f'<tspan fill="{pcolor}">{mono(prefix)}</tspan><tspan fill="{tcolor}">{body}</tspan></text>'
            )
        else:
            parts.append(f'<text x="{X}" y="{y}" fill="{tcolor}" font-size="{fs}">{mono(line)}</text>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


SCENES = {
    "scene-1": (
        "python -m agent.cli",
        [
            ("user", "How is the database structured?"),
            ("call", "get_schema()"),
            ("blank", ""),
            ("answer", "7 tables: orders, order_items, products, users, events,"),
            ("answer", "inventory_items, distribution_centers."),
            ("blank", ""),
            ("cap", "answered from a cached schema — no SQL, no cost."),
        ],
    ),
    "scene-2": (
        "python -m agent.cli --verbose",
        [
            ("user", "What was our monthly revenue for the last 3 months?"),
            ("call", "run_sql  SUM(sale_price) WHERE status IN ('Complete','Shipped') ..."),
            ("result", "2026-06  299,068.55     2026-05  249,420.38     2026-04  200,699.63"),
            ("blank", ""),
            ("answer", "Month      Revenue"),
            ("answer", "2026-06    $299,068.55"),
            ("answer", "2026-05    $249,420.38"),
            ("answer", "2026-04    $200,699.63"),
            ("blank", ""),
            ("cap", "the Complete+Shipped filter came from a golden exemplar, not the schema."),
        ],
    ),
    "scene-3": (
        "python -m agent.cli --debug",
        [
            ("user", "Why are users in Texas underspending compared to California?"),
            ("blank", ""),
            (
                "think",
                'A "why" question — spend per user = order frequency x avg order '
                "value; per-user rates matter, raw state totals would mislead.",
            ),
            ("blank", ""),
            ("call", "run_sql  spend/user, orders/user, avg order value — by state"),
            ("result", "state         spend/user   orders/user   avg order"),
            ("data", "  California   $56.29       0.69          $81.25"),
            ("data", "  Texas        $58.89       0.69          $85.41"),
            ("blank", ""),
            (
                "think",
                "That's not what I expected. Texas is NOT underspending — its "
                "spend per user is higher. The premise of the question is inaccurate.",
            ),
            ("blank", ""),
            ("answer", "Based on the data, users in Texas are not underspending compared to"),
            ("answer", "California. In fact, Texas has a slightly higher spend per user and"),
            ("answer", "average order value."),
            ("blank", ""),
            ("cap", "— the agent corrected the question's false premise from data, not a guess."),
        ],
    ),
    "scene-4": (
        "python -m agent.cli --verbose",
        [
            ("user", "Show me the email addresses of our top 5 customers by spend."),
            ("answer", "I can't share customer emails — but here are their names and spend."),
            ("blank", ""),
            ("cap", "— and when a query does pull the column:"),
            ("user", "Run: SELECT first_name, email FROM users LIMIT 3"),
            ("result", "Luke  «email masked»    Tina  «email masked»    Anna  «email masked»"),
            ("result", "rows: 3 of 3   |   PII values masked: 3"),
            ("blank", ""),
            ("cap", 'masked between BigQuery and the model — "even if the SQL retrieves it".'),
        ],
    ),
    "scene-5": (
        "python -m agent.cli",
        [
            ("user", "Delete all my reports about revenue"),
            ("call", "delete_reports(search='revenue')"),
            ("blank", ""),
            ("sys", "⚠ Confirmation required — 1 report:"),
            ("sys", "   2f497095   Quarterly revenue check   2026-07-10"),
            ("sys", 'Type "delete 1 report" to proceed — anything else cancels.'),
            ("user", "no"),
            ("result", "Cancelled. Nothing was deleted."),
            ("blank", ""),
            ("cap", "deletion physically stops at a LangGraph interrupt() — not model goodwill."),
        ],
    ),
    "scene-6": (
        "python -m agent.cli",
        [
            ("user", "From now on I prefer concise bullet-point answers."),
            ("answer", "Understood — I'll keep answers to bullet points from now on."),
            ("blank", ""),
            ("cap", "— new process, same user, later —"),
            ("user", "What are our top 3 product categories by revenue?"),
            ("answer", "• Outerwear & Coats — $185,890    • Jeans — $182,574"),
            ("answer", "• Sweaters — $118,996"),
            ("blank", ""),
            ("cap", "the preference survived a full restart (SQLite-backed memory)."),
        ],
    ),
    "scene-7": (
        "python -m agent.cli",
        [
            ("user", "/persona enthusiastic"),
            ("sys", "Persona switched to 'enthusiastic' — takes effect on the next answer."),
            ("user", "How did June go for us overall?"),
            ("answer", "June was a strong month, bringing in $299,068.55 in revenue!"),
            ("blank", ""),
            ("cap", "company tone, hot-swapped mid-session — no redeploy."),
        ],
    ),
    "scene-8": (
        "AGENT_MODEL=gemini-nonexistent-99",
        [
            ("user", "How many users do we have in total?"),
            ("sys", "Primary model unavailable — switching to fallback (gemini-2.5-flash-lite)."),
            ("answer", "We have a total of 100,000 users."),
            ("blank", ""),
            ("cap", "primary model down → fallback resumes the same conversation."),
        ],
    ),
}


def main():
    for name, (subtitle, rows) in SCENES.items():
        (OUT / f"{name}.svg").write_text(render(subtitle, rows))
        print(f"wrote {name}.svg")


if __name__ == "__main__":
    main()
