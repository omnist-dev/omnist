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
import json as _json
import math as _math
import re as _re
from typing import TYPE_CHECKING, Any, Optional

from .document import _MAX_DEPTH, _MAX_NODES, _grouped, build_node
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
        raise WriteError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")


def _leaves(node: Any, path: str = "$", depth: int = 0) -> Any:
    """Yield ``(path, value)`` for every scalar leaf in a node."""
    if isinstance(node, list):
        _check_write_depth(depth)
        counts: dict[str, int] = {}
        for label, child in node:
            i = counts.get(label, 0)
            counts[label] = i + 1
            p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
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
    finished: set = set()
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


def _check_json_text_depth(text: str) -> None:
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
            if depth > _MAX_DEPTH:
                raise ParseError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})")
        elif ch in "}]":
            depth -= 1


# --------------------------------------------------------------- JSON
def read_json(text: str, *, schema: Optional["Schema"] = None) -> Any:
    _check_json_text_depth(text)
    try:
        node = build_node(_json.loads(text))
    except _json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}", code="parse.syntax") from exc
    except ValueError as exc:
        # json.loads converts integer literals to `int` while parsing, so an
        # over-digit-limit literal trips CPython's int-string-conversion
        # guard here -- before build_node ever sees a value -- as a bare
        # ValueError, not a JSONDecodeError.  Translate it like any other
        # parse-time failure.
        raise ParseError(f"invalid JSON: {exc}", code="parse.syntax") from exc
    return _materialize(node, schema)


