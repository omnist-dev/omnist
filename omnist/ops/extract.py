"""Subschema extraction (paper Algorithm 5, ExtractSubschema).

Given a schema and a set of *permissible labels* ``keep`` (the paper's
``X'``), produces the minimal subschema that recognizes only documents built
from those labels -- the headline application in the paper is trimming a
large shared schema (xCBL) down to just what a single document type needs
(reported there as a 6-32% size reduction).

Algorithm:

1. For every record in the env, delete any field whose label is not in
   ``keep``.
2. If a deleted field had ``min >= 1`` (mandatory), that record is
   *invalidated* -- the paper's "state removed": there is no way to build a
   document at that record's shape without a label that's no longer
   available, so the record itself can no longer be produced.
3. **Propagate.** A record with a *mandatory* field whose type is an
   invalidated record is itself invalidated (that field can never be
   filled), and so on transitively -- a least-fixpoint closure, same shape
   as ``ops/prune.py``'s satisfiability fixpoint.
4. If the root ends up invalidated, there is no valid subschema for this
   ``keep`` set at all: :func:`extract` raises :class:`~omnist.SchemaError`
   naming the first offending label and record, so the failure is
   actionable.
5. Otherwise, invalidated records (and fields typed to them, along with any
   fields already dropped in step 1) are gone; the result is run through
   :func:`~omnist.ops.prune.prune` and
   :func:`~omnist.ops.minimize.normalize` (Algorithm 5's own
   final MakeUseful + Minimize step) to land in the same canonical minimal
   form ``normalize()`` produces elsewhere.

**Design decision: mandatory deletion is an error, not silently-optional.**
An alternative design could relax a deleted mandatory field to optional
instead of invalidating its record. This implementation deliberately does
not do that: silently loosening cardinality would mean `extract`'s result
no longer reflects the paper's Algorithm 5 semantics (which reports "no
valid subschema" rather than inventing a weaker one), and it would hide a
likely mistake -- asking to keep a leaf label without any of the mandatory
structure that leads to it is far more often a bug in the caller's `keep`
set than an intentional relaxation. Callers who do want the relaxed
behavior can trivially get it by editing field cardinalities before calling
`extract`.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set

from ..errors import SchemaError
from ..schema import Record, Ref, Schema
from .minimize import normalize
from .prune import prune


def extract(s: Schema, keep: Iterable[str]) -> Schema:
    """The minimal subschema of ``s`` that only recognizes documents built
    from labels in ``keep``. Raises :class:`SchemaError` if deleting the
    other labels would invalidate the root record (see module docstring)."""
    keep_set: Set[str] = set(keep)

    # Step 1+2: per-record field deletion, tracking which records are
    # directly invalidated by the loss of a mandatory field, and the first
    # offending (label, record) pair for the error message.
    trimmed: Dict[str, Record] = {}
    invalidated: Set[str] = set()
    first_offender: Optional[tuple[str, str]] = None

    for name, rec in s.env.items():
        kept_fields = []
        for f in rec.fields:
            if f.label in keep_set:
                kept_fields.append(f)
            elif f.min >= 1:
                if name not in invalidated and first_offender is None:
                    first_offender = (f.label, name)
                invalidated.add(name)
        trimmed[name] = Record(kept_fields)

    # Step 3: propagate invalidation -- a record with a mandatory field
    # typed to an invalidated record is itself invalidated. Least fixpoint,
    # same shape as prune.py's satisfiable_set.
    changed = True
    while changed:
        changed = False
        for name, rec in trimmed.items():
            if name in invalidated:
                continue
            for f in rec.fields:
                if f.min >= 1 and isinstance(f.type, Ref) and f.type.name in invalidated:
                    # first_offender is always already set here: this branch
                    # can only run once `invalidated` is non-empty, and it's
                    # only ever seeded by step 1, which sets first_offender
                    # itself before propagation ever begins.
                    invalidated.add(name)
                    changed = True
                    break

    # Step 4: root invalidated -> no valid subschema.
    if s.root.name in invalidated:
        assert first_offender is not None  # seeded by step 1 before any propagation
        label, record_name = first_offender
        raise SchemaError(
            f"no valid subschema: removing label {label!r} deletes a mandatory "
            f"field of record {record_name!r}")

    # Step 5: drop invalidated records and any fields (mandatory or not)
    # that still point at one -- an optional field typed to an invalidated
    # record can never be satisfied either, so prune() will remove it, but
    # we drop it here too so the intermediate Schema stays ref-consistent
    # (env values must all be reachable/defined; an invalidated record is
    # about to disappear from the env entirely).
    new_env: Dict[str, Record] = {}
    for name, rec in trimmed.items():
        if name in invalidated:
            continue
        fields = [
            f for f in rec.fields
            if not (isinstance(f.type, Ref) and f.type.name in invalidated)
        ]
        new_env[name] = Record(fields)

    result = Schema(Ref(s.root.name), new_env)
    return normalize(prune(result))
