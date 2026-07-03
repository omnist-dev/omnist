"""OML (Omnist Markup Language) — the native codec for the Document model.

OML is omnist's own serialization format: every Document — every ordered,
possibly-repeated, possibly-interleaved edge list, and all seven scalar kinds
(``string``, ``integer``, ``number``, ``boolean``, ``date``, ``time``,
``datetime``) plus ``null`` — round-trips through OML exactly, with no
adjustment ever needed (unlike JSON/YAML/TOML/XML, OML never has a
:class:`~omnist.report.WriteReport` entry to report).

This module implements the **OML-Core** grammar in full, plus the
**OML-Extended** raw-string and triple-quoted multiline-string spellings
(E2/E3) on read. The canonical writer only ever emits OML-Core.

See ``docs/formats/oml.md`` for the user-facing guide and
``docs/design/OML-spec.md`` (design-time artifact, not shipped) for the full
normative grammar this implementation follows.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Match, Optional, Tuple

from .document import _MAX_INT_DIGITS
from .errors import ParseError
from .schema import _DATE_RE, _DATETIME_RE, _TIME_RE

if TYPE_CHECKING:
    from .report import WriteReport

_MAX_DEPTH = 200          # matches Document's own nesting bound (document.py)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

class Tok:
    SEP = "SEP"
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    DATE = "DATE"
    TIME = "TIME"
    DATETIME = "DATETIME"
    IDENT = "IDENT"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    COLON = "COLON"
    EOF = "EOF"


@dataclass
class Token:
    kind: str
    text: str          # raw source text (for STRING-family: the unescaped value)
    value: Any = None  # evaluated value (for scalars)
    pos: int = 0        # 1-based line, for error messages
    col: int = 0


_RESERVED = {"null", "true", "false"}
_RESERVED_NUMBER = {"nan", "inf", "-inf"}

_IDENT_RE = _re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
# _DATE_RE / _TIME_RE / _DATETIME_RE: the one shared definition of the
# documented temporal spellings now lives in schema.py (imported above) --
# see its comment there for why (validate()/materialize() need to agree with
# this tokenizer's own notion of "looks like a date/time/datetime").
_NUMDEC_RE = _re.compile(r"-?\d+\.\d+([eE][+\-]?\d+)?")
_NUMEXP_RE = _re.compile(r"-?\d+[eE][+\-]?\d+")
_INTEGER_RE = _re.compile(r"-?\d+")

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}


class _Scanner:
    """Tokenizes OML source by maximal munch with the spec's priority order:
    STRING-family, DATETIME, DATE, TIME, NUMBER, INTEGER, IDENT, punctuation."""

    def __init__(self, text: str) -> None:
        if text.startswith("﻿"):
            text = text[1:]
        self.s = text
        self.n = len(text)
        self.i = 0
        self.line = 1
        self.col = 1

    def error(self, msg: str) -> ParseError:
        return ParseError(f"line {self.line}, col {self.col}: {msg}")

    def _advance(self, k: int) -> None:
        for ch in self.s[self.i:self.i + k]:
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
        self.i += k

    def tokens(self) -> List[Token]:
        out: List[Token] = []
        while True:
            tok = self._next()
            out.append(tok)
            if tok.kind == Tok.EOF:
                return out

    def _next(self) -> Token:
        # 1. skip hspace / comments; collapse a run of newlines/`;` (with
        #    folded ws/comments) into one SEP token.
        sep_seen = False
        while self.i < self.n:
            ch = self.s[self.i]
            if ch in " \t":
                self._advance(1)
            elif ch == "#":
                end = self.s.find("\n", self.i)
                end = self.n if end == -1 else end
                self._advance(end - self.i)
            elif ch == "\r" and self.s[self.i + 1:self.i + 2] == "\n":
                self._advance(2)
                sep_seen = True
            elif ch == "\n" or ch == ";":
                self._advance(1)
                sep_seen = True
            else:
                break
        if sep_seen:
            return Token(Tok.SEP, ";")
        if self.i >= self.n:
            return Token(Tok.EOF, "")

        line, col = self.line, self.col
        ch = self.s[self.i]

        if ch == '"':
            return self._scan_dquote(line, col)
        if ch == "'":
            return self._scan_raw(line, col)
        if ch == "{":
            self._advance(1)
            return Token(Tok.LBRACE, "{", pos=line, col=col)
        if ch == "}":
            self._advance(1)
            return Token(Tok.RBRACE, "}", pos=line, col=col)
        if ch == ":":
            self._advance(1)
            return Token(Tok.COLON, ":", pos=line, col=col)

        m = _DATETIME_RE.match(self.s, self.i)
        if m:
            return self._emit_datetime(m, line, col)
        m = _DATE_RE.match(self.s, self.i)
        if m and not (m.end() < self.n and self.s[m.end()] == "T"
                      and _TIME_RE.match(self.s, m.end() + 1)):
            return self._emit_date(m, line, col)
        m = _TIME_RE.match(self.s, self.i)
        if m:
            return self._emit_time(m, line, col)
        m = _NUMDEC_RE.match(self.s, self.i) or _NUMEXP_RE.match(self.s, self.i)
        if m:
            return self._emit_number(m, line, col)
        if self.s.startswith("-inf", self.i) and not self._alnum_at(self.i + 4):
            self._advance(4)
            return Token(Tok.NUMBER, "-inf", value=float("-inf"), pos=line, col=col)
        if (self.s.startswith("nan", self.i) and not self._alnum_at(self.i + 3)
                and self.s[self.i + 3:self.i + 4] != "-"):
            self._advance(3)
            return Token(Tok.NUMBER, "nan", value=float("nan"), pos=line, col=col)
        if (self.s.startswith("inf", self.i) and not self._alnum_at(self.i + 3)
                and self.s[self.i + 3:self.i + 4] != "-"):
            self._advance(3)
            return Token(Tok.NUMBER, "inf", value=float("inf"), pos=line, col=col)
        m = _INTEGER_RE.match(self.s, self.i)
        if m:
            return self._emit_integer(m, line, col)
        m = _IDENT_RE.match(self.s, self.i)
        if m:
            self._advance(m.end() - self.i)
            return Token(Tok.IDENT, m.group(), pos=line, col=col)

        raise self.error(f"stray character {ch!r}")

    def _alnum_at(self, i: int) -> bool:
        ch = self.s[i:i + 1]
        return bool(ch) and ch.isalnum()

    # -- numeric / temporal emission ----------------------------------
    def _emit_integer(self, m: Match[str], line: int, col: int) -> Token:
        text = m.group()
        digits = text.lstrip("-")
        if len(digits) > _MAX_INT_DIGITS:
            raise self.error(
                f"integer literal has {len(digits)} digits, exceeding the "
                f"{_MAX_INT_DIGITS}-digit limit (security: unbounded-digit "
                "int-to-str conversion is superlinear)")
        self._advance(m.end() - m.start())
        return Token(Tok.INTEGER, text, value=int(text), pos=line, col=col)

    def _emit_number(self, m: Match[str], line: int, col: int) -> Token:
        text = m.group()
        self._advance(m.end() - m.start())
        return Token(Tok.NUMBER, text, value=float(text), pos=line, col=col)

    def _emit_date(self, m: Match[str], line: int, col: int) -> Token:
        text = m.group()
        self._advance(m.end() - m.start())
        try:
            value = _dt.date.fromisoformat(text)
        except ValueError as exc:
            raise self.error(f"invalid date {text!r}: {exc}") from exc
        return Token(Tok.DATE, text, value=value, pos=line, col=col)

    def _emit_time(self, m: Match[str], line: int, col: int) -> Token:
        text = m.group()
        self._advance(m.end() - m.start())
        try:
            value = _dt.time.fromisoformat(text)
        except ValueError as exc:
            raise self.error(f"invalid time {text!r}: {exc}") from exc
        return Token(Tok.TIME, text, value=value, pos=line, col=col)

    def _emit_datetime(self, m: Match[str], line: int, col: int) -> Token:
        text = m.group()
        self._advance(m.end() - m.start())
        try:
            value = _dt.datetime.fromisoformat(text)
        except ValueError as exc:
            raise self.error(f"invalid datetime {text!r}: {exc}") from exc
        return Token(Tok.DATETIME, text, value=value, pos=line, col=col)

    # -- strings ---------------------------------------------------------
    def _scan_raw(self, line: int, col: int) -> Token:
        end = self.s.find("'", self.i + 1)
        if end == -1:
            raise self.error("unterminated raw string (missing closing ')")
        text = self.s[self.i + 1:end]
        self._advance(end + 1 - self.i)
        return Token(Tok.STRING, text, value=text, pos=line, col=col)

    def _scan_dquote(self, line: int, col: int) -> Token:
        if self.s[self.i:self.i + 3] == '"""':
            return self._scan_multiline(line, col)
        return self._scan_string(line, col)

    def _scan_string(self, line: int, col: int) -> Token:
        start = self.i
        i = self.i + 1
        out = []
        while True:
            if i >= self.n:
                raise self.error("unterminated string (missing closing \")")
            ch = self.s[i]
            if ch == '"':
                i += 1
                break
            if ch == "\\":
                esc, i = self._read_escape(i)
                out.append(esc)
                continue
            if ord(ch) < 0x20:
                raise self.error(f"control character U+{ord(ch):04X} in string")
            out.append(ch)
            i += 1
        self._advance(i - start)
        return Token(Tok.STRING, self.s[start:i], value="".join(out), pos=line, col=col)

    def _scan_multiline(self, line: int, col: int) -> Token:
        start = self.i
        i = self.i + 3
        if self.s[i:i + 1] == "\n":
            i += 1
        elif self.s[i:i + 2] == "\r\n":
            i += 2
        out = []
        while True:
            if i >= self.n:
                raise self.error('unterminated multiline string (missing closing """)')
            if self.s[i] == '"':
                run = 0
                j = i
                while j < self.n and self.s[j] == '"':
                    run += 1
                    j += 1
                if run >= 3:
                    # the terminator is the *first* three of this run (§5.2
                    # rule 2a); any further quotes are outside this token and
                    # left for the main tokenizer to scan next (D.4).
                    i = i + 3
                    break
                out.append('"' * run)
                i = j
                continue
            ch = self.s[i]
            if ch == "\\":
                esc, i = self._read_escape(i)
                out.append(esc)
                continue
            if ch == "\t" or ch == "\n" or ord(ch) >= 0x20:
                out.append(ch)
                i += 1
                continue
            raise self.error(f"control character U+{ord(ch):04X} in multiline string")
        self._advance(i - start)
        return Token(Tok.STRING, self.s[start:i], value="".join(out), pos=line, col=col)

    def _read_escape(self, i: int) -> tuple[str, int]:
        if i + 1 >= self.n:
            raise self.error("unterminated escape sequence")
        c = self.s[i + 1]
        if c in _ESCAPES:
            return _ESCAPES[c], i + 2
        if c == "u":
            hexs = self.s[i + 2:i + 6]
            if len(hexs) != 4 or not _re.fullmatch(r"[0-9A-Fa-f]{4}", hexs):
                raise self.error(r"invalid \u escape (need 4 hex digits)")
            cp = int(hexs, 16)
            j = i + 6
            if 0xD800 <= cp <= 0xDBFF:
                hex2 = self.s[j + 2:j + 6]
                if self.s[j:j + 2] == "\\u" and _re.fullmatch(r"[0-9A-Fa-f]{4}", hex2):
                    low = int(hex2, 16)
                    if 0xDC00 <= low <= 0xDFFF:
                        combined = 0x10000 + (cp - 0xD800) * 0x400 + (low - 0xDC00)
                        return chr(combined), j + 6
                raise self.error(
                    f"unpaired high surrogate \\u{hexs} (needs a following "
                    r"low-surrogate \uDC00-\uDFFF escape)")
            if 0xDC00 <= cp <= 0xDFFF:
                raise self.error(f"unpaired low surrogate \\u{hexs}")
            return chr(cp), j
        raise self.error(rf"invalid escape \{c}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, toks: List[Token]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def advance(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def skip_sep(self) -> None:
        while self.peek().kind == Tok.SEP:
            self.advance()

    def parse_document(self) -> Any:
        self.skip_sep()
        if self.peek().kind == Tok.EOF:
            return []
        if self.peek().kind == Tok.LBRACE:
            node = self.parse_value(depth=0)
        else:
            save = self.i
            if self._looks_like_edge():
                self.i = save
                node = self.parse_node_edges(depth=0)
            else:
                self.i = save
                node = self.parse_scalar()
        self.skip_sep()
        if self.peek().kind != Tok.EOF:
            t = self.peek()
            raise ParseError(
                f"line {t.pos}, col {t.col}: unexpected trailing content "
                f"after the document body (token {t.kind} {t.text!r})")
        return node

    def _looks_like_edge(self) -> bool:
        t = self.peek()
        if t.kind == Tok.STRING:
            nxt = self.toks[self.i + 1]
            return nxt.kind == Tok.COLON
        if t.kind == Tok.IDENT:
            if t.text in _RESERVED:
                return False
            nxt = self.toks[self.i + 1]
            return nxt.kind == Tok.COLON
        return False

    def parse_node_edges(self, depth: int) -> List[Tuple[str, Any]]:
        edges: List[Tuple[str, Any]] = []
        self.skip_sep()
        while self.peek().kind not in (Tok.RBRACE, Tok.EOF):
            label = self.parse_label()
            colon = self.advance()
            if colon.kind != Tok.COLON:
                raise ParseError(
                    f"line {colon.pos}, col {colon.col}: expected ':' after "
                    f"label {label!r}, got {colon.kind} {colon.text!r}")
            value = self.parse_value(depth)
            edges.append((label, value))
            nxt = self.peek()
            if nxt.kind in (Tok.RBRACE, Tok.EOF):
                break
            if nxt.kind != Tok.SEP:
                raise ParseError(
                    f"line {nxt.pos}, col {nxt.col}: expected a separator "
                    f"(newline or ';') or '}}' after the value for {label!r}, "
                    f"got {nxt.kind} {nxt.text!r}")
            self.skip_sep()
        return edges

    def parse_label(self) -> str:
        t = self.advance()
        if t.kind == Tok.STRING:
            return str(t.value)
        if t.kind == Tok.IDENT:
            if t.text in _RESERVED:
                raise ParseError(
                    f"line {t.pos}, col {t.col}: {t.text!r} is a reserved "
                    f'word and cannot be a bare label; quote it: "{t.text}"')
            return t.text
        raise ParseError(f"line {t.pos}, col {t.col}: expected a label, "
                          f"got {t.kind} {t.text!r}")

    def parse_value(self, depth: int) -> Any:
        t = self.peek()
        if t.kind == Tok.LBRACE:
            if depth + 1 > _MAX_DEPTH:
                raise ParseError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")
            self.advance()
            self.skip_sep()
            edges = self.parse_node_edges(depth + 1)
            self.skip_sep()
            close = self.advance()
            if close.kind != Tok.RBRACE:
                raise ParseError(
                    f"line {close.pos}, col {close.col}: expected '}}', "
                    f"got {close.kind} {close.text!r}")
            return edges
        return self.parse_scalar()

    def parse_scalar(self) -> Any:
        t = self.advance()
        if t.kind == Tok.STRING:
            return t.value
        if t.kind in (Tok.INTEGER, Tok.NUMBER, Tok.DATE, Tok.TIME, Tok.DATETIME):
            return t.value
        if t.kind == Tok.IDENT:
            if t.text == "null":
                return None
            if t.text == "true":
                return True
            if t.text == "false":
                return False
            raise ParseError(
                f"line {t.pos}, col {t.col}: bare word {t.text!r} is not a "
                "valid value here; strings must be quoted")
        raise ParseError(f"line {t.pos}, col {t.col}: expected a value, "
                          f"got {t.kind} {t.text!r}")


# ---------------------------------------------------------------------------
# Public read/write
# ---------------------------------------------------------------------------

def read_oml(text: str, *, schema: Optional[Any] = None) -> Any:
    """Parse OML source into a canonical Document node (edge-list or leaf)."""
    scanner = _Scanner(text)
    toks = scanner.tokens()
    node = _Parser(toks).parse_document()
    if schema is None:
        return node
    from .deserialize import materialize
    return materialize(node, schema)


def write_oml(node: Any, *, indent: Optional[int] = 2) -> str:
    """Render a canonical Document node as OML source.

    OML is lossless for every Document: there is never an adjustment to
    report (unlike JSON/YAML/TOML/XML), so there is no ``check_oml``/
    ``strict=``/``report=`` machinery — the write always succeeds exactly.

    ``indent=None`` renders a single-line, machine-oriented form (edges
    joined by ``"; "``, no newlines/padding) instead of the default
    pretty-printed, indented form -- mirroring ``write_json``'s own
    ``indent=None`` convention. Both forms round-trip through ``read_oml``.
    """
    if not isinstance(node, list):
        return _write_scalar(node)
    if indent is None:
        return _write_edges_compact(node)
    return _write_edges(node, 0, indent)


def check_oml(node: Any) -> "WriteReport":
    """OML can hold every Document losslessly; always an empty report."""
    from .report import WriteReport
    return WriteReport()


def _write_edges(edges: List[Tuple[str, Any]], depth: int, indent: int) -> str:
    pad = " " * (indent * depth)
    lines = []
    for label, child in edges:
        lab = _write_label(label)
        if isinstance(child, list):
            if not child:
                lines.append(f"{pad}{lab}: {{}}")
            else:
                inner = _write_edges(child, depth + 1, indent)
                lines.append(f"{pad}{lab}: {{\n{inner}\n{pad}}}")
        else:
            lines.append(f"{pad}{lab}: {_write_scalar(child)}")
    return "\n".join(lines)


def _write_edges_compact(edges: List[Tuple[str, Any]]) -> str:
    parts = []
    for label, child in edges:
        lab = _write_label(label)
        if isinstance(child, list):
            if not child:
                parts.append(f"{lab}: {{}}")
            else:
                inner = _write_edges_compact(child)
                parts.append(f"{lab}: {{ {inner} }}")
        else:
            parts.append(f"{lab}: {_write_scalar(child)}")
    return "; ".join(parts)


_BARE_LABEL_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


def _write_label(label: str) -> str:
    if (
        _BARE_LABEL_RE.match(label)
        and label not in _RESERVED
        and label not in _RESERVED_NUMBER
    ):
        return label
    return _write_string(label)


def _write_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        import math
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "-inf" if v < 0 else "inf"
        return repr(v)
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.time):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, str):
        return _write_string(v)
    raise TypeError(f"{type(v).__name__} has no OML scalar form")


def _write_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
