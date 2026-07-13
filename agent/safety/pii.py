import re

from agent.config import Settings

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone matching requires phone-shaped structure (E.164 plus-prefix, or two
# separator groups / parens) so that decimals, coordinates, dates, and ids
# never false-positive — averages like 158.9724 must survive unmasked.
PHONE_RE = re.compile(
    r"(?<!\w)(?:"
    r"\+\d{10,14}"
    r"|(?:\+\d{1,3}[\s.-])?(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}"
    r")(?!\w)"
)

EMAIL_MASK = "«email masked»"
PHONE_MASK = "«phone masked»"


def _sweep(text: str) -> tuple[str, int]:
    masked, n_email = EMAIL_RE.subn(EMAIL_MASK, text)
    masked, n_phone = PHONE_RE.subn(PHONE_MASK, masked)
    return masked, n_email + n_phone


def mask_text(text: str) -> tuple[str, int]:
    """Final-output sweep: last line of defense before anything reaches a user."""
    return _sweep(text)


def mask_rows(rows: list[dict], settings: Settings) -> tuple[list[dict], int]:
    """Mask PII in query results before they enter model context.

    Two layers on purpose: the column denylist catches known PII fields whatever
    their values look like; the value sweep catches PII smuggled past the list
    through aliases (SELECT email AS contact_info) or string concatenation.
    Aggregates are naturally unaffected — they return numbers, not raw values.
    """
    denylist = set(settings.pii_columns)
    hits = 0
    masked_rows: list[dict] = []
    for row in rows:
        out: dict[str, object] = {}
        for col, value in row.items():
            if col.lower() in denylist and value is not None:
                out[col] = f"«{col.lower()} masked»"
                hits += 1
            elif isinstance(value, str):
                out[col], n = _sweep(value)
                hits += n
            else:
                out[col] = value
        masked_rows.append(out)
    return masked_rows, hits
