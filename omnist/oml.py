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

Performance note (issue #168): the reader is a single-pass scanner/parser
built around one compiled "master" regex with named groups. There is no
``Token`` class and no materialized token list — the parser drives a
``master.match(s, pos)`` loop directly off ``Match`` objects and dispatches
on ``m.lastgroup``. Per-token line/col is *not* computed during scanning;
it's derived lazily, only when a ``ParseError`` is actually raised, by
counting newlines in ``s[:pos]``. Scalar values (``int()``/``float()``/date
parsing) are likewise computed only when a token is consumed by the parser,
not when it's scanned. This is what makes the single-pass design pay off:
per-token Python-level object construction was the dominant cost, not regex
matching itself (see the PR for the profile that motivated this).
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from typing import TYPE_CHECKING, Any, List, Optional, Pattern, Tuple

from .document import _MAX_DEPTH, _MAX_INT_DIGITS, _MAX_NODES
from .errors import ParseError, WriteError
from .schema import _DATE_RE, _DATETIME_RE, _TIME_RE

if TYPE_CHECKING:
    from .report import WriteReport


# ---------------------------------------------------------------------------
# Token kind names (used as the master regex's named groups and as the
# `.lastgroup` values the parser dispatches on -- there is no Token class;
# a "token" here is just (kind: str, match: Match[str]) handled inline).
# ---------------------------------------------------------------------------

SEPWS = "SEPWS"        # hspace / comment / newline / ';' run (may or may not
                        # contain a separator-worthy newline/';' -- checked
                        # in Python after the match, see _is_sep)
DQFAST = "DQFAST"       # no-escape, single-line, control-char-free string
DQUOTE3 = "DQUOTE3"     # opening of a """ multiline string (slow path)
DQUOTE = "DQUOTE"       # opening of a plain string that needs the escape
                        # decoder (contains \ and/or control chars) or is
                        # simply not a DQFAST match for some other reason
RAW = "RAW"             # 'raw string' (E2) -- fully regex-expressible since
                        # a raw string can never contain its own delimiter
SQUOTE = "SQUOTE"       # a lone "'" that couldn't extend to RAW (i.e. no
                        # closing "'" before EOF) -- unterminated raw string
LBRACE = "LBRACE"
RBRACE = "RBRACE"
LBRACKET = "LBRACKET"
RBRACKET = "RBRACKET"
COMMA = "COMMA"
COLON = "COLON"
DATETIME = "DATETIME"
DATE = "DATE"
TIME = "TIME"
NUMDEC = "NUMDEC"       # decimal-num (and decimal-num + exponent)
NUMEXP = "NUMEXP"       # exponent-num (integer mantissa + exponent)
NEGINF = "NEGINF"
NANLIT = "NANLIT"
POSINF = "POSINF"
INTEGER = "INTEGER"
IDENT = "IDENT"

_RESERVED = {"null", "true", "false"}
_RESERVED_NUMBER = {"nan", "inf", "-inf"}

# _DATE_RE / _TIME_RE / _DATETIME_RE: the one shared definition of the
# documented temporal spellings lives in schema.py (imported above) -- see
# its comment there for why (validate()/materialize() need to agree with
# this tokenizer's own notion of "looks like a date/time/datetime"). We
# splice their *source patterns* (unanchored, no flags) into the master
# regex below rather than re-deriving them, so the two can never drift.
_DATE_SRC = _DATE_RE.pattern
_TIME_SRC = _TIME_RE.pattern
_DATETIME_SRC = _DATETIME_RE.pattern

# ---------------------------------------------------------------------------
# The master regex.
#
# One compiled alternation covering every token the grammar's lexical
# section (docs/design/oml-grammar.md §1) documents, in the *exact* priority
# order the grammar specifies: STRING-family and punctuation are pinned to
# their own leading character so they never compete with anything else,
# then DATETIME, DATE, TIME, NUMBER (decimal/exponent forms), the three
# reserved float spellings, INTEGER, then IDENT.
#
# Python's `re` alternation is *ordered*, not POSIX-longest-match: the first
# alternative that matches at the current position wins, even if a later
# alternative would consume more text. This is exactly the grammar's
# "maximal munch within a rule, first rule wins between rules" semantics --
# in particular it's what makes DATETIME-before-DATE correctly implement
# the DATE-vs-DATETIME disambiguation (see grammar doc §1.1) with no
# separate lookahead check needed: at `2024-01-01T10:30`, DATETIME matches
# first and wins; at `2024-01-01T99`, DATETIME's pattern fails to match (T99
# isn't TIME-shaped) so the alternation falls through to DATE, which matches
# just the date part, leaving `T99` for the next call to match as IDENT.
#
# SEPWS folds whitespace/comment/newline/';' skipping into the regex engine
# (C-level), covering both "pure hspace/comment, no token" and "a run
# containing a newline/';' collapses into one SEP" in a single alternative;
# the two cases are distinguished cheaply in Python by checking membership
# of '\n' / '\r' / ';' in the matched span (see _is_sep_span).
#
# DQUOTE3 (the """ opener) is tried before DQFAST even though DQFAST is the
# common case, because DQFAST's pattern ("[^"\\control]*") would otherwise
# happily match the *empty* string formed by the first two quotes of a
# """ run (e.g. at `"""body"""`, DQFAST would match just `""` and leave a
# dangling `"body"""`) -- ordering DQUOTE3 first avoids that trap. DQFAST is
# a fast path for the common remaining case: a double-quoted string with no
# backslash and no control character (the overwhelming majority of
# real-world string content). Only when DQFAST fails to match a leading '"'
# does the scanner fall back to DQUOTE, which needs the char-by-char escape
# decoder (see _scan_string_slow).
# ---------------------------------------------------------------------------

_MASTER_SRC = rf"""
(?P<{SEPWS}>
    (?: [ \t] | \#[^\n]* | \r\n | \n | ; )+
)
|
(?P<{DQUOTE3}> \x22\x22\x22 )
|
(?P<{DQFAST}> \x22 [^\x22\\\x00-\x1f]* \x22 )
|
(?P<{DQUOTE}> \x22 )
|
(?P<{RAW}> ' [^']* ' )
|
(?P<{SQUOTE}> ' )
|
(?P<{LBRACE}> \{{ )
|
(?P<{RBRACE}> \}} )
|
(?P<{LBRACKET}> \[ )
|
(?P<{RBRACKET}> \] )
|
(?P<{COMMA}> , )
|
(?P<{COLON}> : )
|
(?P<{DATETIME}> {_DATETIME_SRC} )
|
(?P<{DATE}> {_DATE_SRC} )
|
(?P<{TIME}> {_TIME_SRC} )
|
(?P<{NUMDEC}> -?\d+\.\d+(?:[eE][+\-]?\d+)? )
|
(?P<{NUMEXP}> -?\d+[eE][+\-]?\d+ )
|
(?P<{NEGINF}> -inf(?![A-Za-z0-9\-]) )
|
(?P<{NANLIT}> nan(?![A-Za-z0-9\-]) )
|
(?P<{POSINF}> inf(?![A-Za-z0-9\-]) )
|
(?P<{INTEGER}> -?\d+ )
|
(?P<{IDENT}> [A-Za-z_][A-Za-z0-9_\-]* )
"""

_MASTER: Pattern[str] = _re.compile(_MASTER_SRC, _re.VERBOSE)

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}

