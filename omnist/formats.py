"""Codecs over the canonical Document (edge-list) model.

Readers parse a format into a node; writers project a node back.  JSON/YAML/TOML
go through the JSON-shaped grouping (``to_grouped``); XML uses repeated elements
directly, so it preserves interleaving on read and needs a single document
element on write.

Writing is **lenient by default**: when a value can't be held losslessly (TOML
has no ``null``; JSON/XML have no date type), the writer adjusts it and records
the change in a :class:`~omnist.report.WriteReport`.  Pass
``report=`` to inspect, or ``strict=True`` to raise on any adjustment.  See
:mod:`~omnist.report`.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json as _json
import math as _math
import re as _re
from typing import TYPE_CHECKING, Any, Optional
from xml.parsers import expat

from ._encoding import DEFAULT_MAX_INPUT_BYTES, check_encodable, check_input_size, strip_bom
from ._limits import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_INT_DIGITS,
    DEFAULT_MAX_NODES,
    Limits,
    OverLimitInt,
    int_or_over_limit,
    make_limits,
)
from ._paths import edge_paths, label_segment
from ._position import position
from ._yaml_alias import (
    DEFAULT_MAX_ALIAS_EXPANSION,
    DEFAULT_MAX_EXPANDED_SLOTS,
    check_alias_limits,
    reject_forbidden_tags,
    validate_limit_options,
)
from .document import _MAX_DEPTH, _grouped, build_node
from .errors import DocumentError, ParseError, WriteError
from .report import WriteReport, finish_write

if TYPE_CHECKING:
    from .schema import Scalar, Schema

# Canonical numeric-literal spelling for XML's schema-directed pretype step
# (#288) -- same shape as JSON's own number grammar (no leading zeros, no
# leading '+', no bare '.5'), so a numeric-looking element text only
# upgrades when it's unambiguously that number, not merely parseable as
# one (Python's own int()/float() also accept a leading '+', which this
# deliberately excludes).
_EXPAT_UNDEFINED_ENTITY = expat.errors.codes[expat.errors.XML_ERROR_UNDEFINED_ENTITY]
_XML_INT_RE = _re.compile(r"-?(0|[1-9]\d*)")
_XML_NUM_RE = _re.compile(r"-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?")


def _materialize(node: Any, schema: Optional["Schema"]) -> Any:
    """Apply schema-directed deserialization if a schema was given."""
    if schema is None:
        return node
    from .deserialize import materialize
    return materialize(node, schema)


def _check_write_depth(depth: int) -> None:
    """Shared guard for every writer/check_* recursion: raise cleanly instead
    of letting the recursion blow the C stack with a raw ``RecursionError``.
    Uses the same shared maximum depth the reader (oml.py) and the Document
    model (document.py) enforce."""
    if depth > _MAX_DEPTH:
        raise WriteError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})",
                            code="document.limit.depth", path="$")


def _leaves(node: Any, path: str = "$", depth: int = 0) -> Any:
    """Yield ``(path, value)`` for every scalar leaf in a node."""
    if isinstance(node, list):
        _check_write_depth(depth)
        for _label, child, p in edge_paths(path, node):
            yield from _leaves(child, p, depth + 1)
    else:
        yield path, node


def _has_interleaving_loss(node: Any, depth: int = 0) -> bool:
    """True if any list node in the tree has a label reappearing after a
    *different* label's run already ended -- i.e. the JSON-shaped grouping
    rule (`_grouped`, document.py) would reorder same-label edges together,
    losing the original interleaving. A label repeated only contiguously
    (`[(m,A),(m,B),(x,X)]`) groups losslessly and does NOT count."""
    if not isinstance(node, list):
        return False
    _check_write_depth(depth)
    finished: set[Any] = set()
    prev = None
    for label, child in node:
        if label != prev:
            if label in finished:
                return True
            if prev is not None:
                finished.add(prev)
            prev = label
        if _has_interleaving_loss(child, depth + 1):
            return True
    return False


def _check_interleaving(node: Any, rep: WriteReport) -> None:
    """format.interleaving-lost (Sec8.3.8): JSON/YAML/TOML have no way to
    represent cross-label interleaving -- `_grouped` always groups same-label
    edges together regardless of their original position. Reported once at
    "$", the whole document, since the loss isn't localized to any one
    label's edges."""
    if _has_interleaving_loss(node):
        rep.add("$", "format.interleaving-lost",
                "cross-label interleaving is lost: same-label edges are "
                "grouped together regardless of their original position",
                "warning")


def _check_json_text_depth(text: str, max_depth: int) -> None:
    """Reject deeply-nested JSON *before* handing it to ``json.loads`` (#307):
    the standard library parser has no depth limit of its own, so a
    malicious payload can raise an uncaught ``RecursionError`` from inside
    it -- ``build_node()``'s own ``_MAX_DEPTH`` guard runs too late to help,
    since by then ``json.loads`` has already fully parsed (or crashed
    trying). A cheap bracket-depth scan of the raw text, skipping string
    contents, catches this before any real parsing work happens."""
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            if depth > max_depth:
                raise ParseError(f"nesting exceeds the maximum depth ({max_depth})",
                                 code="document.limit.depth", path="$")
        elif ch in "}]":
            depth -= 1


def _int_digits_limit(message: str) -> ParseError:
    """The int-digits limit (D-13, ``document.limit.int-digits``) as a reader
    raises it when it cannot tell which leaf holds the literal: the whole
    document, ``$``. Every reader now marks the literal instead
    (``OverLimitInt``) and ``build_node`` refuses it at its own path; this is
    the fallback of the one reader that cannot always do that (TOML)."""
    return ParseError(message, code="document.limit.int-digits", path="$")


def _yaml_position(exc: Any, text: str) -> str:
    """The ``line:col`` (E-11) of a PyYAML failure: the problem mark where the
    scanner or parser gives one (0-based in the library, 1-based here), the
    reader's character offset for an unprintable character, else ``1:1``."""
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is not None:
        return f"{mark.line + 1}:{mark.column + 1}"
    offset = getattr(exc, "position", None)
    if offset is not None:
        return position(text, offset)
    return "1:1"


_TOML_AT_LINE_RE = _re.compile(r"\(at line (\d+), column (\d+)\)")


def _toml_position(exc: Any, text: str) -> str:
    """The ``line:col`` (E-11) of a ``tomllib`` failure. Python 3.14 exposes
    ``lineno``/``colno``; earlier versions only put ``(at line L, column C)``
    (or ``(at end of document)``) in the message, so read it from there."""
    lineno, colno = getattr(exc, "lineno", None), getattr(exc, "colno", None)
    if lineno is not None and colno is not None:
        return f"{lineno}:{colno}"
    message = str(exc)
    m = _TOML_AT_LINE_RE.search(message)
    if m is not None:
        return f"{m[1]}:{m[2]}"
    if "(at end of document)" in message:
        return position(text, len(text))
    return "1:1"


