"""The Schema model — two state kinds plus naming, per ``docs/design/model.md``.

* **Record** — a closed set of fields, each ``(label, type, cardinality)``;
  constrained by its child labels.  Cardinality is the *unordered* number of
  times a label may appear.
* **Scalar** — one of exactly seven predefined value types (``string``,
  ``integer``, ``number``, ``boolean``, ``date``, ``time``, ``datetime``),
  optionally nullable.  There is no user-declared scalar/value-domain
  composition — a field's value side is always exactly one of the seven, never
  a union, an enum, or a literal.  (See ``docs/design/model.md`` for why: a
  composable value-domain made schema-directed deserialization ambiguous — a
  value could satisfy more than one candidate representation with no
  principled way to choose.)
* **Ref** — a pointer into the schema's named environment (records only);
  enables reuse and recursion.

A field's ``type`` is a ``Ref`` (to a named record) or a ``Scalar``.  There
are no inline records and no separate array type — "array" is just a field
with cardinality ``max > 1``.  Validation ignores order.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Any, Dict, List, NamedTuple, Optional, Union

from .errors import SchemaError

SCALAR_NAMES = {"string", "integer", "number", "boolean", "date", "time", "datetime"}

# The one definition of the documented temporal spellings (hyphenated date,
# colon time, 'T'-joined datetime) shared by every consumer that needs to
# tell "is this string shaped like a date/time/datetime" from "is it merely
# something `datetime.fromisoformat` happens to also accept" -- OML's own
# tokenizer (``oml.py``) and schema-directed deserialization (``deserialize.py``)
# both import these rather than each defining their own copy.  `fromisoformat`
# is deliberately wider than this: it also admits ISO 8601 basic format
# (``20240101``), week dates (``2024-W01-1``), and other spellings the docs
# never promise, so a shape check against these patterns must run *before*
# handing the string to `fromisoformat` for conversion -- see `_is_iso` below
# and `deserialize._materialize_temporal`.
_DATE_RE = _re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_RE = _re.compile(r"\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?([+\-]\d{2}:\d{2})?")
_DATETIME_RE = _re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?([+\-]\d{2}:\d{2})?")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Scalar:
    """One of the seven predefined value types, optionally nullable.

    ``STRING``, ``INTEGER``, … (also under ``t.*``) are ready-to-use,
    non-nullable instances — a field's type can be one of them directly,
    with no wrapping needed.  Use :func:`nullable` for the ``?`` form.
    """
    __slots__ = ("name", "nullable")

    def __init__(self, name: str, nullable: bool = False) -> None:
        if name not in SCALAR_NAMES:
            raise SchemaError(f"unknown scalar {name!r}; expected one of "
                              f"{sorted(SCALAR_NAMES)}")
        self.name = name
        self.nullable = bool(nullable)

    def __repr__(self) -> str:
        return f"{self.name}{'?' if self.nullable else ''}"

    def __eq__(self, other: Any) -> bool:
        return (isinstance(other, Scalar) and other.name == self.name
                and other.nullable == self.nullable)

    def __hash__(self) -> int:
        return hash((Scalar, self.name, self.nullable))


STRING = Scalar("string")
INTEGER = Scalar("integer")
NUMBER = Scalar("number")
BOOLEAN = Scalar("boolean")
DATE = Scalar("date")
TIME = Scalar("time")
DATETIME = Scalar("datetime")


class _Types:
    """The seven scalars under one namespace: ``t.string``, ``t.integer``, …

    Namespaced so they never shadow builtins or the stdlib ``datetime`` names.
    Each is a ready-to-use :class:`Scalar` — pass it directly as a field's
    type, e.g. ``field("name", t.string)``.
    """
    string = STRING
    integer = INTEGER
    number = NUMBER
    boolean = BOOLEAN
    date = DATE
    time = TIME
    datetime = DATETIME

    def __repr__(self) -> str:
        return ("omnist.t — the seven scalars: string, integer, number, "
                "boolean, date, time, datetime")


t = _Types()


def nullable(scalar: Scalar) -> Scalar:
    """A copy of ``scalar`` that also accepts ``null`` (the ``?`` form)."""
    return scalar if scalar.nullable else Scalar(scalar.name, True)


class Ref:
    """A reference to a named record."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"ref({self.name})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Ref) and other.name == self.name

    def __hash__(self) -> int:
        return hash((Ref, self.name))


Type = Union[Ref, Scalar]


