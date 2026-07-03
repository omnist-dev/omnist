"""OSD (Omnist Schema Definition) — the text language for the Schema model.

Grammar (informal)::

    schema      := record* 'root' NAME
    record      := 'record' NAME '{' field (',' field)* ','? '}'
    field       := STRING cardinality? ':' type
    cardinality := '[' INT? (',' INT?)? ']'          -- [m,n] [m,] [,n] [n]; absent = [1,1]
    type        := SCALARNAME '?'? | NAME            -- one scalar, or one Ref

Quoting rule: a ``"quoted"`` token is a data string (always a field label —
there is no other use for a string literal in this grammar); an unquoted
identifier is a schema name (a scalar keyword, or a ``Ref``).

There is no value-domain composition: no ``|``, no enum, no literal-valued
fields, and no ``union``/``domain`` declaration.  A field's type is always
either one of the seven scalars (``string``, ``integer``, ``number``,
``boolean``, ``date``, ``time``, ``datetime``), optionally ``?``, or a
``Ref`` to a named record.  See ``docs/design/model.md`` for why: a
composable value-domain made schema-directed deserialization ambiguous.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .errors import SchemaError
from .schema import SCALAR_NAMES, Field, Record, Ref, Scalar, Schema

_TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<comment>\#[^\n]*)
    | (?P<string>"(?:\\.|[^"\\])*")
    | (?P<number>-?\d+\.\d+|-?\d+)
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<punct>[{}\[\]:,?])
""", re.VERBOSE)


class _Tok:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind: str, text: str, pos: int) -> None:
        self.kind, self.text, self.pos = kind, text, pos


def _tokenize(text: str) -> List[_Tok]:
    toks: List[_Tok] = []
    i = 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise SchemaError(f"unexpected character {text[i]!r} at {i}")
        i = m.end()
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        toks.append(_Tok(kind or "", m.group() or "", m.start()))
    toks.append(_Tok("eof", "", len(text)))
    return toks


def _unquote(s: str) -> str:
    return re.sub(r'\\(.)', r'\1', s[1:-1])