# --------------------------------------------------------------- JSON
def _json_int_hook(max_digits: int) -> Any:
    """``json.loads``'s ``parse_int``: an integer literal of more than
    ``max_digits`` digits is not converted (CPython's own int-string guard
    would raise a bare ``ValueError`` with no Document path) but returned as
    an ``OverLimitInt``, which ``build_node`` refuses at the leaf's path."""
    return functools.partial(int_or_over_limit, max_digits=max_digits)


def _json_reject_constant(token: str) -> Any:
    """``json.loads``'s ``parse_constant``: JSON has no ``NaN``, ``Infinity``
    or ``-Infinity`` token (C-19), which CPython's decoder would otherwise
    read as a non-finite float. The hook has no position, so it raises a
    ``JSONDecodeError`` whose position the caller leaves at 1:1."""
    raise _json.JSONDecodeError(f"{token} is not a JSON token", token, 0)


def read_json(text: str, *, schema: Optional["Schema"] = None,
              max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
              max_depth: int = DEFAULT_MAX_DEPTH,
              max_nodes: int = DEFAULT_MAX_NODES,
              max_int_digits: int = DEFAULT_MAX_INT_DIGITS) -> Any:
    """Read JSON text into a node.

    ``max_input_bytes`` (default 64 MiB) is D-23's input size limit.
    ``max_depth`` (default and ceiling 200), ``max_nodes`` (default 1 000 000,
    ceiling 10 000 000) and ``max_int_digits`` (default and ceiling 4300) are
    the safety limits of Sec2.4 for this read; exceeding one is
    ``document.limit.depth``, ``.nodes`` or ``.int-digits`` (D-13), the last at
    the Document path of the literal (E-4a). A key repeated in an object keeps
    the last value at the first position (C-11). A number literal beyond
    binary64 reads as an infinity (D-29)."""
    limits = make_limits(max_depth, max_nodes, max_int_digits)
    check_input_size(text, max_input_bytes)      # Sec2.4.2 D-23: first, before anything else
    text = strip_bom(text, reject_second=True)   # Sec2.5 D-15/D-21
    _check_json_text_depth(text, limits.max_depth)
    try:
        data = _json.loads(text, parse_int=_json_int_hook(limits.max_int_digits),
                           parse_constant=_json_reject_constant)
    except _json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}", code="parse.codec-syntax",
                         path=f"{exc.lineno}:{exc.colno}") from exc
    node = build_node(data, limits=limits)
    return _materialize(node, schema)


def write_json(node: Any, *, indent: Optional[int] = None, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    rep = _scan_json(node)
    text = _json.dumps(_grouped(node), indent=indent, ensure_ascii=False, default=_iso)
    return finish_write(text, rep, strict=strict, report=report)


def check_json(node: Any) -> WriteReport:
    """Report what writing JSON would adjust, without producing output."""
    return _scan_json(node)


def _scan_json(node: Any) -> WriteReport:
    check_encodable(node)                        # Sec7.3 C-9, unconditional
    rep = WriteReport()
    for path, v in _leaves(node):
        if isinstance(v, (_dt.date, _dt.time)):
            rep.add(path, "format.temporal-stringified",
                    "temporal value written as an ISO-8601 string", "warning")
        elif isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
            # Issue #325: NaN/Infinity used to be substituted with `null` and
            # reported (format.float-special) -- found to collide with a
            # genuine null value (both produce the identical `null` token,
            # indistinguishable on read-back). No substitute is safe, so this
            # now fails unconditionally, not just under strict.
            raise WriteError(f"{path}: {v} is not valid JSON and has no safe "
                              "substitute", code="write.unsupported-value", path=path)
    _check_interleaving(node, rep)
    return rep


def _iso(o: Any) -> str:
    if isinstance(o, (_dt.date, _dt.time)):
        return o.isoformat()
    raise TypeError(f"cannot serialize {type(o).__name__}")


# --------------------------------------------------------------- YAML
def read_yaml(text: str, *, schema: Optional["Schema"] = None,
              max_alias_expansion: int = DEFAULT_MAX_ALIAS_EXPANSION,
              max_expanded_slots: int = DEFAULT_MAX_EXPANDED_SLOTS,
              max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
              max_depth: int = DEFAULT_MAX_DEPTH,
              max_nodes: int = DEFAULT_MAX_NODES,
              max_int_digits: int = DEFAULT_MAX_INT_DIGITS) -> Any:
    """Read YAML text into a node.

    ``max_input_bytes`` (default 64 MiB) is the largest input, in UTF-8 bytes,
    that is read at all (D-23); see ``docs/api.md``.

    ``max_depth`` (default and ceiling 200), ``max_nodes`` (default 1 000 000,
    ceiling 10 000 000) and ``max_int_digits`` (default and ceiling 4300) are
    the safety limits of Sec2.4 for this read; exceeding one is
    ``document.limit.depth``, ``.nodes`` or ``.int-digits`` (D-13), the last at
    the Document path of the literal, whose digits are counted in its
    *value* whatever the spelling: ``0xFFF``, ``07777`` and ``4_095`` all have
    four (D-28). A mapping that repeats a key is refused as
    ``parse.codec-syntax`` (C-12), and a node tagged ``!!pairs``, ``!!omap`` or
    ``!!set`` as ``format.tag-forbidden`` (C-13).

    ``max_alias_expansion`` (default 50, at most 10 000) is the largest
    expansion factor ``W / S`` any mapping or sequence may have (D-18), and
    ``max_expanded_slots`` (default 1 000 000, at most 10 000 000) the largest
    number of value slots an input containing an alias or a merge key may
    materialize (D-22); an input over either is refused with
    ``document.limit.alias-expansion`` or ``document.limit.expanded-size``
    *before* any alias is expanded. An input with neither an alias nor a merge
    key is exempt from the second. See ``docs/formats/yaml.md``.
    """
    validate_limit_options(max_alias_expansion, max_expanded_slots)
    limits = make_limits(max_depth, max_nodes, max_int_digits)
    check_input_size(text, max_input_bytes)      # Sec2.4.2 D-23: before anything else is read
    text = strip_bom(text, reject_second=True)   # Sec2.5 D-15/D-21
    yaml = _need("yaml", "pip install pyyaml")
    loader = None
    try:
        loader = _yaml_loader(yaml)(text)
        loader.omnist_max_int_digits = limits.max_int_digits
        # compose -> check the anchor/alias graph -> only then construct, so
        # no alias is ever expanded for an input that is over a limit (D-19).
        root = loader.get_single_node()
        data = None
        if root is not None:
            reject_forbidden_tags(root, yaml.nodes)     # C-13
            check_alias_limits(root, yaml.nodes, saw_alias=loader.omnist_saw_alias,
                               max_alias_expansion=max_alias_expansion,
                               max_expanded_slots=max_expanded_slots)
            data = loader.construct_document(root)
        node = build_node(data, limits=limits)
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML: {exc}", code="parse.codec-syntax",
                         path=_yaml_position(exc, text)) from exc
    except ValueError as exc:
        # What is left is PyYAML's timestamp resolver: `2001-13-45` matches
        # YAML 1.1's timestamp pattern, then fails to be a date. The library
        # gives no position for it. (An over-long integer never gets here: the
        # loader marks it, see construct_yaml_int, and build_node refuses it.)
        raise ParseError(f"invalid YAML: {exc}", code="parse.codec-syntax",
                         path="1:1") from exc
    except RecursionError as exc:
        # #307: unlike JSON's bracket grammar, YAML nesting (indentation,
        # flow collections, anchors) isn't cheap to bound from raw text
        # without reimplementing the grammar -- this is a safety net that
        # converts an uncaught crash into the same clean error a depth
        # violation always raises, rather than precise prevention.
        raise ParseError(f"nesting exceeds the maximum depth ({limits.max_depth})",
                         code="document.limit.depth", path="$") from exc
    finally:
        if loader is not None:
            loader.dispose()
    return _materialize(node, schema)