_HEX4_RE = _re.compile(r"[0-9A-Fa-f]{4}")


def _is_sep_span(text: str) -> bool:
    """Does a SEPWS match contain at least one newline/';' (-> SEP token),
    or is it pure hspace/comment (-> skipped, no token emitted)?"""
    return "\n" in text or ";" in text or "\r" in text


# ---------------------------------------------------------------------------
# Scanner -- single pass, driven by the parser (no Token class, no list).
# ---------------------------------------------------------------------------

class _Scanner:
    """Wraps the source text and the master-regex matching loop.

    There is no ``tokens()`` that materializes a list: the parser calls
    :meth:`next` to pull one token at a time, receiving ``(kind, Match)``
    (or ``(EOF, None)`` at end of input). Values are *not* computed here --
    ``int()``/``float()``/date parsing happens only when the parser actually
    consumes a scalar token (see ``_Parser.parse_scalar``), and line/col are
    computed only when :meth:`error_at` is actually called to build a
    ``ParseError``.
    """

    __slots__ = ("s", "n", "pos")

    def __init__(self, text: str) -> None:
        if text.startswith("﻿"):
            text = text[1:]
        self.s = text
        self.n = len(text)
        self.pos = 0

    def line_col(self, pos: int) -> Tuple[int, int]:
        """1-based (line, col) for byte offset ``pos``, computed lazily --
        only ever called while building a ParseError message."""
        s = self.s
        line = s.count("\n", 0, pos) + 1
        nl = s.rfind("\n", 0, pos)
        col = pos - nl if nl != -1 else pos + 1
        return line, col

    def error_at(self, pos: int, msg: str, code: str = "parse.unexpected-token") -> ParseError:
        line, col = self.line_col(pos)
        return ParseError(f"line {line}, col {col}: {msg}", code=code, path=f"{line}:{col}")

    def error_eof(self, msg: str, code: str = "parse.unexpected-token") -> ParseError:
        # Quirk preserved from the original scanner: its EOF token was
        # constructed with no pos=/col= args (`Token(Tok.EOF, "")`), so any
        # error naming "got EOF" always reported line 0, col 0 rather than
        # the source's actual end position. Used only where the *current
        # token* being reported in the message is EOF itself -- byte-
        # identical to v0.2.26, verified by differential fuzzing (see PR).
        return ParseError(f"line 0, col 0: {msg}", code=code, path="0:0")

    def next(self) -> Tuple[str, int, int]:
        """Advance past (and return) the next significant token as
        ``(kind, start, end)``. Skips pure hspace/comment runs silently and
        collapses newline/';'-bearing runs into a single SEP. Raw values
        (text slices) are available via ``self.s[start:end]``; scalar
        conversion happens later, on demand, in the parser."""
        s, n = self.s, self.n
        pos = self.pos
        while True:
            if pos >= n:
                self.pos = pos
                return ("EOF", pos, pos)
            m = _MASTER.match(s, pos)
            if m is None:
                raise self.error_at(pos, f"stray character {s[pos]!r}")
            kind = m.lastgroup
            end = m.end()
            if kind == SEPWS:
                if _is_sep_span(m.group()):
                    self.pos = end
                    return ("SEP", pos, end)
                pos = end
                continue
            if kind == DQUOTE3:
                start, end = self._scan_multiline(pos)
                self.pos = end
                return ("STRING", start, end)
            if kind == DQUOTE:
                start, end = self._scan_string_slow(pos)
                self.pos = end
                return ("STRING", start, end)
            if kind == DQFAST or kind == RAW:
                self.pos = end
                return ("STRING", pos, end)
            if kind == SQUOTE:
                raise self.error_at(pos, "unterminated raw string (missing closing ')",
                                    code="parse.unterminated-string")
            self.pos = end
            assert kind is not None
            return (kind, pos, end)

    # -- strings: slow paths -------------------------------------------
    #
    # These mirror the original char-by-char scanner exactly (semantics
    # unchanged); they're reached only when the DQFAST fast path can't
    # match at a '"' position (a backslash escape, a control character, or
    # a """ multiline opener is present).

    def _scan_string_slow(self, start: int) -> Tuple[int, int]:
        # NOTE on error positions: every ParseError raised while scanning a
        # token reports the *token's start* position (`start`), matching the
        # original scanner exactly -- it only ever advanced its line/col
        # bookkeeping between tokens, never mid-token, so a mid-string error
        # (bad escape, control char, unterminated) always pointed at the
        # opening quote, not the offending character. Preserved verbatim
        # here since tests assert exact messages/positions.
        s, n = self.s, self.n
        i = start + 1
        while True:
            if i >= n:
                raise self.error_at(start, "unterminated string (missing closing \")",
                                    code="parse.unterminated-string")
            ch = s[i]
            if ch == '"':
                return start, i + 1
            if ch == "\\":
                i = self._skip_escape(start, i)
                continue
            if ord(ch) < 0x20:
                raise self.error_at(start, f"control character U+{ord(ch):04X} in string",
                                    code="parse.control-character")
            i += 1

    def _scan_multiline(self, start: int) -> Tuple[int, int]:
        s, n = self.s, self.n
        i = start + 3
        if s[i:i + 1] == "\n":
            i += 1
        elif s[i:i + 2] == "\r\n":
            i += 2
        while True:
            if i >= n:
                raise self.error_at(
                    start, 'unterminated multiline string (missing closing """)',
                    code="parse.unterminated-string")
            ch = s[i]
            if ch == '"':
                run = 0
                j = i
                while j < n and s[j] == '"':
                    run += 1
                    j += 1
                if run >= 3:
                    return start, i + 3
                i = j
                continue
            if ch == "\\":
                i = self._skip_escape(start, i)
                continue
            if ch == "\t" or ch == "\n" or ord(ch) >= 0x20:
                i += 1
                continue
            raise self.error_at(start, f"control character U+{ord(ch):04X} in multiline string",
                                code="parse.control-character")

    def _skip_escape(self, tok_start: int, i: int) -> int:
        """Validate (but don't decode) one escape sequence starting at the
        backslash `s[i]`; return the position just past it. Decoding happens
        later in ``_decode_dquote``/``_decode_multiline`` when the token is
        actually consumed by the parser. Errors report `tok_start` (the
        enclosing string token's opening quote), not `i` -- see the note in
        ``_scan_string_slow``."""
        s, n = self.s, self.n
        if i + 1 >= n:
            raise self.error_at(tok_start, "unterminated escape sequence",
                                code="parse.unterminated-string")
        c = s[i + 1]
        if c in _ESCAPES:
            return i + 2
        if c == "u":
            hexs = s[i + 2:i + 6]
            if len(hexs) != 4 or not _HEX4_RE.fullmatch(hexs):
                raise self.error_at(tok_start, r"invalid \u escape (need 4 hex digits)",
                                    code="parse.invalid-escape")
            cp = int(hexs, 16)
            j = i + 6
            if 0xD800 <= cp <= 0xDBFF:
                hex2 = s[j + 2:j + 6]
                if s[j:j + 2] == "\\u" and _HEX4_RE.fullmatch(hex2):
                    low = int(hex2, 16)
                    if 0xDC00 <= low <= 0xDFFF:
                        return j + 6
                raise self.error_at(
                    tok_start, f"unpaired high surrogate \\u{hexs} (needs a following "
                    r"low-surrogate \uDC00-\uDFFF escape)", code="parse.unpaired-surrogate")
            if 0xDC00 <= cp <= 0xDFFF:
                raise self.error_at(tok_start, f"unpaired low surrogate \\u{hexs}",
                                    code="parse.unpaired-surrogate")
            return j
        raise self.error_at(tok_start, rf"invalid escape \{c}", code="parse.invalid-escape")