def write_json(node: Any, *, indent: Optional[int] = None, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    rep = _scan_json(node)
    prepared = node if strict else _prepare_json(node)
    text = _json.dumps(_grouped(prepared), indent=indent, ensure_ascii=False, default=_iso)
    return finish_write(text, rep, strict=strict, report=report)


def check_json(node: Any) -> WriteReport:
    """Report what writing JSON would adjust, without producing output."""
    return _scan_json(node)


def _scan_json(node: Any) -> WriteReport:
    rep = WriteReport()
    for path, v in _leaves(node):
        if isinstance(v, (_dt.date, _dt.time)):
            rep.add(path, "temporal.stringified",
                    "temporal value written as an ISO-8601 string", "warning")
        elif isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
            rep.add(path, "float.special", f"{v} is not valid JSON; wrote null", "error")
    _check_interleaving(node, rep)
    return rep


def _prepare_json(node: Any, depth: int = 0) -> Any:
    """Lenient-mode substitution: a NaN/Infinity leaf becomes ``null`` so the
    written text is always valid JSON (mirrors XML's illegal-char -> U+FFFD
    substitution). ``strict=True`` skips this and refuses via WriteError
    instead, so it never sees the substituted value."""
    if isinstance(node, list):
        _check_write_depth(depth)
        return [(label, _prepare_json(child, depth + 1)) for label, child in node]
    if isinstance(node, float) and (_math.isnan(node) or _math.isinf(node)):
        return None
    return node


def _iso(o: Any) -> str:
    if isinstance(o, (_dt.date, _dt.time)):
        return o.isoformat()
    raise TypeError(f"cannot serialize {type(o).__name__}")


# --------------------------------------------------------------- YAML
def read_yaml(text: str, *, schema: Optional["Schema"] = None) -> Any:
    yaml = _need("yaml", "pip install pyyaml")
    try:
        node = build_node(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML: {exc}", code="parse.syntax") from exc
    except ValueError as exc:
        # Same int-string-conversion guard as read_json (see its comment):
        # PyYAML converts an integer scalar to `int` while loading.
        raise ParseError(f"invalid YAML: {exc}", code="parse.syntax") from exc
    except RecursionError as exc:
        # #307: unlike JSON's bracket grammar, YAML nesting (indentation,
        # flow collections, anchors) isn't cheap to bound from raw text
        # without reimplementing the grammar -- this is a safety net that
        # converts an uncaught crash into the same clean error a depth
        # violation always raises, rather than precise prevention.
        raise ParseError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})") from exc
    return _materialize(node, schema)


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
    rep = WriteReport()
    for path, v in _leaves(node):
        if isinstance(v, _dt.time):       # YAML carries date/datetime natively, not time
            rep.add(path, "temporal.stringified",
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
    counts: dict[str, int] = {}
    for label, child in node:
        i = counts.get(label, 0)
        counts[label] = i + 1
        p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
        if isinstance(label, str) and "\x85" in label:
            rep.add(p, "string.line-break-char",
                    "label contains U+0085 (NEL); written double-quoted to "
                    "round-trip correctly", "warning")
        if isinstance(child, str) and "\x85" in child:
            rep.add(p, "string.line-break-char",
                    "value contains U+0085 (NEL); written double-quoted to "
                    "round-trip correctly", "warning")
        _scan_yaml_labels(child, p, rep, depth + 1)


def _prepare_yaml(node: Any, depth: int = 0) -> Any:
    if isinstance(node, list):
        _check_write_depth(depth)
        return [(label, _prepare_yaml(c, depth + 1)) for label, c in node]
    if isinstance(node, _dt.time):
        return node.isoformat()
    return node


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
        dumper = type("_OmnistYamlDumper", (yaml.SafeDumper,), {})
        dumper.add_representer(str, _yaml_str_representer)  # type: ignore[attr-defined]
        _YAML_DUMPER_CACHE[yaml] = dumper
    return dumper


# --------------------------------------------------------------- TOML
def read_toml(text: str, *, schema: Optional["Schema"] = None) -> Any:
    import tomllib
    try:
        node = build_node(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ParseError(f"invalid TOML: {exc}", code="parse.syntax") from exc
    except ValueError as exc:
        # Same int-string-conversion guard as read_json (see its comment):
        # tomllib converts an integer literal to `int` while loading.
        raise ParseError(f"invalid TOML: {exc}", code="parse.syntax") from exc
    except RecursionError as exc:
        # #307: same safety net as read_yaml -- TOML nesting (inline
        # tables/arrays, dotted keys) isn't cheap to bound from raw text
        # without reimplementing the grammar.
        raise ParseError(f"nesting exceeds the maximum depth ({_MAX_DEPTH})") from exc
    return _materialize(node, schema)


def write_toml(node: Any, *, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    tomli_w = _need("tomli_w", "pip install tomli_w")
    rep = WriteReport()
    stripped = _strip_nulls(node, "$", rep)        # TOML has no null
    _check_interleaving(node, rep)
    grouped = _grouped(stripped)
    if not isinstance(grouped, dict):
        raise WriteError("TOML needs a top-level table (the root must be an object)")
    text = tomli_w.dumps(grouped)
    return finish_write(text, rep, strict=strict, report=report)


def check_toml(node: Any) -> WriteReport:
    rep = WriteReport()
    _strip_nulls(node, "$", rep)
    _check_interleaving(node, rep)
    return rep


def _strip_nulls(node: Any, path: str, rep: WriteReport, depth: int = 0) -> Any:
    """Drop edges whose value is null (TOML can't hold null), recording each."""
    if not isinstance(node, list):
        return node
    _check_write_depth(depth)
    out: list[tuple[str, Any]] = []
    counts: dict[str, int] = {}
    for label, child in node:
        i = counts.get(label, 0)
        counts[label] = i + 1
        p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
        if child is None:
            rep.add(p, "null.omitted", "null value dropped (TOML has no null)", "warning")
            continue
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
            report: Optional[WriteReport] = None) -> Any:
    try:
        root = _xml_fromstring(text)
    except ImportError:
        raise  # missing defusedxml -- a setup problem, not a syntax one
    except Exception as exc:
        raise ParseError(f"invalid XML: {exc}", code="parse.syntax") from exc
    root_local = _local(root.tag)
    # `epath` is the proper full dotted Document path (Sec8.4 convention),
    # used only for format.attribute-dropped/format.namespace-dropped --
    # kept separate from `path` below, which is the pre-existing (shallower)
    # scheme mixed-content errors already use and report on.
    root_epath = f"$.{root_local}"
    _check_xml_drops(root, root_epath, report)
    node = [(root_local, _xml_to_node(root, "$", 0, [0], report, root_epath))]
    if schema is not None:
        # #288: recover boolean/integer/number from XML's untyped text
        # before the shared materialize() sees it. This is XML-specific,
        # not a materialize() capability -- materialize() itself must keep
        # rejecting a string that merely looks numeric (a string is a
        # deliberate choice in JSON/YAML/TOML/OML, never an untyped
        # placeholder the way it always is in XML).
        node = _xml_pretype(node, schema, schema.root)
    return _materialize(node, schema)


def _xml_pretype(node: Any, schema: "Schema", t: Any) -> Any:
    from .schema import AnyType, Scalar
    d = schema.resolve(t)
    if isinstance(d, AnyType):
        return node
    if isinstance(d, Scalar):
        return _xml_pretype_scalar(node, d)
    if not isinstance(node, list):
        return node
    out = []
    for label, child in node:
        f = d.field(label)
        out.append((label, _xml_pretype(child, schema, f.type) if f else child))
    return out


def _xml_pretype_scalar(value: Any, s: "Scalar") -> Any:
    # value is always the str _xml_to_node produced -- _xml_pretype is only
    # ever called on a freshly-built XML node, never a value from elsewhere.
    if s.name == "boolean" and value in ("true", "false"):
        return value == "true"
    if s.name == "integer" and _XML_INT_RE.fullmatch(value):
        return int(value)
    if s.name == "number" and _XML_NUM_RE.fullmatch(value):
        return float(value)
    return value


def _xml_to_node(elem: Any, path: str, depth: int, budget: list[int],
                 report: Optional[WriteReport] = None, epath: Optional[str] = None) -> Any:
    # budget is a shared running node count across the whole call tree, the
    # same mechanism build_node uses (document.py) -- unlike build_node's
    # readers, XML's ElementTree parse has no aliasing mechanism to create a
    # DAG (defusedxml also blocks DTDs, closing the classic XML entity-
    # expansion vector upstream), so there's no _MAX_DEPTH-bypassing
    # amplification vector here. This guard exists for the same size
    # ceiling every other reader now has, not because an exploit is known.
    budget[0] += 1
    if budget[0] > _MAX_NODES:
        raise DocumentError(
            f"{path}: too many nodes materialized (over {_MAX_NODES})")
    if depth > _MAX_DEPTH:
        raise DocumentError(f"{path}: nesting exceeds the maximum depth ({_MAX_DEPTH})")
    children = list(elem)
    if children:
        if elem.text and elem.text.strip():
            raise ParseError(
                f"{path}: mixed content (text alongside child elements) is "
                "outside the data-XML profile", code="parse.syntax", path=path)
        for c in children:
            if c.tail and c.tail.strip():
                p = f"{path}.{_local(c.tag)}"
                raise ParseError(
                    f"{p}: mixed content (text alongside "
                    "child elements) is outside the data-XML profile",
                    code="parse.syntax", path=p)
        out = []
        for c in children:
            c_local = _local(c.tag)
            p = f"{path}.{c_local}"
            cepath = f"{epath}.{c_local}" if epath is not None else None
            _check_xml_drops(c, cepath, report)
            out.append((c_local, _xml_to_node(c, p, depth + 1, budget, report, cepath)))
        return out
    return elem.text or ""


def write_xml(node: Any, *, strict: bool = False,
              report: Optional[WriteReport] = None) -> str:
    if not (isinstance(node, list) and len(node) == 1):
        raise WriteError(
            "XML needs exactly one document element; the root node must have a "
            "single top-level edge (a single-rooted Document)")
    rep = check_xml(node)
    import xml.etree.ElementTree as ET
    (tag, content), = node
    el = ET.Element(_xml_name(tag))
    _node_to_xml(content, el)
    _indent(el)
    text = ET.tostring(el, encoding="unicode")
    return finish_write(text, rep, strict=strict, report=report)


def check_xml(node: Any) -> WriteReport:
    rep = WriteReport()
    _scan_xml(node, "$", rep)
    return rep


def _scan_xml(node: Any, path: str, rep: WriteReport, depth: int = 0) -> None:
    if isinstance(node, list):
        _check_write_depth(depth)
        if not node:
            rep.add(path, "shape.empty_ambiguous",
                    "empty internal node (no edges) written as <tag /> and "
                    "reads back as the empty-string leaf '', not []",
                    "warning")
            return
        counts: dict[str, int] = {}
        for label, child in node:
            i = counts.get(label, 0)
            counts[label] = i + 1
            p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
            if not _XML_NAME.match(label):
                rep.add(p, "key.sanitized",
                        f"label {label!r} isn't a valid XML name; written sanitized",
                        "warning")
            _scan_xml(child, p, rep, depth + 1)
        return
    v = node
    if v is None:
        rep.add(path, "null.omitted", "null written as an empty element", "warning")
    elif isinstance(v, (_dt.date, _dt.time)):
        rep.add(path, "temporal.stringified",
                "temporal value written as text (reads back as a string)", "warning")
    elif isinstance(v, (bool, int, float)):
        # #288: read_xml no longer infers scalar kind from text shape, so a
        # non-string scalar written to XML (XML has no native typed
        # literals -- everything is text) now reads back as a string, not
        # its original type. Previously silent (the old shape-based
        # coercion happened to undo this on read); now reported like every
        # other type-losing write.
        rep.add(path, "value.stringified",
                "non-string scalar written as text (reads back as a string)", "warning")
    if isinstance(v, str):
        if _XML_ILLEGAL_CHAR.search(v):
            rep.add(path, "string.illegal_xml_char",
                    "string contains a character XML 1.0 cannot represent "
                    "(e.g. a C0 control other than tab/LF/CR); it is replaced "
                    "with U+FFFD on write so the output stays well-formed",
                    "error")
        if "\r" in v:
            rep.add(path, "string.cr_normalized",
                    "string contains a carriage return ('\\r'); XML mandates "
                    "line-ending normalization on parse, so '\\r' (and "
                    "'\\r\\n') read back as '\\n'",
                    "warning")


def _node_to_xml(content: Any, parent: Any) -> None:
    import xml.etree.ElementTree as ET
    if isinstance(content, list):
        for label, child in content:
            sub = ET.SubElement(parent, _xml_name(label))
            _node_to_xml(child, sub)
    else:
        parent.text = _xml_sanitize(_xml_text(content))


def _xml_name(name: str) -> str:
    if _XML_NAME.match(name):
        return name
    safe = _re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    if not safe or not _XML_NAME.match(safe):
        safe = "_" + safe
    return safe


def _xml_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    return str(v)


def _xml_sanitize(text: str) -> str:
    """Replace characters XML 1.0 cannot represent (see ``string.illegal_xml_char``)
    with U+FFFD so write_xml's output is always well-formed XML.  CR is left
    as-is -- it's legal XML and only normalizes to LF on parse, which is
    reported separately as ``string.cr_normalized``."""
    return _XML_ILLEGAL_CHAR.sub(chr(0xFFFD), text)


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
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
    import xml.parsers.expat as expat
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

    def _entity_decl(name: str, is_parameter_entity: bool, value: Any, base: Any,
                     sysid: Any, pubid: Any, notation_name: Any) -> None:
        raise EntitiesForbidden(name, value, base, sysid, pubid, notation_name)

    def _unparsed_entity_decl(name: str, base: Any, sysid: Any, pubid: Any,
                              notation_name: Any) -> None:
        raise EntitiesForbidden(name, None, base, sysid, pubid, notation_name)

    def _external_entity_ref(context: Any, base: Any, sysid: Any, pubid: Any) -> None:
        raise ExternalReferenceForbidden(context, base, sysid, pubid)

    parser.StartDoctypeDeclHandler = _start_doctype
    parser.EntityDeclHandler = _entity_decl
    parser.UnparsedEntityDeclHandler = _unparsed_entity_decl
    parser.ExternalEntityRefHandler = _external_entity_ref
    parser.Parse(text, True)
    return builder.close()


def _need(module: str, how: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover
        raise ImportError(f"{module} is required: {how}") from exc
