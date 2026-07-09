from datetime import datetime
from pathlib import Path

import structlog


class Trace:
    """JSON-lines session trace: one file per session, one event per line.

    Trace(None) is a silent no-op so tools and tests need no log plumbing.
    Every event carries whatever fields the caller passes — turn_id is the
    join key for reconstructing a full turn during a deep-dive.
    """

    def __init__(self, log_dir: str | None):
        self._log = None
        self.path: Path | None = None
        if log_dir:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / f"session-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
            self._log = structlog.wrap_logger(
                structlog.WriteLogger(self.path.open("a")),
                processors=[
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.JSONRenderer(),
                ],
            )

    def event(self, name: str, **fields) -> None:
        if self._log is not None:
            self._log.msg(name, **fields)