# ---------------------------------------------------------------------------
# Value decoding -- deferred until the parser actually consumes a token.
# ---------------------------------------------------------------------------

def _decode_dquote(text: str) -> str:
    """Decode a dquote-string token's *raw source text* (including the
    surrounding quotes) into its value. Used for both the DQUOTE (slow-scan)
    and DQFAST tokens -- DQFAST's text is guaranteed escape-free, but running
    it through the same decoder keeps this one code path (the escape-free
    case just never enters the backslash branch)."""
    if "\\" not in text:
        return text[1:-1]
    out = []
    i = 1
    n = len(text) - 1  # stop before the closing quote
    while i < n:
        ch = text[i]
        if ch == "\\":
            esc, i = _decode_escape(text, i)
            out.append(esc)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _decode_multiline(text: str) -> str:
    # text is `"""` + body + `"""`; strip the 3+3 delimiters, then an
    # immediately-following single \n or \r\n (opening-newline elision).
    body = text[3:-3]
    if body[:1] == "\n":
        body = body[1:]
    elif body[:2] == "\r\n":
        body = body[2:]
    if "\\" not in body:
        return body
    out = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "\\":
            esc, i = _decode_escape(body, i)
            out.append(esc)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _decode_escape(s: str, i: int) -> Tuple[str, int]:
    """Decode one escape sequence at ``s[i] == '\\\\'``. Validation already
    happened during scanning (``_Scanner._skip_escape``); this just repeats
    the (cheap) parse to produce the value, so the scanner never needs to
    allocate output on the hot path."""
    c = s[i + 1]
    if c in _ESCAPES:
        return _ESCAPES[c], i + 2
    # c == "u" (only remaining valid case, already validated)
    hexs = s[i + 2:i + 6]
    cp = int(hexs, 16)
    j = i + 6
    if 0xD800 <= cp <= 0xDBFF:
        low = int(s[j + 2:j + 6], 16)
        combined = 0x10000 + (cp - 0xD800) * 0x400 + (low - 0xDC00)
        return chr(combined), j + 6
    return chr(cp), j


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive-descent parser driven directly off the scanner's
    ``(kind, start, end)`` triples -- no Token objects, no token list."""

    def __init__(self, scanner: _Scanner) -> None:
        self.sc = scanner
        self.kind, self.start, self.end = scanner.next()
        # #313: build_node() (document.py) enforces this same cap for the
        # other readers, but OML's own recursive-descent parser builds its
        # edge lists directly, bypassing build_node entirely -- nothing
        # else enforced a node-count ceiling on OML text at all. One
        # counter for the whole parse, incremented once per container node
        # (parse_node_edges call), matching build_node's post-#309
        # container-only semantics exactly.
        self.node_count = 0

    def _advance(self) -> Tuple[str, int, int]:
        cur = (self.kind, self.start, self.end)
        self.kind, self.start, self.end = self.sc.next()
        return cur

    def skip_sep(self) -> None:
        while self.kind == "SEP":
            self._advance()

    def _error_for(self, kind: str, pos: int, msg: str) -> ParseError:
        """Build a ParseError positioned at `pos`, *unless* the token being
        reported is EOF, in which case it uses the line-0/col-0 quirk (see
        ``_Scanner.error_eof``) -- centralizes the "is this token EOF"
        branch so every call site doesn't have to repeat it."""
        if kind == "EOF":
            return self.sc.error_eof(msg)
        return self.sc.error_at(pos, msg)

    def parse_document(self) -> Any:
        self.skip_sep()
        if self.kind == "EOF":
            return []
        if self.kind == LBRACE:
            node = self.parse_value(depth=0)
        elif self._looks_like_edge():
            node = self.parse_node_edges(depth=0)
        else:
            node = self.parse_scalar()
        self.skip_sep()
        if self.kind != "EOF":
            text = self._tok_text(self.kind, self.start, self.end)
            raise self.sc.error_at(
                self.start,
                f"unexpected trailing content after the document body "
                f"(token {self.kind} {text!r})")
        return node

    def _looks_like_edge(self) -> bool:
        kind = self.kind
        if kind == "STRING":
            return self._peek_kind_after_current() == COLON
        if kind == IDENT:
            text = self.sc.s[self.start:self.end]
            if text in _RESERVED:
                return False
            return self._peek_kind_after_current() == COLON
        return False

    def _peek_kind_after_current(self) -> str:
        """One token of lookahead *past* the current token, without
        consuming the current token or materializing a list: save scanner
        position, pull the next token, restore. Only called at the very
        start of a document/value (§2.1 of the grammar), so this is O(1)
        amortized, not O(n) re-scanning."""
        saved_pos = self.sc.pos
        kind, _start, _end = self.sc.next()
        self.sc.pos = saved_pos
        return kind

    def parse_node_edges(self, depth: int) -> List[Tuple[str, Any]]:
        self.node_count += 1
        if self.node_count > _MAX_NODES:
            raise ParseError(
                f"too many nodes materialized (over {_MAX_NODES}) -- "
                "likely a runaway or maliciously large document")
        edges: List[Tuple[str, Any]] = []
        self.skip_sep()
        while self.kind not in (RBRACE, "EOF"):
            label = self.parse_label()
            colon_kind, colon_start, colon_end = self._advance()
            if colon_kind != COLON:
                text = self._tok_text(colon_kind, colon_start, colon_end)
                raise self._error_for(
                    colon_kind, colon_start,
                    f"expected ':' after label {label!r}, got {colon_kind} {text!r}")
            if self.kind == LBRACKET:
                for element in self.parse_array(depth):
                    edges.append((label, element))
            else:
                value = self.parse_value(depth)
                edges.append((label, value))
            if self.kind in (RBRACE, "EOF"):
                break
            if self.kind != "SEP":
                text = self._tok_text(self.kind, self.start, self.end)
                raise self.sc.error_at(
                    self.start,
                    f"expected a separator (newline or ';') or '}}' after "
                    f"the value for {label!r}, got {self.kind} {text!r}")
            self.skip_sep()
        return edges

    def _tok_text(self, kind: str, start: int, end: int) -> str:
        """A token's display text for error messages. For every kind except
        STRING this is a plain source slice (EOF's start == end == n, so
        that naturally yields ""). STRING is special, and inconsistent in a
        way preserved verbatim from the original scanner: its ``Token.text``
        held the *decoded value, no delimiters* for a raw string (E2), but
        the *raw source slice, delimiters included* for a dquote/multiline
        string -- e.g. an unterminated raw string's error names the value
        ``'s broken'``, but a dangling empty dquote-string leftover names
        the source ``'""'`` (2 literal quote chars), not the decoded value
        ``''``. Reproduced exactly (not "fixed") since tests assert exact
        messages and the differential fuzz against v0.2.26 must be silent."""
        if kind == "STRING" and self.sc.s[start:start + 1] == "'":
            return self._string_value(start, end)
        return self.sc.s[start:end]

    def parse_label(self) -> str:
        kind, start, end = self._advance()
        if kind == "STRING":
            return self._string_value(start, end)
        if kind == IDENT:
            text = self.sc.s[start:end]
            if text in _RESERVED:
                raise self.sc.error_at(
                    start,
                    f"{text!r} is a reserved word and cannot be a bare "
                    f'label; quote it: "{text}"')
            return text
        text = self._tok_text(kind, start, end)
        raise self._error_for(kind, start, f"expected a label, got {kind} {text!r}")

    def parse_value(self, depth: int) -> Any:
        if self.kind == LBRACE:
            if depth + 1 > _MAX_DEPTH:
                # No "line X, col Y:" prefix here, matching the original
                # scanner exactly: it raises a bare ParseError for this one
                # message rather than going through its usual self.error()
                # position-prefixing helper.
                raise ParseError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")
            self._advance()
            self.skip_sep()
            edges = self.parse_node_edges(depth + 1)
            self.skip_sep()
            close_kind, close_start, close_end = self._advance()
            if close_kind != RBRACE:
                text = self._tok_text(close_kind, close_start, close_end)
                raise self._error_for(
                    close_kind, close_start, f"expected '}}', got {close_kind} {text!r}")
            return edges
        return self.parse_scalar()

    def parse_array(self, depth: int) -> List[Any]:
        """Parse ``'[' element (',' element)* [','] ']'`` (issue #218) and
        return the list of element values -- the caller (parse_node_edges)
        splices these into the edge list as repeated same-label edges.
        Arrays are pure edge-multiplication sugar, not a value in the
        Document model, so this never returns anything the model itself
        would represent as an array node."""
        open_start = self.start
        self._advance()  # consume '['
        self.skip_sep()
        if self.kind == RBRACKET:
            raise self.sc.error_at(open_start, "empty array is not allowed")
        elements: List[Any] = []
        while True:
            if self.kind == LBRACKET:
                raise self.sc.error_at(
                    self.start, "nested array is not allowed (arrays may only "
                    "contain scalars, null, or brace subtrees)")
            elements.append(self.parse_value(depth))
            self.skip_sep()
            if self.kind == COMMA:
                self._advance()
                self.skip_sep()
                if self.kind == RBRACKET:
                    break  # trailing comma
                continue
            break
        close_kind, close_start, close_end = self._advance()
        if close_kind != RBRACKET:
            text = self._tok_text(close_kind, close_start, close_end)
            raise self._error_for(
                close_kind, close_start,
                f"expected ',' or ']' in array, got {close_kind} {text!r}")
        return elements

    def parse_scalar(self) -> Any:
        kind, start, end = self._advance()
        if kind == "STRING":
            return self._string_value(start, end)
        if kind == INTEGER:
            text = self.sc.s[start:end]
            digits = text[1:] if text[0] == "-" else text
            if len(digits) > _MAX_INT_DIGITS:
                raise self.sc.error_at(
                    start,
                    f"integer literal has {len(digits)} digits, exceeding "
                    f"the {_MAX_INT_DIGITS}-digit limit (security: "
                    "unbounded-digit int-to-str conversion is superlinear)")
            return int(text)
        if kind == NUMDEC or kind == NUMEXP:
            return float(self.sc.s[start:end])
        if kind == NANLIT:
            return float("nan")
        if kind == POSINF:
            return float("inf")
        if kind == NEGINF:
            return float("-inf")
        if kind == DATE:
            text = self.sc.s[start:end]
            try:
                return _dt.date.fromisoformat(text)
            except ValueError as exc:
                # Position quirk preserved from the original scanner: it
                # advanced its line/col past the token *before* attempting
                # fromisoformat(), so an invalid-date error reports the
                # position right after the token, not its start.
                raise self.sc.error_at(end, f"invalid date {text!r}: {exc}") from exc
        if kind == TIME:
            text = self.sc.s[start:end]
            try:
                return _dt.time.fromisoformat(text)
            except ValueError as exc:
                raise self.sc.error_at(end, f"invalid time {text!r}: {exc}") from exc
        if kind == DATETIME:
            text = self.sc.s[start:end]
            try:
                return _dt.datetime.fromisoformat(text)
            except ValueError as exc:
                raise self.sc.error_at(end, f"invalid datetime {text!r}: {exc}") from exc
        if kind == IDENT:
            text = self.sc.s[start:end]
            if text == "null":
                return None
            if text == "true":
                return True
            if text == "false":
                return False
            raise self.sc.error_at(
                start,
                f"bare word {text!r} is not a valid value here; strings "
                "must be quoted")
        text = self._tok_text(kind, start, end)
        raise self._error_for(kind, start, f"expected a value, got {kind} {text!r}")

    def _string_value(self, start: int, end: int) -> str:
        text = self.sc.s[start:end]
        if text[0] == "'":
            return text[1:-1]
        if text[:3] == '"""':
            return _decode_multiline(text)
        return _decode_dquote(text)


