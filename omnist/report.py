"""Adjustment reports for lossy writes.

Writing a Document to a format that can't hold every value (TOML has no
``null``; JSON/XML have no date type) means the writer has to *adjust* the data.
Each adjustment is recorded as an :class:`Adjustment` in a :class:`WriteReport`
rather than lost silently.  The same report drives three behaviours:

* **lenient** (default) — adjust and move on; ignore the report if you like.
* **inspect** — pass ``report=`` to a writer (or call ``check_*``) to see what
  changed without stopping.
* **strict** — ``strict=True`` raises :class:`~omnist.errors.WriteError`
  (carrying the report) if anything had to be adjusted.

Each adjustment has a ``severity``: ``"warning"`` (conventional / recoverable —
a date written as a string) or ``"error"`` (likely to surprise or corrupt — a
``null`` dropped, ``NaN`` in JSON).  ``strict`` ignores severity and raises on
anything.
"""

from __future__ import annotations

from typing import Iterator, List, NamedTuple, Optional

from .errors import WriteError


class Adjustment(NamedTuple):
    path: str        # e.g. "$.order.total" — same path style as validation
    code: str        # stable, machine-checkable, e.g. "null.omitted"
    message: str     # human-readable sentence
    severity: str    # "warning" | "error"


class WriteReport:
    """Everything a writer adjusted.  Truthy when there are no error-severity
    entries (warnings are fine), so ``if check_toml(doc): …`` reads as 'safe'."""

    def __init__(self) -> None:
        self.adjustments: List[Adjustment] = []

    def add(self, path: str, code: str, message: str, severity: str) -> None:
        self.adjustments.append(Adjustment(path, code, message, severity))

    @property
    def warnings(self) -> List[Adjustment]:
        return [a for a in self.adjustments if a.severity == "warning"]

    @property
    def errors(self) -> List[Adjustment]:
        return [a for a in self.adjustments if a.severity == "error"]

    def __bool__(self) -> bool:
        return not self.errors

    def __iter__(self) -> Iterator[Adjustment]:
        return iter(self.adjustments)

    def __len__(self) -> int:
        return len(self.adjustments)

    def __str__(self) -> str:
        if not self.adjustments:
            return "no adjustments"
        return "\n".join(f"{a.severity}: {a.path}: {a.message}" for a in self.adjustments)


def finish_write(text: str, rep: WriteReport, *, strict: bool = False,
                 report: Optional[WriteReport] = None) -> str:
    """Apply the standard ``strict`` / ``report`` handling to a writer's result.

    If ``report`` is given, ``rep``'s adjustments are copied into it.  If
    ``strict`` and ``rep`` has any adjustments, raises ``WriteError`` carrying
    ``rep``.  Otherwise returns ``text``.
    """
    if report is not None:
        report.adjustments.extend(rep.adjustments)
    if strict and rep.adjustments:
        raise WriteError(str(rep), report=rep)
    return text
