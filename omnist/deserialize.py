"""Schema-directed deserialization: make a freshly-read node conform to a
:class:`~omnist.schema.Schema`, or raise.

Readers (``read_json``, etc.) hand back text-shaped values: JSON/YAML/TOML
have no ``date``/``time`` type, so a temporal field arrives as an ISO-8601
string; a whole-number ``float`` may need to become an ``int`` (or vice
versa) to match what the schema declares. Passing ``schema=`` to a reader is
the request for a Document that's *guaranteed* to conform to that schema:
:func:`materialize` walks the node together with the schema, upgrading each
leaf **only when the conversion is value-exact** -- ``"2024-01-01" -> date``,
``1.0 -> int 1`` -- and checking every record's shape (closed fields,
cardinality) along the way, exactly as :meth:`Schema.validate` would. If
anything can't be made to conform -- an inexact scalar, an unknown field, a
missing field, the wrong cardinality -- :func:`materialize` collects *every*
such problem (not just the first) and raises one
:class:`~omnist.errors.ParseError` with the full report.

This can't simply delegate to :meth:`Schema.validate` after the fact:
``validate`` only ever *checks* a value already in its final form, with no
notion of upgrading, and it would mean a second, redundant top-down walk of
the same tree using different traversal code. Since :func:`materialize`
already knows, at every node, exactly which field/type the schema expects
there, upgrading and shape-checking happen together in one pass.

There's no ``strict=`` switch: a schema is either given, in which case the
result is guaranteed to conform (or an error is raised), or it isn't, in
which case the node is returned exactly as read, untouched -- ``schema=None``
is the existing, well-defined way to opt out of validation entirely.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .errors import ParseError
from .schema import Record, Scalar, Schema, ValidationResult, _is_iso

_TEMPORAL_CLASS = {"date": _dt.date, "time": _dt.time, "datetime": _dt.datetime}


def materialize(node: Any, schema: Schema) -> Any:
    """A copy of ``node`` with leaf values upgraded to match ``schema``,
    guaranteed to conform to it -- raises :class:`~omnist.errors.ParseError`
    (with every problem found, not just the first) if it can't be made to."""
    res = ValidationResult()
    out = _materialize_type(node, schema, schema.root, "$", res)
    if not res.ok:
        raise ParseError(str(res))
    return out


def _materialize_type(node: Any, schema: Schema, t: Any, path: str,
                       res: ValidationResult) -> Any:
    d = schema.resolve(t)
    if isinstance(d, Scalar):
        return _materialize_scalar(node, d, path, res)
    return _materialize_record(node, schema, d, path, res)


def _materialize_record(node: Any, schema: Schema, rec: Record, path: str,
                         res: ValidationResult) -> Any:
    if not isinstance(node, list):
        res.add(path, "expected an object, got a value", "shape-mismatch")
        return node
    out: list[tuple[str, Any]] = []
    counts: dict[str, int] = {}
    for label, child in node:
        i = counts.get(label, 0)
        counts[label] = i + 1
        p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
        f = rec.field(label)
        if f is None:
            res.add(p, "unexpected field", "unexpected-field")
            out.append((label, child))
        else:
            out.append((label, _materialize_type(child, schema, f.type, p, res)))
    for f in rec.fields:
        c = counts.get(f.label, 0)
        if c < f.min or (f.max is not None and c > f.max):
            res.add(path,
                    f"field {f.label!r} occurs {c} time(s), expected {f.cardinality_str()}",
                    "cardinality")
    return out


def _materialize_scalar(value: Any, s: Scalar, path: str, res: ValidationResult) -> Any:
    if isinstance(value, list):
        res.add(path, f"expected a {s.name} value, got an object", "shape-mismatch")
        return value
    if value is None:
        if not s.nullable:
            res.add(path, "null not allowed here", "null-not-allowed")
        return value
    if s.name == "string":
        if isinstance(value, str):
            return value
    elif s.name == "boolean":
        if isinstance(value, bool):
            return value
    elif s.name == "integer":
        if isinstance(value, bool):
            pass
        elif isinstance(value, int):
            return value
        elif isinstance(value, float) and value.is_integer():
            return int(value)
    elif s.name == "number":
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            return float(value)
    elif s.name in _TEMPORAL_CLASS:
        converted = _materialize_temporal(value, s.name)
        if converted is not _SENTINEL:
            return converted
    res.add(path, f"{value!r} cannot be read as {s.name} (not a value-exact conversion)",
            "type-mismatch")
    return value


_SENTINEL = object()


def _materialize_temporal(value: Any, name: str) -> Any:
    cls = _TEMPORAL_CLASS[name]
    if isinstance(value, cls):
        if name == "date" and isinstance(value, _dt.datetime):
            return _SENTINEL               # datetime is a date subclass -- not this kind
        return value
    # Shape-check against the documented hyphenated/colon spellings *before*
    # converting -- `fromisoformat` on its own is wider (basic format like
    # "20240101", week dates like "2024-W01-1", ...) than anything the docs
    # or OML's grammar define, and `matches_kind` (schema.py, used by
    # `validate()`) applies the exact same shape check via `_is_iso`, so the
    # two stay in agreement: a string only ever materializes here if
    # `validate()` would also have accepted it.
    #
    # This shape check is also what keeps "a bare date string is not a
    # datetime" true without a separate sentinel case: schema.py's
    # _DATETIME_RE requires a literal 'T' separator that _DATE_RE never has,
    # so no string can ever fullmatch both -- "2024-01-01" fails _is_iso(...,
    # datetime) outright, it never reaches fromisoformat here at all.
    if not _is_iso(value, cls):
        return _SENTINEL
    return cls.fromisoformat(value)  # type: ignore[attr-defined]
