"""Satisfiability analysis and schema pruning.

Implements the paper's "useless-state removal" (MakeUsefulSA) analog: a
record is *satisfiable* iff it admits at least one finite document, and
:func:`prune` returns an equivalent schema with everything that can never
match removed. This is the precondition Algorithm 4 (SubschemaSA,
``ops/subschema.py``) needs to be correct — see ``docs/design/model.md``
for the full satisfiability subsection.

Satisfiability is a least fixpoint over the env's records: a record is
satisfiable iff every field with ``min >= 1`` is either a ``Scalar`` or a
``Ref`` to a satisfiable record. (Fields with ``min == 0`` never block
satisfiability -- they simply need not be emitted.) Scalars are always
satisfiable, so a record with no mandatory fields at all is trivially
satisfiable (the empty document for that record admits it).
"""

from __future__ import annotations

from typing import Dict, Set

from ..schema import AnyType, Field, Record, Ref, Scalar, Schema


def satisfiable_set(s: Schema) -> Set[str]:
    """The set of env record names that admit at least one finite document.

    Least fixpoint: start with nothing known-satisfiable and repeatedly add
    any record all of whose mandatory (``min >= 1``) fields are already
    satisfiable (a bare ``Scalar``, or a ``Ref`` to an already-satisfiable
    record). Monotonic on a finite env, so this always terminates.
    """
    sat: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, rec in s.env.items():
            if name in sat:
                continue
            if _record_satisfiable(rec, sat):
                sat.add(name)
                changed = True
    return sat


def _record_satisfiable(rec: Record, sat: Set[str]) -> bool:
    for f in rec.fields:
        if f.min < 1:
            continue                      # optional -- never blocks satisfiability
        if isinstance(f.type, (Scalar, AnyType)):
            continue
        if f.type.name not in sat:
            return False
    return True


def is_empty(s: Schema) -> bool:
    """True iff ``s``'s root record is unsatisfiable -- the schema's
    language (the set of documents it accepts) is empty."""
    return s.root.name not in satisfiable_set(s)


def prune(s: Schema) -> Schema:
    """An equivalent schema with everything that can never match removed:

    * records unreachable from root (following refs) are dropped;
    * fields with ``max == 0`` are dropped (never emittable);
    * optional (``min == 0``) fields whose type is an unsatisfiable record
      are dropped (they could never actually be emitted either);
    * records left unreachable/unsatisfiable after the above are dropped
      from the environment too.

    **Root-unsatisfiable case.** If the root record itself is unsatisfiable
    (every finite document is rejected -- ``is_empty()`` is True), field
    pruning is *not* applied to the root: its mandatory fields are exactly
    what make it unsatisfiable, and stripping them would silently produce a
    *different*, satisfiable schema, contradicting "prune returns an
    equivalent schema." Instead the root record is kept as-is and only the
    rest of the environment is reduced to what's reachable from it (which,
    being unsatisfiable, typically collapses to the cyclic core itself).
    This mirrors the paper's treatment of an unsatisfiable start state --
    MakeUsefulSA modifies the automaton rather than rejecting it outright.
    """
    sat = satisfiable_set(s)
    root_ok = s.root.name in sat

    reachable = _reachable(s, sat, root_ok)

    new_env: Dict[str, Record] = {}
    for name in reachable:
        rec = s.env[name]
        if not root_ok and name == s.root.name:
            new_env[name] = rec           # keep the unsatisfiable root intact
        else:
            new_env[name] = _prune_record(rec, sat)
    return Schema(Ref(s.root.name), new_env)


def _reachable(s: Schema, sat: Set[str], root_ok: bool) -> Set[str]:
    """Names reachable from root by following refs through kept fields --
    a field is "kept" if it survives ``_prune_record``, except the
    unsatisfiable root itself, whose fields are all kept as-is (it isn't
    pruned; see :func:`prune`'s docstring)."""
    seen: Set[str] = set()
    stack = [s.root.name]
    while stack:
        name = stack.pop()
        if name in seen or name not in s.env:
            continue
        seen.add(name)
        rec = s.env[name]
        is_unpruned_root = (name == s.root.name) and not root_ok
        for f in rec.fields:
            if not is_unpruned_root:
                if f.max == 0:
                    continue
                if f.min == 0 and isinstance(f.type, Ref) and f.type.name not in sat:
                    continue
            if isinstance(f.type, Ref):
                stack.append(f.type.name)
    return seen


def _prune_record(rec: Record, sat: Set[str]) -> Record:
    kept = []
    for f in rec.fields:
        if f.max == 0:
            continue
        if f.min == 0 and isinstance(f.type, Ref) and f.type.name not in sat:
            continue
        kept.append(Field(f.label, f.type, f.min, f.max))
    return Record(kept)