# ---------------------------------------------------------------------------
# Public read/write
# ---------------------------------------------------------------------------

def read_oml(text: str, *, schema: Optional[Any] = None) -> Any:
    """Parse OML source into a canonical Document node (edge-list or leaf)."""
    scanner = _Scanner(text)
    node = _Parser(scanner).parse_document()
    if schema is None:
        return node
    from .deserialize import materialize
    return materialize(node, schema)


def write_oml(node: Any, *, indent: Optional[int] = 2, arrays: bool = False) -> str:
    """Render a canonical Document node as OML source.

    OML is lossless for every Document: there is never an adjustment to
    report (unlike JSON/YAML/TOML/XML), so there is no ``check_oml``/
    ``strict=``/``report=`` machinery — the write always succeeds exactly.

    ``indent=None`` renders a single-line, machine-oriented form (edges
    joined by ``"; "``, no newlines/padding) instead of the default
    pretty-printed, indented form -- mirroring ``write_json``'s own
    ``indent=None`` convention. Both forms round-trip through ``read_oml``.

    ``arrays=True`` (issue #218) collapses any maximal run of >= 2
    consecutive same-label edges into ``label: [v1, v2, ...]`` array
    syntax -- a run of length 1 still writes as a plain scalar edge, and a
    run is never merged across an edge with a different label in between,
    so this never reorders anything: ``read_oml(write_oml(node,
    arrays=True)) == node`` holds unconditionally. Default ``False``
    produces output byte-identical to ``arrays`` not existing at all.
    """
    if not isinstance(node, list):
        return _write_scalar(node)
    if indent is None:
        return _write_edges_compact(node, arrays, 0)
    return _write_edges(node, 0, indent, arrays, 0)