_YAML_LOADER_CACHE: dict[Any, Any] = {}

_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"
_YAML_VALUE_TAG = "tag:yaml.org,2002:value"
_YAML_STR_TAG = "tag:yaml.org,2002:str"
_YAML_NONZERO_DIGITS = tuple("123456789")


def _yaml_loader(yaml: Any) -> type[Any]:
    """PyYAML's ``SafeLoader`` with the merge key (``<<``) flattened in
    *source order*, per ``docs/formats/yaml.md`` (Sec YAML, "Merged entries
    come first, in source order").

    Stock PyYAML flattens a merge *sequence* in reverse (``submerge.reverse()``
    in ``SafeConstructor.flatten_mapping``), so ``<<: [*a, *b]`` reads ``b``'s
    entries before ``a``'s. That is an artefact of how it makes the earlier
    alias win a key collision (later dict assignments overwrite earlier
    ones), not a rule of the format, and an ordered Document cannot inherit
    it. This subclass overrides the constructor's flatten step -- not the
    library -- to resolve the whole merge explicitly instead:

    * merged entries come first, each merged mapping in its own (already
      flattened) order, the mappings in sequence order, then the mapping's own;
    * a key supplied more than once yields exactly one edge, at the position
      of its first occurrence in that order;
    * that edge carries the referring mapping's own value when it writes the
      key, else the value from the earliest merged mapping that supplies it.
    """
    cls = _YAML_LOADER_CACHE.get(yaml)
    if cls is not None:
        return cls  # type: ignore[no-any-return]
    ConstructorError = yaml.constructor.ConstructorError
    MappingNode = yaml.MappingNode

    AliasEvent = yaml.events.AliasEvent

    class _OmnistYamlLoader(yaml.SafeLoader):  # type: ignore[misc]
        def __init__(self, stream: Any) -> None:
            super().__init__(stream)
            #: whether the composer resolved any alias (PyYAML nodes do not
            #: record their anchors); D-22 applies only when one was seen.
            self.omnist_saw_alias = False
            #: the integer-digit limit of this read (D-9, D-28); read_yaml sets it
            self.omnist_max_int_digits = DEFAULT_MAX_INT_DIGITS

        def compose_node(self, parent: Any, index: Any) -> Any:
            if self.check_event(AliasEvent):
                self.omnist_saw_alias = True
            else:
                # YAML 1.2 lets an anchor be defined again; the latest
                # definition applies to the aliases after it. PyYAML refuses
                # a duplicate, so forget the earlier one first.
                anchor = self.peek_event().anchor
                if anchor is not None:
                    self.anchors.pop(anchor, None)
            return super().compose_node(parent, index)

        def construct_yaml_int(self, node: Any) -> Any:
            """A plain decimal literal of more than the limit's digits is not
            converted (PyYAML's ``int()`` would raise CPython's bare
            ``ValueError`` past 4300 digits, with no Document path): it reads
            as an ``OverLimitInt`` and ``build_node`` refuses it at the leaf's
            path. A hex, octal or binary literal converts without that guard
            and is checked on its value (D-28)."""
            text = self.construct_scalar(node).replace("_", "")
            if text.lstrip("+-")[:1] in _YAML_NONZERO_DIGITS and ":" not in text:
                return int_or_over_limit(text, self.omnist_max_int_digits)
            return super().construct_yaml_int(node)

        def construct_yaml_timestamp(self, node: Any) -> Any:
            """PyYAML cuts a fraction to six digits without a word. The
            Document holds microseconds at most, so a non-zero digit past the
            sixth is refused (fail, don't invent); zeros past it are dropped."""
            if fraction_inexact(self.construct_scalar(node)):
                raise ConstructorError(
                    None, None,
                    "a fractional second has more than six digits (the Document "
                    "model holds at most microseconds); it would be altered",
                    node.start_mark)
            return super().construct_yaml_timestamp(node)

        def flatten_mapping(self, node: Any) -> None:
            merged: list[list[Any]] = []       # one entry list per merged mapping
            written: set[Any] = set()          # C-12: the keys this mapping writes itself
            index = 0
            while index < len(node.value):
                key_node, value_node = node.value[index]
                if key_node.tag == _YAML_MERGE_TAG:
                    # Deleted *before* recursing, as PyYAML does: a mapping
                    # that merges itself (or is merged into something it
                    # contains) then terminates instead of recursing forever.
                    del node.value[index]
                    if isinstance(value_node, MappingNode):
                        self.flatten_mapping(value_node)
                        merged.append(list(value_node.value))
                    else:
                        # a sequence of mappings: every other merge shape was
                        # refused as parse.codec-syntax before this runs (D-18a)
                        for subnode in value_node.value:
                            self.flatten_mapping(subnode)
                            merged.append(list(subnode.value))
                else:
                    if key_node.tag == _YAML_VALUE_TAG:
                        key_node.tag = _YAML_STR_TAG
                    key = self._merge_key(node, key_node)
                    # C-12: a key written twice in one mapping is refused. A key
                    # a merge key supplies is not a repeat of one written here
                    # (the merge below resolves that), so only this mapping's
                    # own entries are counted; (type, value) keeps 1 and 1.0
                    # and "1" apart, as the keys they construct are.
                    if (type(key), key) in written:
                        raise ConstructorError(
                            "while constructing a mapping", node.start_mark,
                            f"found duplicate key {key!r}", key_node.start_mark)
                    written.add((type(key), key))
                    index += 1
            if merged:
                node.value = self._merge_entries(node, merged)

        def _merge_entries(self, node: Any, merged: list[list[Any]]) -> list[Any]:
            """Resolve ``merged`` (source order) followed by ``node``'s own
            entries into one entry list with each key exactly once."""
            entries: dict[Any, Any] = {}
            for source in merged:
                for key_node, value_node in source:
                    key = self._merge_key(node, key_node)
                    if key not in entries:            # earliest merged mapping wins
                        entries[key] = (key_node, value_node)
            for key_node, value_node in node.value:
                key = self._merge_key(node, key_node)
                # the local value, in the merged key's position when it has one
                entries[key] = (entries[key][0] if key in entries else key_node, value_node)
            return list(entries.values())

        def _merge_key(self, node: Any, key_node: Any) -> Any:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    "found unhashable key", key_node.start_mark) from exc
            return key

    _OmnistYamlLoader.add_constructor("tag:yaml.org,2002:int",
                                      _OmnistYamlLoader.construct_yaml_int)
    _OmnistYamlLoader.add_constructor("tag:yaml.org,2002:timestamp",
                                      _OmnistYamlLoader.construct_yaml_timestamp)
    _YAML_LOADER_CACHE[yaml] = _OmnistYamlLoader
    return _OmnistYamlLoader


