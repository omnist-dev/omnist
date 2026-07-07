"""Non-destructive structural diagnostics for a schema (``omnist schema lint``).

``validate`` checks a *document* against a schema; ``lint`` checks the *schema
itself* for structural problems that parse fine but mean parts of the schema can
never do anything. It **reports, never mutates** -- that line is the whole
design. ``prune`` and ``normalize`` are the transforms that *fix* these issues;
``lint`` only diagnoses them.

Four checks:

* ``unsatisfiable-record`` (``warning``) -- a reachable record no finite
  document can match (e.g. a mandatory ref cycle). Reuses
  :func:`prune.satisfiable_set` (its complement), intersected with reachable.
* ``unreachable-record`` (``warning``) -- a record defined in ``env`` but not
  reachable from ``root`` by following any ref. A plain reachability walk (no
  pruning): every ``Ref``-typed field is followed regardless of cardinality.
* ``duplicate-record`` (``warning``) -- two or more structurally identical
  records under different names. Reuses :func:`minimize.equivalence_classes` on
  the *raw* schema, so duplicates are reported as authored.
* ``any-field`` (``info``) -- an inventory of every ``any``-typed field, so a
  human can audit the schema's deliberate openings. Advisory only; never fails
  the exit code on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

from ..schema import AnyType, Ref, Schema
from .minimize import equivalence_classes
from .prune import satisfiable_set


@dataclass(frozen=True)
class LintFinding:
    """One structural diagnostic. ``code`` is a stable machine-readable
    identifier (``unsatisfiable-record``, ``unreachable-record``,
    ``duplicate-record``, ``any-field``); ``severity`` is ``warning`` or
    ``info``; ``location`` is a record name (or ``Record.label`` for
    ``any-field``); ``message`` is a human-readable, actionable description."""

    code: str
    severity: str
    location: str
    message: str


def _reachable(s: Schema) -> Set[str]:
    """Record names reachable from ``s.root`` by a plain walk following every
    ``Ref``-typed field -- no pruning, cardinality ignored. A record reachable
    only via an optional or unsatisfiable field still counts as referenced."""
    seen: Set[str] = set()
    stack = [s.root.name]
    while stack:
        name = stack.pop()
        if name in seen or name not in s.env:
            continue
        seen.add(name)
        for f in s.env[name].fields:
            if isinstance(f.type, Ref):
                stack.append(f.type.name)
    return seen


def lint(s: Schema) -> List[LintFinding]:
    """Structural diagnostics for ``s`` -- see the module docstring for the
    four checks. Returns findings sorted deterministically by ``(code,
    location)``. Never mutates ``s``."""
    findings: List[LintFinding] = []

    reachable = _reachable(s)
    sat = satisfiable_set(s)

    # unsatisfiable-record: reachable but not satisfiable
    for name in reachable - sat:
        findings.append(LintFinding(
            "unsatisfiable-record", "warning", name,
            f"record {name!r} is reachable but unsatisfiable -- no finite "
            f"document can match it (e.g. a mandatory ref cycle)"))

    # unreachable-record: defined in env but not reachable from root
    for name in set(s.env) - reachable:
        findings.append(LintFinding(
            "unreachable-record", "warning", name,
            f"record {name!r} is defined but never reachable from the root; "
            f"drop it with `schema prune`"))

    # duplicate-record: structurally identical records under different names
    for block in equivalence_classes(s):
        if len(block) > 1:
            group = sorted(block)
            location = ", ".join(group)
            keep = group[0]
            others = ", ".join(repr(n) for n in group[1:])
            findings.append(LintFinding(
                "duplicate-record", "warning", location,
                f"records {others} are structurally identical to {keep!r}; "
                f"merge them with `schema normalize`"))

    # any-field: inventory of every any-typed field
    for name in sorted(s.env):
        for f in s.env[name].fields:
            if isinstance(f.type, AnyType):
                findings.append(LintFinding(
                    "any-field", "info", f"{name}.{f.label}",
                    f"field {f.label!r} of record {name!r} is typed `any` "
                    f"(accepts any value unchecked)"))

    findings.sort(key=lambda x: (x.code, x.location))
    return findings