def _group_runs(
    edges: List[Tuple[str, Any]],
) -> List[Tuple[str, List[Any]]]:
    """Group ``edges`` into maximal runs of consecutive same-label edges,
    preserving order -- ``[('b',1),('b',2),('c',True),('b',3)]`` ->
    ``[('b',[1,2]), ('c',[True]), ('b',[3])]``. Never reorders; a run only
    ever contains edges that were already adjacent in the input."""
    runs: List[Tuple[str, List[Any]]] = []
    for label, child in edges:
        if runs and runs[-1][0] == label:
            runs[-1][1].append(child)
        else:
            runs.append((label, [child]))
    return runs


def check_oml(node: Any) -> "WriteReport":
    """OML can hold every Document losslessly; always an empty report."""
    from .report import WriteReport
    return WriteReport()


def _write_edges(
    edges: List[Tuple[str, Any]], depth: int, indent: int, arrays: bool = False,
    node_depth: int = 0,
) -> str:
    if node_depth > _MAX_DEPTH:
        raise WriteError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")
    pad = " " * (indent * depth)
    lines = []
    for label, children in (_group_runs(edges) if arrays else [(lbl, [c]) for lbl, c in edges]):
        lab = _write_label(label)
        if arrays and len(children) > 1:
            items = ", ".join(
                _write_array_element(c, depth, indent, arrays, node_depth) for c in children)
            lines.append(f"{pad}{lab}: [{items}]")
            continue
        child = children[0]
        if isinstance(child, list):
            if not child:
                lines.append(f"{pad}{lab}: {{}}")
            else:
                inner = _write_edges(child, depth + 1, indent, arrays, node_depth + 1)
                lines.append(f"{pad}{lab}: {{\n{inner}\n{pad}}}")
        else:
            lines.append(f"{pad}{lab}: {_write_scalar(child)}")
    return "\n".join(lines)


