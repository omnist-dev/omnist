"""Subschema compatibility and equivalence.

Implements the paper's Algorithm 4 (SubschemaSA) restricted to omnist's
counting cardinality languages; ``equivalent`` is bidirectional inclusion.

Algorithm 4 assumes its precondition MakeUsefulSA (useless-state removal,
``ops/prune.py``) has already run: the coinductive cycle rule below only
coincides with true (finite-document) language inclusion once every A-side
record is known satisfiable. Rather than requiring callers to pre-prune,
``compatible_with`` computes ``a``'s satisfiable set once up front and
``_sub``/``_record_sub`` consult it directly -- an unsatisfiable A-side
record is vacuously a subschema of anything (it emits no documents at all),
and an optional A-field whose type is unsatisfiable is skipped (it can
never actually be emitted, so it imposes no obligation on B). See
``docs/design/model.md`` for the full satisfiability subsection.
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from ..schema import Record, Ref, Scalar, Schema
from .prune import satisfiable_set


def compatible_with(a: Schema, b: Schema) -> bool:
    """True if every document ``a`` accepts is also accepted by ``b``
    (``a`` is a subschema / ``b`` is backward-compatible)."""
    sat_a = satisfiable_set(a)
    return _sub(a, a.root, b, b.root, sat_a, {})


def equivalent(a: Schema, b: Schema) -> bool:
    """True if both schemas accept exactly the same documents."""
    return compatible_with(a, b) and compatible_with(b, a)


def _sub(sa: Schema, ta: Ref | Scalar, sb: Schema, tb: Ref | Scalar, sat_a: Set[str],
         memo: Dict[Tuple[int, int], bool]) -> bool:
    if isinstance(ta, Ref) and ta.name not in sat_a:
        return True                       # vacuous: an unsatisfiable A-side record
    da = sa.resolve(ta)
    db = sb.resolve(tb)
    key = (id(da), id(db))
    if key in memo:
        return memo[key]
    memo[key] = True                      # coinductive assumption while descending
    if isinstance(da, Scalar) and isinstance(db, Scalar):
        result = _scalar_sub(da, db)
    elif isinstance(da, Record) and isinstance(db, Record):
        result = _record_sub(sa, da, sb, db, sat_a, memo)
    else:
        result = False                     # a value vs an object — never compatible
    memo[key] = result
    return result


def _scalar_sub(a: Scalar, b: Scalar) -> bool:
    if a.nullable and not b.nullable:
        return False
    if a.name == b.name:
        return True
    return a.name == "integer" and b.name == "number"   # the one subset relation


def _record_sub(sa: Schema, a: Record, sb: Schema, b: Record, sat_a: Set[str],
                memo: Dict[Tuple[int, int], bool]) -> bool:
    # Every label A may emit must be allowed by B, with a cardinality range
    # B's covers and a type B accepts.
    for fa in a.fields:
        if fa.max == 0:
            continue                      # A never emits this label
        if (fa.min == 0 and isinstance(fa.type, Ref)
                and fa.type.name not in sat_a):
            continue                      # A never actually emits this label either
        fb = b.field(fa.label)
        if fb is None:
            return False                  # B is closed and has no such field
        if not (fb.min <= fa.min and _le(fa.max, fb.max)):
            return False                  # [fa.min,fa.max] not a subset of B's range
        if not _sub(sa, fa.type, sb, fb.type, sat_a, memo):
            return False
    # Every label B *requires* must be guaranteed by A.
    for fb in b.fields:
        if fb.min >= 1:
            fa_opt = a.field(fb.label)
            if fa_opt is None or fa_opt.min < fb.min:
                return False
    return True


def _le(x: Optional[int], y: Optional[int]) -> bool:
    """x <= y, treating None as +infinity (unbounded max)."""
    if y is None:
        return True
    if x is None:
        return False
    return x <= y