def write_yaml(node: Any, *, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    yaml = _need("yaml", "pip install pyyaml")
    rep = check_yaml(node)
    prepared = _prepare_yaml(node)
    dumper = _yaml_dumper(yaml)
    text = yaml.dump(_grouped(prepared), Dumper=dumper, sort_keys=False,
                     allow_unicode=True, default_flow_style=False)
    return finish_write(text, rep, strict=strict, report=report)


def check_yaml(node: Any) -> WriteReport:
    check_encodable(node)                        # Sec7.3 C-9, unconditional
    rep = WriteReport()
    for path, v in _leaves(node):
        if isinstance(v, _dt.time):       # YAML carries date/datetime natively, not time
            rep.add(path, "format.temporal-stringified",
                    "time-of-day written as a string (YAML has no standalone time)",
                    "warning")
    _scan_yaml_labels(node, "$", rep)
    _check_interleaving(node, rep)
    return rep


def _scan_yaml_labels(node: Any, path: str, rep: WriteReport, depth: int = 0) -> None:
    """PyYAML's emitter/parser treat U+0085 (NEL) as a line-break character and
    normalize it away under the default (unquoted/single-quoted) scalar styles,
    so a label containing it would silently come back as a space.  We force
    double-quoted style for any such scalar (see ``_yaml_str_representer``),
    which round-trips correctly, but still flag it here for visibility."""
    if not isinstance(node, list):
        return
    _check_write_depth(depth)
    for label, child, p in edge_paths(path, node):
        if isinstance(label, str) and "\x85" in label:
            rep.add(p, "format.string-line-break-char",
                    "label contains U+0085 (NEL); written double-quoted to "
                    "round-trip correctly", "warning")
        if isinstance(child, str) and "\x85" in child:
            rep.add(p, "format.string-line-break-char",
                    "value contains U+0085 (NEL); written double-quoted to "
                    "round-trip correctly", "warning")
        _scan_yaml_labels(child, p, rep, depth + 1)


def _prepare_yaml(node: Any, depth: int = 0) -> Any:
    if isinstance(node, list):
        _check_write_depth(depth)
        return [(label, _prepare_yaml(c, depth + 1)) for label, c in node]
    if isinstance(node, _dt.time):
        return _YamlQuoted(node.isoformat())      # E-37 rule 4: double-quoted
    return node


class _YamlQuoted(str):
    """A string that must be written double-quoted (E-37 rule 4)."""


def _yaml_quoted_representer(dumper: Any, data: str) -> Any:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


def _yaml_datetime_representer(dumper: Any, data: _dt.datetime) -> Any:
    # E-37 rule 3: ISO-8601 with the ``T`` separator (PyYAML's default is a space).
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", data.isoformat())


_YAML_ESCAPE = _re.compile(r"\\[xuU][0-9A-F]+\Z")


class _LowerEscapes:
    """Stream wrapper: PyYAML writes each escape sequence in one ``write`` call
    and never writes a backslash inside a plain text segment, so a whole-write
    an escape sequence matched whole; C-14 pins its digits lowercase."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, data: str) -> Any:
        return self._stream.write(data[:2] + data[2:].lower() if _YAML_ESCAPE.match(data) else data)


def _yaml_write_double_quoted(self: Any, text: str, split: bool = True) -> None:
    orig = self.stream
    self.stream = _LowerEscapes(orig)
    try:
        _need("yaml", "pip install pyyaml").emitter.Emitter.write_double_quoted(
            self, text, split)
    finally:
        self.stream = orig


def _yaml_str_representer(dumper: Any, data: str) -> Any:
    # U+0085 (NEL) is normalized to a space by PyYAML under the default
    # scalar styles; double-quoted style escapes it (as "\N") and round-trips.
    style = '"' if "\x85" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_YAML_DUMPER_CACHE: dict[Any, Any] = {}


def _yaml_dumper(yaml: Any) -> type[Any]:
    """A SafeDumper subclass whose str representer escapes U+0085 safely."""
    dumper = _YAML_DUMPER_CACHE.get(yaml)
    if dumper is None:
        dumper = type("_OmnistYamlDumper", (yaml.SafeDumper,),
                      {"write_double_quoted": _yaml_write_double_quoted})
        dumper.add_representer(str, _yaml_str_representer)  # type: ignore[attr-defined]
        dumper.add_representer(_YamlQuoted, _yaml_quoted_representer)  # type: ignore[attr-defined]
        dumper.add_representer(_dt.datetime, _yaml_datetime_representer)  # type: ignore[attr-defined]
        _YAML_DUMPER_CACHE[yaml] = dumper
    return dumper


# --------------------------------------------------------------- TOML
_TOML_DECIMAL = _re.compile(r"[+-]?[0-9](?:_?[0-9])*(?=[\s,\]}#]|\Z)")


def _toml_string_end(text: str, i: int) -> int:
    """The offset just past the TOML string that starts at ``text[i]``."""
    quote, n = text[i], len(text)
    if text.startswith(quote * 3, i):                       # multi-line
        j = i + 3
        while j < n:
            if quote == '"' and text[j] == "\\":
                j += 2
            elif text.startswith(quote * 3, j):
                j += 3
                for _ in range(2):                          # up to two quotes of content
                    if j < n and text[j] == quote:
                        j += 1
                return j
            else:
                j += 1
        return n
    j = i + 1                                               # single-line
    while j < n and text[j] not in (quote, "\n"):
        j += 2 if quote == '"' and text[j] == "\\" else 1
    return min(j + 1, n)


def _toml_mark_over_limit(text: str, max_digits: int) -> Optional[tuple[str, str]]:
    """Rewrite each decimal integer literal of more than ``max_digits`` digits
    in a TOML value position (after ``=``, ``,``, ``[`` or ``{``; strings and
    comments are skipped) to the float spelling ``marker``, and return
    ``(new_text, marker)``; ``None`` when there is none.

    ``tomllib`` converts an integer with the builtin ``int`` and has no hook
    for it, so a literal past CPython's int-string guard fails with a bare
    ``ValueError`` and no position. Marking it lets ``parse_float`` (which
    ``tomllib`` does have) hand back an ``OverLimitInt`` at the leaf, so the
    refusal can carry the Document path of the literal (E-4a). A heuristic that
    misses a literal falls back to the whole-document path ``$``."""
    marker_exponent = 400
    while f"1e-{marker_exponent}" in text:
        marker_exponent += 1
    marker = f"1e-{marker_exponent}"
    out: list[str] = []
    i, n, prev, replaced = 0, len(text), "\n", False
    while i < n:
        ch = text[i]
        if ch == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])
            i = j
        elif ch in "\"'":
            j = _toml_string_end(text, i)
            out.append(text[i:j])
            i, prev = j, ch
        elif ch.isspace():
            out.append(ch)
            i += 1
        else:
            m = _TOML_DECIMAL.match(text, i) if prev in "=,[{" else None
            if m is not None and sum(c.isdigit() for c in m[0]) > max_digits:
                out.append(marker)
                i, prev, replaced = m.end(), "1", True
            else:
                out.append(ch)
                i, prev = i + 1, ch
    return ("".join(out), marker) if replaced else None


_TOML_FRACTION_PROBE = _re.compile(r"\.[0-9]{7}")
_TOML_TEMPORAL = _re.compile(
    r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ])?[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]+")


def fraction_inexact(text: str) -> bool:
    """Whether a temporal literal's fractional second has a non-zero digit
    past the sixth: such a value cannot be held (the Document keeps
    microseconds) without altering it. Zeros past the sixth are insignificant."""
    dot = text.find(".")
    if dot < 0:
        return False
    digits = 0
    for ch in text[dot + 1:]:
        if not "0" <= ch <= "9":
            break
        digits += 1
    return digits > 6 and text[dot + 7:dot + 1 + digits].strip("0") != ""


def _toml_check_fractions(text: str) -> None:
    """``tomllib`` cuts a fraction to six digits without a word. Refuse a time
    or datetime literal (value position; strings and comments skipped) whose
    fraction has a non-zero digit past the sixth: ``parse.codec-syntax`` at the
    literal. Runs on text ``tomllib`` accepted, and only when seven fraction
    digits appear somewhere in it."""
    if _TOML_FRACTION_PROBE.search(text) is None:
        return
    i, n, prev = 0, len(text), "\n"
    while i < n:
        ch = text[i]
        if ch == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif ch in "\"'":
            i, prev = _toml_string_end(text, i), ch
        elif ch.isspace():
            i += 1
        else:
            m = _TOML_TEMPORAL.match(text, i) if prev in "=,[{" else None
            if m is not None:
                if fraction_inexact(m[0]):
                    raise ParseError(
                        "invalid TOML: a fractional second has more than six digits "
                        "(the Document model holds at most microseconds); "
                        "it would be altered",
                        code="parse.codec-syntax", path=position(text, i))
                i, prev = m.end(), "1"
            else:
                i, prev = i + 1, ch


def _toml_loads(text: str, max_digits: int) -> Any:
    import tomllib
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise
    except ValueError as exc:
        # CPython's int-string guard (an integer of more than 4300 digits, or
        # whatever limit the process has set), which tomllib does not catch.
        marked = _toml_mark_over_limit(text, max_digits)
        if marked is not None:
            new_text, marker = marked
            try:
                return tomllib.loads(
                    new_text, parse_float=lambda s: OverLimitInt() if s == marker else float(s))
            except ValueError:
                pass
        raise _int_digits_limit(f"invalid TOML: {exc}") from exc


def read_toml(text: str, *, schema: Optional["Schema"] = None,
              max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
              max_depth: int = DEFAULT_MAX_DEPTH,
              max_nodes: int = DEFAULT_MAX_NODES,
              max_int_digits: int = DEFAULT_MAX_INT_DIGITS) -> Any:
    """Read TOML text into a node.

    ``max_depth`` (default and ceiling 200), ``max_nodes`` (default 1 000 000,
    ceiling 10 000 000) and ``max_int_digits`` (default and ceiling 4300) are
    the safety limits of Sec2.4 for this read; exceeding one is
    ``document.limit.depth``, ``.nodes`` or ``.int-digits`` (D-13), the last at
    the Document path of the literal, whose digits are counted in its *value*
    whatever the spelling (D-28). A repeated key is refused as
    ``parse.codec-syntax`` (C-12); a float literal beyond binary64 reads as an
    infinity (D-29)."""
    limits = make_limits(max_depth, max_nodes, max_int_digits)
    check_input_size(text, max_input_bytes)      # Sec2.4.2 D-23: first, before anything else
    text = strip_bom(text, reject_second=True)   # Sec2.5 D-15/D-21
    import tomllib
    try:
        data = _toml_loads(text, limits.max_int_digits)
        _toml_check_fractions(text)
        node = build_node(data, limits=limits)
    except tomllib.TOMLDecodeError as exc:
        raise ParseError(f"invalid TOML: {exc}", code="parse.codec-syntax",
                         path=_toml_position(exc, text)) from exc
    except RecursionError as exc:
        # #307: same safety net as read_yaml -- TOML nesting (inline
        # tables/arrays, dotted keys) isn't cheap to bound from raw text
        # without reimplementing the grammar.
        raise ParseError(f"nesting exceeds the maximum depth ({limits.max_depth})",
                         code="document.limit.depth", path="$") from exc
    return _materialize(node, schema)


def write_toml(node: Any, *, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    tomli_w = _need("tomli_w", "pip install tomli_w")
    check_encodable(node)                        # Sec7.3 C-9, unconditional
    rep = WriteReport()
    stripped = _strip_nulls(node, "$", rep)        # TOML has no null
    _check_interleaving(node, rep)
    grouped = _grouped(stripped)
    if not isinstance(grouped, dict):
        raise WriteError("TOML needs a top-level table (the root must be an object)",
                         code="write.unsupported-value", path="$")
    text = tomli_w.dumps(grouped)
    return finish_write(text, rep, strict=strict, report=report)


def check_toml(node: Any) -> WriteReport:
    check_encodable(node)                        # Sec7.3 C-9, unconditional
    rep = WriteReport()
    _strip_nulls(node, "$", rep)
    _check_interleaving(node, rep)
    return rep


class _TomlDatetime(_dt.datetime):
    """A datetime whose ``str`` (what tomli_w writes) uses the ``T`` separator."""

    @classmethod
    def of(cls, d: _dt.datetime) -> "_TomlDatetime":
        return cls(d.year, d.month, d.day, d.hour, d.minute, d.second,
                   d.microsecond, d.tzinfo, fold=d.fold)

    def __str__(self) -> str:
        return self.isoformat()


def _strip_nulls(node: Any, path: str, rep: WriteReport, depth: int = 0) -> Any:
    """Reject a null leaf (TOML can't hold null, and there is no substitute
    value to fall back to).

    Issue #324: this used to drop the edge and record the loss
    (``format.null-unrepresentable``) -- but dropping doesn't just alter what
    a position holds, it erases the edge's existence entirely, with no trace
    on read-back that it was ever there. That's unconditional data loss, so
    the write now fails unconditionally too, not just under strict.
    """
    if not isinstance(node, list):
        return node
    _check_write_depth(depth)
    out: list[tuple[str, Any]] = []
    for label, child, p in edge_paths(path, node):
        if isinstance(child, _dt.time) and child.tzinfo is not None:
            # E-37 rule 4: TOML has no offset time -- string + warning.
            rep.add(p, "format.temporal-stringified",
                    "time with an offset written as an ISO-8601 string "
                    "(TOML has no offset time)", "warning")
            child = child.isoformat()
        elif isinstance(child, _dt.datetime):
            child = _TomlDatetime.of(child)         # E-37 rule 3: ``T`` separator
        if child is None:
            raise WriteError(f"{p}: null has no representation in TOML",
                              code="write.unsupported-value", path=p)
        out.append((label, _strip_nulls(child, p, rep, depth + 1)))
    return out


# --------------------------------------------------------------- XML
_XML_NAME = _re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*\Z")

# XML 1.0 only legally permits tab (U+0009), LF (U+000A), CR (U+000D), and
# U+0020-U+D7FF, U+E000-U+FFFD, U+10000-U+10FFFF in character data.  Built
# from codepoint ranges (rather than embedding raw control / surrogate
# characters in this source file) to avoid any encoding ambiguity.
_XML_ILLEGAL_RANGES = (
    (0x00, 0x08), (0x0B, 0x0C), (0x0E, 0x1F),   # C0 controls minus tab/LF/CR
    (0xD800, 0xDFFF),                            # surrogate range
    (0xFFFE, 0xFFFF),                            # BMP noncharacters
)
_XML_ILLEGAL_CHAR = _re.compile(
    chr(0x5B) + "".join(chr(lo) + "-" + chr(hi) for lo, hi in _XML_ILLEGAL_RANGES) + chr(0x5D))


def read_xml(text: str, *, schema: Optional["Schema"] = None,
            report: Optional[WriteReport] = None,
            max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
            max_depth: int = DEFAULT_MAX_DEPTH,
            max_nodes: int = DEFAULT_MAX_NODES,
            max_int_digits: int = DEFAULT_MAX_INT_DIGITS) -> Any:
    """Read XML text into a node.

    ``max_depth`` (default and ceiling 200), ``max_nodes`` (default 1 000 000,
    ceiling 10 000 000) and ``max_int_digits`` (default and ceiling 4300) are
    the safety limits of Sec2.4 for this read; exceeding one is
    ``document.limit.depth``, ``.nodes`` or ``.int-digits`` (D-13). Nodes are
    counted as every other format counts them: the root and each element with
    child elements (E-4a), not a leaf element. The digit limit applies to an
    integer leaf pretyped against ``schema`` (D-28), refused at the leaf's
    Document path."""
    limits = make_limits(max_depth, max_nodes, max_int_digits)
    check_input_size(text, max_input_bytes)      # Sec2.4.2 D-23: first, before anything else
    text = strip_bom(text, reject_second=True)   # Sec2.5 D-15/D-21
    root = _xml_fromstring(text)
    root_local = _local(root.tag)
    # `epath` is the proper full dotted Document path (Sec8.4 convention),
    # used only for format.attribute-dropped/format.namespace-dropped --
    # kept separate from `path` below, which is the pre-existing (shallower)
    # scheme mixed-content errors already use and report on.
    root_epath = f"$.{root_local}"
    _check_xml_drops(root, root_epath, report)
    node = [(root_local, _xml_to_node(root, "$", 0, [1], report, root_epath, limits))]
    if schema is not None:
        # #288: recover boolean/integer/number from XML's untyped text
        # before the shared materialize() sees it. This is XML-specific,
        # not a materialize() capability -- materialize() itself must keep
        # rejecting a string that merely looks numeric (a string is a
        # deliberate choice in JSON/YAML/TOML/OML, never an untyped
        # placeholder the way it always is in XML).
        node = _xml_pretype(node, schema, schema.root, "$", limits)
    return _materialize(node, schema)


def _xml_pretype(node: Any, schema: "Schema", t: Any, path: str, limits: Limits) -> Any:
    from .schema import AnyType, Scalar
    d = schema.resolve(t)
    if isinstance(d, AnyType):
        return node
    if isinstance(d, Scalar):
        return _xml_pretype_scalar(node, d, path, limits)
    if not isinstance(node, list):
        return node
    out = []
    for label, child, child_path in edge_paths(path, node):
        f = d.field(label)
        out.append((label, _xml_pretype(child, schema, f.type, child_path, limits)
                    if f else child))
    return out


def _xml_pretype_scalar(value: Any, s: "Scalar", path: str, limits: Limits) -> Any:
    # value is always the str _xml_to_node produced -- _xml_pretype is only
    # ever called on a freshly-built XML node, never a value from elsewhere.
    if s.name == "boolean" and value in ("true", "false"):
        return value == "true"
    if s.name == "integer" and _XML_INT_RE.fullmatch(value):
        number = int_or_over_limit(value, limits.max_int_digits)
        if isinstance(number, OverLimitInt):
            # D-28/E-4a: the digit limit of an integer leaf, at the leaf's path
            # (it used to be CPython's bare ValueError).
            raise DocumentError(
                f"{path}: integer has more than {limits.max_int_digits} digits, "
                "exceeding the digit limit (security: unbounded-digit int-to-str "
                "conversion is superlinear)", code="document.limit.int-digits", path=path)
        return number
    if s.name == "number" and _XML_NUM_RE.fullmatch(value):
        return float(value)
    return value


def _xml_to_node(elem: Any, path: str, depth: int, budget: list[int],
                 report: Optional[WriteReport], epath: str, limits: Limits) -> Any:
    # budget is a shared running node count across the whole call tree, the
    # same mechanism build_node uses (document.py) -- unlike build_node's
    # readers, XML's ElementTree parse has no aliasing mechanism to create a
    # DAG (defusedxml also blocks DTDs, closing the classic XML entity-
    # expansion vector upstream), so there's no _MAX_DEPTH-bypassing
    # amplification vector here. This guard exists for the same size
    # ceiling every other reader now has, not because an exploit is known.
    #
    # Depth and nodes are counted as the other readers count them (E-4a): the
    # value of this element's edge sits one level below its container, a leaf
    # as much as a container, and only a container is a node -- the root is
    # the one already in ``budget``, then each element with child elements.
    if depth + 1 > limits.max_depth:
        raise DocumentError(
            f"{path}: nesting exceeds the maximum depth ({limits.max_depth})",
            code="document.limit.depth", path="$")
    children = list(elem)
    if children:
        budget[0] += 1
        if budget[0] > limits.max_nodes:
            raise DocumentError(
                f"{path}: too many nodes materialized (over {limits.max_nodes})",
                code="document.limit.nodes", path="$")
        if elem.text and elem.text.strip():
            raise ParseError(
                f"{path}: mixed content (text alongside child elements) is "
                "outside the data-XML profile", code="format.mixed-content", path="$")
        for c in children:
            if c.tail and c.tail.strip():
                p = f"{path}{label_segment(_local(c.tag))}"
                raise ParseError(
                    f"{p}: mixed content (text alongside "
                    "child elements) is outside the data-XML profile",
                    code="format.mixed-content", path="$")
        out = []
        # E-10 (omnist#357): the index is on every edge of a label that
        # repeats in this node, so the drop-diagnostic path is built by the
        # shared edge_paths helper, not by hand.
        edges = [(_local(c.tag), c) for c in children]
        for (c_local, c), (_, _, cepath) in zip(edges, edge_paths(epath, edges)):
            p = f"{path}{label_segment(c_local)}"
            _check_xml_drops(c, cepath, report)
            out.append((c_local, _xml_to_node(c, p, depth + 1, budget, report, cepath,
                                              limits)))
        return out
    return elem.text or ""


def write_xml(node: Any, *, strict: bool = False,
              report: Optional[WriteReport] = None) -> str:
    check_encodable(node)                        # Sec7.3 C-9, unconditional (first)
    if not (isinstance(node, list) and len(node) == 1):
        raise WriteError(
            "XML needs exactly one document element; the root node must have a "
            "single top-level edge (a single-rooted Document)",
            code="format.multiple-roots", path="$")
    rep = WriteReport()
    _scan_xml(node, "$", rep)
    import xml.etree.ElementTree as ET
    (tag, content), = node
    el = ET.Element(tag)
    _node_to_xml(content, el)
    _indent(el)
    text = ET.tostring(el, encoding="unicode")
    # Issue #326: a numeric character reference is exempt from XML's
    # mandated line-ending normalization on parse, so escaping a literal CR
    # (and CRLF) this way is genuinely lossless -- unlike every other
    # `\r`-in-text-content byte, a real `&#13;` never occurs in
    # ET.tostring's own output (its own formatting/indentation only ever
    # inserts `\n`), so a plain string replace on the serialized text can't
    # collide with anything else in it.
    text = text.replace("\r\n", "&#13;\n").replace("\r", "&#13;")
    return finish_write(text, rep, strict=strict, report=report)


def check_xml(node: Any) -> WriteReport:
    check_encodable(node)                        # Sec7.3 C-9, unconditional
    rep = WriteReport()
    _scan_xml(node, "$", rep)
    return rep


def _scan_xml(node: Any, path: str, rep: WriteReport, depth: int = 0) -> None:
    if isinstance(node, list):
        _check_write_depth(depth)
        if not node:
            # Issue #325: an empty internal node and an empty-string leaf
            # both serialize to <tag />, and read_xml always reconstructs
            # the leaf -- the same collision shape as the label/null cases
            # below. No substitute is safe, so this now fails
            # unconditionally instead of substituting-and-warning
            # (previously format.shape-empty-ambiguous).
            raise WriteError(
                f"{path}: an empty internal node has no XML spelling distinct "
                "from an empty-string leaf",
                code="write.unsupported-value", path=path)
        for label, child, p in edge_paths(path, node):
            if not _XML_NAME.match(label):
                # Issue #323: two different labels can sanitize to the same
                # XML name (e.g. "my label" and "my_label" both becoming
                # <my_label>), silently colliding on read-back with no
                # diagnostic. No single well-defined substitute is safe, so
                # this now fails unconditionally instead of
                # substituting-and-warning (previously format.key-sanitized).
                raise WriteError(f"{p}: label {label!r} isn't a valid XML name",
                                  code="write.unsupported-value", path=p)
            _scan_xml(child, p, rep, depth + 1)
        return
    v = node
    if v is None:
        # Sec7.3 C-10: XML has no null token and `<a/>` reads back as the
        # empty string, so a written null would be indistinguishable from
        # the different, valid Document holding "". Fails unconditionally,
        # regardless of `strict`, at the (E-10 indexed) path of the leaf.
        raise WriteError(
            f"{path}: a null leaf has no XML spelling (an empty element "
            "reads back as the empty string)",
            code="write.unsupported-value", path=path)
    elif isinstance(v, (_dt.date, _dt.time)):
        rep.add(path, "format.temporal-stringified",
                "temporal value written as text (reads back as a string)", "warning")
    elif isinstance(v, (bool, int, float)):
        # #288: read_xml no longer infers scalar kind from text shape, so a
        # non-string scalar written to XML (XML has no native typed
        # literals -- everything is text) now reads back as a string, not
        # its original type. Previously silent (the old shape-based
        # coercion happened to undo this on read); now reported like every
        # other type-losing write.
        rep.add(path, "format.value-stringified",
                "non-string scalar written as text (reads back as a string)", "warning")
    if isinstance(v, str):
        if _XML_ILLEGAL_CHAR.search(v):
            # Issue #323: same "no safe substitute" collision shape as the
            # label case above -- U+FFFD substitution is unconditional data
            # corruption, not a recoverable adjustment. Fails unconditionally
            # instead of substituting-and-warning (previously
            # format.string-illegal-char).
            raise WriteError(
                f"{path}: string contains a character XML 1.0 cannot "
                "represent (e.g. a C0 control other than tab/LF/CR)",
                code="write.unsupported-value", path=path)
        # Issue #326: a CR is now escaped as the numeric character reference
        # `&#13;` on write (see write_xml), which survives a compliant
        # parser's line-ending normalization intact -- genuinely lossless,
        # so there's nothing left to report here (previously
        # format.string-cr-normalized, a warning-severity adjustment).


def _node_to_xml(content: Any, parent: Any) -> None:
    import xml.etree.ElementTree as ET
    if isinstance(content, list):
        for label, child in content:
            # _scan_xml already rejected (via write.unsupported-value) any
            # label that isn't a valid XML name, so every label reaching
            # here is used verbatim -- no sanitizing fallback needed
            # (issue #323).
            sub = ET.SubElement(parent, label)
            _node_to_xml(child, sub)
    else:
        parent.text = _xml_text(content)


def _xml_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    return str(v)


def _local(tag: str) -> str:
    # _xml_fromstring builds every tag with a non-namespace-aware expat
    # parser, so a Clark-notation "{uri}local" tag can never reach here --
    # only ever a literal tag, "b" or a prefixed "ns:b".
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


_XMLNS_ATTR = _re.compile(r"^xmlns(:|$)")


def _check_xml_drops(elem: Any, path: str, report: Optional[WriteReport]) -> None:
    """format.attribute-dropped / format.namespace-dropped (Sec8.3.8): fired
    at the element the loss happened on, the same convention format.float-
    special uses for the value it substituted. ElementTree gives every
    element a plain (non-namespace-aware) tag/attrib here -- see
    `_xml_fromstring` -- so a namespace prefix survives as a literal
    `prefix:local` tag, and an `xmlns`/`xmlns:prefix` declaration survives
    as a literal attribute rather than being consumed by namespace
    processing; the latter is filtered out below so it isn't double-counted
    as a dropped *data* attribute (it's already covered by
    format.namespace-dropped)."""
    if report is None:
        return
    if ":" in elem.tag:
        report.add(path, "format.namespace-dropped",
                    "XML namespace prefix discarded on read (element reads "
                    "as its local name only)", "warning")
    if any(not _XMLNS_ATTR.match(k) for k in elem.attrib):
        report.add(path, "format.attribute-dropped",
                    "XML attribute(s) discarded on read (there is no path "
                    "from a Document edge back to an attribute)", "warning")


def _indent(elem: Any, level: int = 0) -> None:
    pad = "\n" + "  " * level
    children = list(elem)
    if children:
        if not (elem.text and elem.text.strip()):
            elem.text = pad + "  "
        for i, child in enumerate(children):
            _indent(child, level + 1)
            child.tail = (pad + "  ") if i < len(children) - 1 else pad
        if not (elem.tail and elem.tail.strip()):
            elem.tail = pad if level else "\n"


def _xml_parser() -> Any:
    try:
        import defusedxml.ElementTree as ET  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("defusedxml is required: pip install defusedxml") from exc
    return ET


def _xml_fromstring(text: str) -> Any:
    """Parse with a defused *non-namespace-aware* expat parser.

    `xml.etree.ElementTree`'s default parser turns on expat's namespace
    processing unconditionally, which requires every prefix to be bound --
    so `<ns:b>` with no `xmlns:ns` declaration raises "unbound prefix"
    before omnist ever gets a chance to read it. omnist doesn't resolve
    namespaces at all (Sec8.3.8/docs/formats/xml.md: the prefix is always
    dropped, reported, and the local name kept), so requiring the prefix to
    be *bound* first is stricter than the format actually needs. Building
    the tree with a plain (non-namespace) expat parser instead means a
    prefixed tag simply becomes the literal string "ns:b", same as any
    other tag -- `_local` strips the prefix back off, and `_check_xml_drops`
    reports it as dropped either way, bound or not.

    The DTD/entity/external-reference protections are the same ones
    `defusedxml.ElementTree.DefusedXMLParser` installs -- reimplemented
    here (rather than subclassing it) only because `DefusedXMLParser`
    always requests a namespace-aware expat parser itself.
    """
    from xml.etree.ElementTree import TreeBuilder
    try:
        from defusedxml.common import (  # type: ignore[import-untyped]
            DTDForbidden,
            EntitiesForbidden,
            ExternalReferenceForbidden,
        )
    except ImportError as exc:
        raise ImportError("defusedxml is required: pip install defusedxml") from exc

    parser = expat.ParserCreate()  # no namespace_separator -> literal tag/attr names
    builder = TreeBuilder()
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data

    def _start_doctype(name: str, sysid: Any, pubid: Any, has_internal_subset: bool) -> None:
        raise DTDForbidden(name, sysid, pubid)

    # Entities and external references are declared inside a DTD's subset,
    # which expat only reaches once StartDoctypeDeclHandler has already
    # accepted the DOCTYPE -- since _start_doctype above unconditionally
    # raises instead, these three handlers can never actually fire. Kept
    # anyway (rather than omitted) as defense in depth: if that
    # unconditional raise is ever weakened, these still stand between a
    # DTD and the classic XXE/entity-expansion vectors it enables.
    def _entity_decl(name: str, is_parameter_entity: bool, value: Any, base: Any,
                     sysid: Any, pubid: Any, notation_name: Any) -> None:
        raise EntitiesForbidden(  # pragma: no cover
            name, value, base, sysid, pubid, notation_name)

    def _unparsed_entity_decl(name: str, base: Any, sysid: Any, pubid: Any,
                              notation_name: Any) -> None:
        raise EntitiesForbidden(  # pragma: no cover
            name, None, base, sysid, pubid, notation_name)

    def _external_entity_ref(context: Any, base: Any, sysid: Any, pubid: Any) -> None:
        raise ExternalReferenceForbidden(context, base, sysid, pubid)  # pragma: no cover

    parser.StartDoctypeDeclHandler = _start_doctype
    parser.EntityDeclHandler = _entity_decl
    parser.UnparsedEntityDeclHandler = _unparsed_entity_decl
    parser.ExternalEntityRefHandler = _external_entity_ref  # type: ignore[assignment]
    try:
        parser.Parse(text, True)
    except DTDForbidden as exc:
        # Reject on sight (xml.md): the DOCTYPE itself is the refusal, before
        # any element is read, so the path is the whole document.
        raise ParseError("a DOCTYPE declaration is outside the data-XML profile",
                         code="format.dtd-forbidden", path="$") from exc
    except (EntitiesForbidden, ExternalReferenceForbidden) as exc:  # pragma: no cover
        raise ParseError("an entity declaration is outside the data-XML profile",
                         code="format.entity-forbidden", path="$") from exc
    except expat.ExpatError as exc:
        if exc.code != _EXPAT_UNDEFINED_ENTITY:
            raise _xml_syntax_error(exc) from exc
        # An entity reference other than the five predefined ones. That is a
        # profile *refusal* (format.entity-forbidden), not malformed input --
        # but only once the document is known to be well-formed: expat
        # stopped at the reference, so the rest of the text has not been
        # checked. Re-check with every such reference neutralised to
        # same-length filler (positions stay identical); anything expat
        # rejects then is a genuine syntax error and is reported as one.
        try:
            _xml_well_formed(_XML_NONPREDEFINED_ENTITY_RE.sub(
                lambda m: "x" * len(m.group()), text))
        except expat.ExpatError as again:
            raise _xml_syntax_error(again) from again
        raise ParseError(
            "an entity reference other than the five predefined ones is "
            "outside the data-XML profile",
            code="format.entity-forbidden", path="$") from exc
    return builder.close()


def _xml_syntax_error(exc: Any) -> ParseError:
    """A well-formedness failure as ``parse.codec-syntax`` (E-11): expat's
    1-based line and 0-based column become the 1-based ``line:col``."""
    return ParseError(f"invalid XML: {exc}", code="parse.codec-syntax",
                      path=f"{exc.lineno}:{exc.offset + 1}")


def _xml_well_formed(text: str) -> None:
    """Raise ``expat.ExpatError`` unless ``text`` is well-formed XML (no
    handlers, so nothing is built and no DOCTYPE processing is refused)."""
    # Defence in depth: this parser installs no DTD, entity or external-reference
    # handlers, unlike the one in _xml_fromstring, whose comment there does not
    # extend here.  That is safe only because the call is unreachable with a DTD
    # today: the sole caller re-checks text the first pass already accepted up to
    # an undefined entity, and a DOCTYPE must precede the root element, so any
    # DOCTYPE was refused (format.dtd-forbidden) on that first pass.  If this
    # is ever reached with untrusted text some other way, add the same handlers.
    expat.ParserCreate().Parse(text, True)


# Any `&name;` other than the five predefined references and numeric
# character references.
_XML_NONPREDEFINED_ENTITY_RE = _re.compile(r"&(?!(?:lt|gt|amp|quot|apos);)(?!#)[^\s&;<>\"']+;")


def _need(module: str, how: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover
        raise ImportError(f"{module} is required: {how}") from exc