class Field:
    """One named, cardinality-bound field slot of a record: ``label`` of
    ``type``, occurring ``[min, max]`` times (``max=None`` is unbounded)."""

    __slots__ = ("label", "type", "min", "max")

    def __init__(self, label: str, type: Type, min: int = 1,
                 max: Optional[int] = 1) -> None:
        if not isinstance(type, (Ref, Scalar)):
            raise SchemaError(f"field {label!r} type must be a Ref or Scalar, got {type!r}")
        if min < 0 or (max is not None and max < min):
            raise SchemaError(f"field {label!r} has an invalid cardinality [{min},{max}]")
        self.label = label
        self.type = type
        self.min = min
        self.max = max

    def cardinality_str(self) -> str:
        if (self.min, self.max) == (1, 1):
            return "exactly 1"
        if (self.min, self.max) == (0, 1):
            return "0 or 1"
        if self.max is None:
            return f"at least {self.min}"
        return f"between {self.min} and {self.max}"

    def __repr__(self) -> str:
        hi = "" if self.max is None else self.max
        return f"Field({self.label!r}[{self.min},{hi}]: {self.type!r})"


class Record:
    """A closed set of named fields (constrained by its child labels)."""

    __slots__ = ("fields", "_by_label")

    def __init__(self, fields: List[Field]) -> None:
        self.fields = list(fields)
        self._by_label: Dict[str, Field] = {}
        seen = set()
        for f in self.fields:
            if f.label in seen:
                raise SchemaError(f"duplicate field label {f.label!r} in a record")
            seen.add(f.label)
            self._by_label[f.label] = f

    def field(self, label: str) -> Optional[Field]:
        return self._by_label.get(label)

    def __repr__(self) -> str:
        return "record{" + ", ".join(repr(f) for f in self.fields) + "}"


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class Error(NamedTuple):
    path: str
    message: str
    # stable machine-readable code: unexpected-field, cardinality,
    # type-mismatch, null-not-allowed, shape-mismatch
    code: str


class ValidationResult:
    def __init__(self) -> None:
        self.errors: List[Error] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, path: str, message: str, code: str) -> None:
        self.errors.append(Error(path, message, code))

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return "valid"
        return "invalid:\n" + "\n".join(f"  at {e.path}: {e.message}" for e in self.errors)

    def __repr__(self) -> str:
        return f"ValidationResult(ok={self.ok}, errors={len(self.errors)})"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class Schema:
    """A schema: a root reference plus an environment of named records."""

    def __init__(self, root: Ref, env: Optional[Dict[str, Record]] = None) -> None:
        if not isinstance(root, Ref):
            raise SchemaError("a schema root must be a Ref to a named record")
        self.root = root
        self.env: Dict[str, Record] = dict(env or {})
        self.check_refs()

    def resolve(self, t: Type) -> Union[Record, Scalar]:
        """A bare ``Scalar`` resolves to itself; a ``Ref`` is a single environment
        lookup -- env values are always Records (enforced by ``check_refs``), so
        ref chains cannot occur."""
        if isinstance(t, Scalar):
            return t
        if t.name not in self.env:
            raise SchemaError(f"unknown type {t.name!r}")
        return self.env[t.name]

    def check_refs(self) -> None:
        for name, rec in self.env.items():
            if not isinstance(rec, Record):
                raise SchemaError(
                    f"environment entry {name!r} must be a Record, got {rec!r}")

        def walk(t: Type) -> None:
            if isinstance(t, Ref) and t.name not in self.env:
                raise SchemaError(f"unknown type {t.name!r}")
        walk(self.root)
        for rec in self.env.values():
            for f in rec.fields:
                walk(f.type)
        # every env value is now known to be a Record (checked above), and
        # root is always a Ref (checked in __init__), so resolve(root) always
        # lands on a Record once the walk above confirms root.name is known.

    # -- validation -----------------------------------------------------
    def validate(self, doc: Any) -> ValidationResult:
        from .document import Doc
        if not isinstance(doc, Doc):
            raise TypeError("validate() expects a Doc; wrap your data with doc(...)")
        res = ValidationResult()
        self._conform(doc, self.root, res)
        return res

    def accepts(self, doc: Any) -> bool:
        return self.validate(doc).ok

    def _conform(self, doc: Any, t: Type, res: ValidationResult) -> None:
        d = self.resolve(t)
        if isinstance(d, Scalar):
            self._conform_scalar(doc, d, res)
        else:
            self._conform_record(doc, d, res)

    def _conform_scalar(self, doc: Any, s: Scalar, res: ValidationResult) -> None:
        if not doc.is_leaf:
            res.add(doc.path, f"expected a {s.name} value, got an object", "shape-mismatch")
            return
        v = doc.value
        if v is None:
            if not s.nullable:
                res.add(doc.path, "null not allowed here", "null-not-allowed")
            return
        if not matches_kind(v, s.name):
            res.add(doc.path, f"expected {s.name}, got {_typename(v)} ({v!r})", "type-mismatch")

    def _conform_record(self, doc: Any, rec: Record, res: ValidationResult) -> None:
        if doc.is_leaf:
            res.add(doc.path, "expected an object, got a value", "shape-mismatch")
            return
        counts: Dict[str, int] = {}
        for label, child in doc.edges():
            counts[label] = counts.get(label, 0) + 1
            f = rec.field(label)
            if f is None:
                res.add(child.path, "unexpected field", "unexpected-field")
            else:
                self._conform(child, f.type, res)
        for f in rec.fields:
            c = counts.get(f.label, 0)
            if c < f.min or (f.max is not None and c > f.max):
                res.add(doc.path,
                        f"field {f.label!r} occurs {c} time(s), expected {f.cardinality_str()}",
                        "cardinality")

    # -- comparison (delegate to operations) ----------------------------
    def compatible_with(self, other: "Schema") -> bool:
        """True if every document this schema accepts is also accepted by
        ``other`` (this is a subschema; ``other`` is backward-compatible)."""
        from .ops import compatible_with
        return compatible_with(self, other)

    def equivalent(self, other: "Schema") -> bool:
        """True if both schemas accept exactly the same documents."""
        from .ops import equivalent
        return equivalent(self, other)

    def normalize(self) -> "Schema":
        """The canonical minimal schema equivalent to this one: fewest env
        records, unique up to naming (via partition refinement)."""
        from .ops import normalize
        return normalize(self)

    def is_empty(self) -> bool:
        """True iff this schema's root record is unsatisfiable -- no finite
        document conforms to it (the schema's language is empty)."""
        from .ops import is_empty
        return is_empty(self)

    def prune(self) -> "Schema":
        """An equivalent schema with everything that can never match
        removed: unreachable records, never-emittable (``max == 0``)
        fields, and optional fields whose type can never be satisfied."""
        from .ops import prune
        return prune(self)

    def extract(self, *labels: str) -> "Schema":
        """The minimal subschema that only recognizes documents built from
        ``labels`` (paper Algorithm 5, ExtractSubschema). Fields whose label
        isn't in ``labels`` are dropped; if that deletes a mandatory
        (``min >= 1``) field, the record that had it -- and transitively
        anything that mandatorily depends on it -- is invalidated. Raises
        :class:`~omnist.SchemaError` if the root itself ends up invalidated
        (no valid subschema exists for this label set)."""
        from .ops import extract
        return extract(self, labels)

    # -- serialization --------------------------------------------------
    def to_osd(self, *, indent: Optional[int] = 4) -> str:
        from .osd import to_osd
        return to_osd(self, indent=indent)

    def __repr__(self) -> str:
        return f"Schema(root={self.root!r}, env={list(self.env)})"