class _Parser:
    def __init__(self, toks: List[_Tok]) -> None:
        self.toks = toks
        self.i = 0

    def _peek(self) -> _Tok:
        return self.toks[self.i]

    def _next(self) -> _Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def _expect(self, kind: str, text: Optional[str] = None) -> _Tok:
        t = self._next()
        if t.kind != kind or (text is not None and t.text != text):
            want = text or kind
            raise SchemaError(f"expected {want!r} at {t.pos}, got {t.text!r}")
        return t

    def parse(self) -> Schema:
        env: dict[str, Record] = {}
        root: Optional[str] = None
        while self._peek().kind != "eof":
            t = self._peek()
            if t.kind == "name" and t.text == "record":
                name, rec = self._record()
                self._define(env, name, rec)
            elif t.kind == "name" and t.text == "root":
                self._next()
                root = self._expect("name").text
            else:
                raise SchemaError(f"expected 'record' or 'root' at {t.pos}, "
                                  f"got {t.text!r}")
        if root is None:
            raise SchemaError("a schema must declare a root")
        return Schema(Ref(root), env)

    def _define(self, env: dict[str, Record], name: str, rec: Record) -> None:
        if name in SCALAR_NAMES:
            raise SchemaError(
                f"{name!r} is a reserved scalar name; a record cannot be "
                "defined with this name, or it could never be referenced "
                "(a bare name in a type position always means the builtin "
                "scalar)")
        if name in env:
            raise SchemaError(f"duplicate definition {name!r}")
        env[name] = rec

    def _record(self) -> tuple[str, Record]:
        self._expect("name", "record")
        name = self._expect("name").text
        self._expect("punct", "{")
        fields: List[Field] = []
        while self._peek().text != "}":
            fields.append(self._field())
            if self._peek().text == ",":
                self._next()
            else:
                break
        self._expect("punct", "}")
        return name, Record(fields)

    def _field(self) -> Field:
        label_tok = self._next()
        if label_tok.kind != "string":
            raise SchemaError(f"expected a quoted field name at {label_tok.pos}, "
                              f"got {label_tok.text!r}")
        label = _unquote(label_tok.text)
        lo: int = 1
        hi: Optional[int] = 1
        if self._peek().text == "[":
            lo, hi = self._cardinality()
        self._expect("punct", ":")
        typ = self._type()
        return Field(label, typ, lo, hi)

    def _cardinality(self) -> tuple[int, Optional[int]]:
        self._expect("punct", "[")
        first: Optional[int] = None
        if self._peek().kind == "number":
            first = self._cardinality_int()
        if self._peek().text == ",":
            self._next()
            second: Optional[int] = None
            if self._peek().kind == "number":
                second = self._cardinality_int()
            lo = first if first is not None else 0
            hi = second
        else:
            if first is None:
                raise SchemaError(f"empty cardinality at {self._peek().pos}")
            lo = hi = first
        self._expect("punct", "]")
        return lo, hi

    def _cardinality_int(self) -> int:
        t = self._next()
        if "." in t.text:
            raise SchemaError(f"cardinality must be a whole number, got {t.text!r} "
                              f"at {t.pos}")
        return int(t.text)

    def _type(self) -> Scalar | Ref:
        t = self._next()
        if t.kind != "name":
            raise SchemaError(
                f"expected a scalar name or a reference at {t.pos}, got {t.text!r} "
                "(enums and literal-valued fields are not supported -- a "
                "field's type is always one scalar or a reference to a "
                "named record)")
        nullable = False
        if self._peek().text == "?":
            self._next()
            nullable = True
        if t.text in SCALAR_NAMES:
            return Scalar(t.text, nullable)
        if nullable:
            raise SchemaError(
                f"'?' cannot apply to the reference {t.text!r}; use "
                "cardinality [0,1] for an optional field")
        return Ref(t.text)


def parse_schema(text: str) -> Schema:
    """Parse OSD text into a :class:`~omnist.schema.Schema`."""
    return _Parser(_tokenize(text)).parse()


# ---------------------------------------------------------------------------
# Serialize a Schema back to OSD text
# ---------------------------------------------------------------------------

def to_osd(schema: Schema, *, indent: Optional[int] = 4) -> str:
    """Serialize a Schema back to OSD text.

    ``indent=None`` renders a single-line, machine-oriented form (record
    defs and the ``root`` statement joined by spaces, fields joined by
    ``", "``, no trailing comma) instead of the default pretty-printed,
    indented form -- mirroring ``write_oml``/``write_json``'s own
    ``indent=None`` convention. A non-``None`` int sets the pretty-mode
    indent width (default 4, matching the prior hardcoded behavior). Both
    forms round-trip through ``parse_schema``.
    """
    parts: List[str] = [_record(name, rec, indent) for name, rec in schema.env.items()]
    parts.append(f"root {schema.root.name}")
    if indent is None:
        return " ".join(parts) + "\n"
    return "\n".join(parts) + "\n"


def _record(name: str, rec: Record, indent: Optional[int]) -> str:
    if indent is None:
        fields = ", ".join(_field(f) for f in rec.fields)
        return f"record {name} {{ {fields} }}"
    pad = " " * indent
    out = [f"record {name} {{"]
    for f in rec.fields:
        out.append(f"{pad}{_field(f)},")
    out.append("}")
    return "\n".join(out)


def _field(f: Field) -> str:
    card = "" if (f.min, f.max) == (1, 1) else f" {_card(f.min, f.max)}"
    return f'"{f.label}"{card}: {_type(f.type)}'


def _card(lo: int, hi: Optional[int]) -> str:
    if lo == hi:
        return f"[{lo}]"
    return f"[{lo},{'' if hi is None else hi}]"


def _type(t: Scalar | Ref) -> str:
    if isinstance(t, Ref):
        return t.name
    return f"{t.name}{'?' if t.nullable else ''}"
