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
from .schema import ANY, SCALAR_NAMES, AnyType, Field, Record, Ref, Scalar, Schema

RESERVED_TYPE_NAMES = SCALAR_NAMES | {"any"}

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
            # A quote with no matching close is its own diagnosis
            # (Sec8.3.1 parse.unterminated-string) -- distinguish it from
            # every other unmatched-character case before falling back to
            # the generic parse.unexpected-token.
            if text[i] == '"':
                raise SchemaError(f"unterminated string starting at {i}",
                                  code="parse.unterminated-string", path=str(i))
            raise SchemaError(f"unexpected character {text[i]!r} at {i}",
                              code="parse.unexpected-token", path=str(i))
        i = m.end()
        kind = m.lastgroup
        if kind in ("ws", "comment"):
            continue
        if kind == "string":
            # #303/omnist-spec Sec5.3.1: a raw control character (< U+0020)
            # in a string body is an error -- matches OML's existing rule
            # (oml.py's _scan_string_slow). The tokenizer's regex alone
            # can't express "no control characters", so check the matched
            # text after the fact rather than complicating the pattern.
            text_val = m.group()
            for offset, ch in enumerate(text_val):
                if ord(ch) < 0x20:
                    pos = m.start() + offset
                    raise SchemaError(
                        f"control character U+{ord(ch):04X} in string at {pos}",
                        code="parse.control-character", path=str(pos))
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
            raise SchemaError(f"expected {want!r} at {t.pos}, got {t.text!r}",
                              code="parse.unexpected-token", path=str(t.pos))
        return t

    def parse(self) -> Schema:
        env: dict[str, Record] = {}
        root: Optional[str] = None
        while self._peek().kind != "eof":
            t = self._peek()
            if t.kind == "name" and t.text == "record":
                name, rec, name_pos = self._record()
                self._define(env, name, rec, name_pos)
            elif t.kind == "name" and t.text == "root":
                self._next()
                root = self._expect("name").text
            else:
                raise SchemaError(f"expected 'record' or 'root' at {t.pos}, "
                                  f"got {t.text!r}",
                                  code="parse.unexpected-token", path=str(t.pos))
        if root is None:
            raise SchemaError("a schema must declare a root", code="schema.no-root")
        return Schema(Ref(root), env)

    def _define(self, env: dict[str, Record], name: str, rec: Record,
                name_pos: int) -> None:
        if name in RESERVED_TYPE_NAMES:
            if name == "any":
                raise SchemaError(
                    "'any' is a reserved type name and cannot be used as a "
                    f"record name at {name_pos}",
                    code="schema.reserved-name", path=name)
            raise SchemaError(
                f"{name!r} is a reserved scalar name; a record cannot be "
                "defined with this name, or it could never be referenced "
                "(a bare name in a type position always means the builtin "
                "scalar)",
                code="schema.reserved-name", path=name)
        if name in env:
            raise SchemaError(f"duplicate definition {name!r}",
                              code="schema.duplicate-record", path=name)
        env[name] = rec

    def _record(self) -> tuple[str, Record, int]:
        self._expect("name", "record")
        name_tok = self._expect("name")
        name = name_tok.text
        self._expect("punct", "{")
        fields: List[Field] = []
        while self._peek().text != "}":
            fields.append(self._field())
            if self._peek().text == ",":
                self._next()
            else:
                break
        self._expect("punct", "}")
        return name, Record(fields), name_tok.pos

    def _field(self) -> Field:
        label_tok = self._next()
        if label_tok.kind != "string":
            raise SchemaError(f"expected a quoted field name at {label_tok.pos}, "
                              f"got {label_tok.text!r}",
                              code="schema.unquoted-label", path=str(label_tok.pos))
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
                raise SchemaError(f"empty cardinality at {self._peek().pos}",
                                  code="schema.empty-cardinality",
                                  path=str(self._peek().pos))
            lo = hi = first
        self._expect("punct", "]")
        return lo, hi

    def _cardinality_int(self) -> int:
        t = self._next()
        if "." in t.text:
            raise SchemaError(f"cardinality must be a whole number, got {t.text!r} "
                              f"at {t.pos}",
                              code="schema.non-integer-cardinality", path=str(t.pos))
        return int(t.text)

    def _type(self) -> Scalar | Ref | AnyType:
        t = self._next()
        if t.kind != "name":
            # A quoted string in type position gets its own code (Sec5.2's
            # quoting rule, the mirror image of schema.unquoted-label) --
            # any other wrong token kind is a plain unexpected-token.
            code = "schema.quoted-type" if t.kind == "string" else "parse.unexpected-token"
            raise SchemaError(
                f"expected a scalar name or a reference at {t.pos}, got {t.text!r} "
                "(enums and literal-valued fields are not supported -- a "
                "field's type is always one scalar or a reference to a "
                "named record)",
                code=code, path=str(t.pos))
        if t.text == "any":
            if self._peek().text == "?":
                q = self._next()
                raise SchemaError(
                    "'any' already includes null; 'any?' is redundant at "
                    f"{q.pos}",
                    code="schema.nullable-any", path=str(q.pos))
            return ANY
        nullable = False
        if self._peek().text == "?":
            self._next()
            nullable = True
        if t.text in SCALAR_NAMES:
            return Scalar(t.text, nullable)
        if nullable:
            raise SchemaError(
                f"'?' cannot apply to the reference {t.text!r}; use "
                "cardinality [0,1] for an optional field",
                code="schema.nullable-ref", path=t.text)
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


def _type(t: Scalar | Ref | AnyType) -> str:
    if isinstance(t, AnyType):
        return "any"
    if isinstance(t, Ref):
        return t.name
    return f"{t.name}{'?' if t.nullable else ''}"