# ---------------------------------------------------------------------------
# Value matching
# ---------------------------------------------------------------------------

def matches_kind(value: Any, name: str) -> bool:
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "date":
        if isinstance(value, _dt.datetime):
            return False
        if isinstance(value, _dt.date):
            return True
        return _is_iso(value, _dt.date)
    if name == "time":
        if isinstance(value, _dt.time):
            return True
        return _is_iso(value, _dt.time)
    if name == "datetime":
        if isinstance(value, _dt.datetime):
            return True
        # datetime.fromisoformat is lenient: a bare date-only string ("2024-
        # 01-01") parses fine, defaulting the missing time to midnight. That
        # silently treats "no time given" as "the time is exactly midnight" --
        # not the same value. Require that the string isn't ALSO a bare date.
        return _is_iso(value, _dt.datetime) and not _is_iso(value, _dt.date)
    return False


_SHAPE_RE = {_dt.date: _DATE_RE, _dt.time: _TIME_RE, _dt.datetime: _DATETIME_RE}


def _is_iso(value: Any, cls: type[Any]) -> bool:
    if not isinstance(value, str):
        return False
    if not _SHAPE_RE[cls].fullmatch(value):
        return False          # narrower than fromisoformat -- see _DATE_RE etc. above
    try:
        cls.fromisoformat(value)
        return True
    except ValueError:
        return False


def value_kind(v: Any) -> str:
    """The most specific scalar name a Python value matches, for inference
    and error messages (``integer`` is reported even though it also matches
    ``number`` — callers needing the wider check use :func:`matches_kind`)."""
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, _dt.datetime):
        return "datetime"
    if isinstance(v, _dt.date):
        return "date"
    if isinstance(v, _dt.time):
        return "time"
    return "string"


def _typename(v: Any) -> str:
    return "null" if v is None else value_kind(v)


# ---------------------------------------------------------------------------
# Python builders
# ---------------------------------------------------------------------------

def field(label: str, type: Type, min: int = 1, max: Optional[int] = 1) -> Field:
    return Field(label, type, min, max)


def record(*fields: Field) -> Record:
    return Record(list(fields))


def ref(name: str) -> Ref:
    return Ref(name)


def schema(root: Union[Ref, str], **env: Record) -> Schema:
    r = Ref(root) if isinstance(root, str) else root
    return Schema(r, env)