def _write_array_element(
    child: Any, depth: int, indent: int, arrays: bool, node_depth: int = 0,
) -> str:
    """One element inside a pretty-mode ``[...]`` -- brace subtrees render
    single-line (``{ ... }``) regardless of the surrounding indent mode,
    matching the "arrays never wrap" decision (issue #218, 1A)."""
    if isinstance(child, list):
        if not child:
            return "{}"
        inner = _write_edges_compact(child, arrays, node_depth + 1)
        return f"{{ {inner} }}"
    return _write_scalar(child)


def _write_edges_compact(
    edges: List[Tuple[str, Any]], arrays: bool = False, node_depth: int = 0,
) -> str:
    if node_depth > _MAX_DEPTH:
        raise WriteError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")
    parts = []
    for label, children in (_group_runs(edges) if arrays else [(lbl, [c]) for lbl, c in edges]):
        lab = _write_label(label)
        if arrays and len(children) > 1:
            items = ", ".join(
                _write_array_element(c, 0, 0, arrays, node_depth) for c in children)
            parts.append(f"{lab}: [{items}]")
            continue
        child = children[0]
        if isinstance(child, list):
            if not child:
                parts.append(f"{lab}: {{}}")
            else:
                inner = _write_edges_compact(child, arrays, node_depth + 1)
                parts.append(f"{lab}: {{ {inner} }}")
        else:
            parts.append(f"{lab}: {_write_scalar(child)}")
    return "; ".join(parts)


# \Z, not $: $ also matches just before a trailing "\n", which would let a
# label like "A\n" be written bare and break the read/write round-trip.
_BARE_LABEL_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*\Z")


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
