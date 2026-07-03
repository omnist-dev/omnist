"""Field-signature helpers for schema minimization (and, later, isomorphism).

``local_signature`` is the target-blind structural key used as the
*initial* partition for MinimizeSA (issue #140, ``ops/minimize.py``): a
key including ref target names would be too strong a starting point --
records that turn out to be equivalent because their ref targets are
themselves equivalent-but-differently-named would never even land in the
same starting block. It captures a field's label, cardinality, and
scalar-or-ref *shape*, but excludes ref target names (those are compared
by evolving block id during refinement instead).
"""

from __future__ import annotations

from typing import Union

from ..schema import Record, Ref, Scalar


def local_signature(
    rec: Record,
) -> tuple[str, tuple[tuple[str, int, int | None, tuple[str, ...] | tuple[str, str, bool]], ...]]:
    """Target-blind structural key for a record: fields sorted by label,
    each keyed by ``(label, min, max, shape)`` where ``shape`` is
    ``("scalar", name, nullable)`` for a scalar field or ``("ref",)`` for a
    ref field -- the target record's *name* is deliberately excluded, since
    minimization must be free to merge records whose ref targets are
    themselves later found equivalent under different names.

    Fields are sorted by label rather than kept in declaration order:
    validation ignores field order (a ``Record`` is a *set* of labeled
    fields, per ``docs/design/model.md``), and OSD's printed field order is
    purely cosmetic. Two records that declare the same fields in a
    different order accept exactly the same documents and so MUST land in
    the same initial partition block -- keying by declaration order would
    incorrectly split them and could prevent them from ever merging.
    """
    fields = tuple(sorted(
        ((f.label, f.min, f.max, _shape_key(f.type)) for f in rec.fields),
        key=lambda t: t[0],
    ))
    return ("record", fields)


def _shape_key(t: Union[Ref, Scalar]) -> tuple[str, ...] | tuple[str, str, bool]:
    if isinstance(t, Ref):
        return ("ref",)
    return ("scalar", t.name, t.nullable)
