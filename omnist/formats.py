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
import warnings
from typing import TYPE_CHECKING, Any, Optional

from .document import _MAX_DEPTH, _grouped, build_node
from .errors import DocumentError, ParseError, UnsafeXMLWarning, WriteError
from .report import WriteReport, finish_write

if TYPE_CHECKING:
    from .schema import Schema


def _materialize(node: Any, schema: Optional["Schema"]) -> Any:
    """Apply schema-directed deserialization if a schema was given."""
    if schema is None:
        return node
    from .deserialize import materialize
    return materialize(node, schema)


def _leaves(node: Any, path: str = "$") -> Any:
    """Yield ``(path, value)`` for every scalar leaf in a node."""
    if isinstance(node, list):
        counts: dict[str, int] = {}
        for label, child in node:
            i = counts.get(label, 0)
            counts[label] = i + 1
            p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
            yield from _leaves(child, p)
    else:
        yield path, node


# --------------------------------------------------------------- JSON
def read_json(text: str, *, schema: Optional["Schema"] = None) -> Any:
    try:
        node = build_node(_json.loads(text))
    except _json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc
    except ValueError as exc:
        # json.loads converts integer literals to `int` while parsing, so an
        # over-digit-limit literal trips CPython's int-string-conversion
        # guard here -- before build_node ever sees a value -- as a bare
        # ValueError, not a JSONDecodeError.  Translate it like any other
        # parse-time failure.
        raise ParseError(f"invalid JSON: {exc}") from exc
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
    return rep


def _prepare_json(node: Any) -> Any:
    """Lenient-mode substitution: a NaN/Infinity leaf becomes ``null`` so the
    written text is always valid JSON (mirrors XML's illegal-char -> U+FFFD
    substitution). ``strict=True`` skips this and refuses via WriteError
    instead, so it never sees the substituted value."""
    if isinstance(node, list):
        return [(label, _prepare_json(child)) for label, child in node]
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
        raise ParseError(f"invalid YAML: {exc}") from exc
    except ValueError as exc:
        # Same int-string-conversion guard as read_json (see its comment):
        # PyYAML converts an integer scalar to `int` while loading.
        raise ParseError(f"invalid YAML: {exc}") from exc
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
    return rep


def _scan_yaml_labels(node: Any, path: str, rep: WriteReport) -> None:
    """PyYAML's emitter/parser treat U+0085 (NEL) as a line-break character and
    normalize it away under the default (unquoted/single-quoted) scalar styles,
    so a label containing it would silently come back as a space.  We force
    double-quoted style for any such scalar (see ``_yaml_str_representer``),
    which round-trips correctly, but still flag it here for visibility."""
    if not isinstance(node, list):
        return
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
        _scan_yaml_labels(child, p, rep)


def _prepare_yaml(node: Any) -> Any:
    if isinstance(node, list):
        return [(label, _prepare_yaml(c)) for label, c in node]
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
        raise ParseError(f"invalid TOML: {exc}") from exc
    except ValueError as exc:
        # Same int-string-conversion guard as read_json (see its comment):
        # tomllib converts an integer literal to `int` while loading.
        raise ParseError(f"invalid TOML: {exc}") from exc
    return _materialize(node, schema)


def write_toml(node: Any, *, strict: bool = False,
               report: Optional[WriteReport] = None) -> str:
    tomli_w = _need("tomli_w", "pip install tomli_w")
    rep = WriteReport()
    stripped = _strip_nulls(node, "$", rep)        # TOML has no null
    grouped = _grouped(stripped)
    if not isinstance(grouped, dict):
        raise WriteError("TOML needs a top-level table (the root must be an object)")
    text = tomli_w.dumps(grouped)
    return finish_write(text, rep, strict=strict, report=report)


def check_toml(node: Any) -> WriteReport:
    rep = WriteReport()
    _strip_nulls(node, "$", rep)
    return rep


def _strip_nulls(node: Any, path: str, rep: WriteReport) -> Any:
    """Drop edges whose value is null (TOML can't hold null), recording each."""
    if not isinstance(node, list):
        return node
    out: list[tuple[str, Any]] = []
    counts: dict[str, int] = {}
    for label, child in node:
        i = counts.get(label, 0)
        counts[label] = i + 1
        p = f"{path}.{label}" if i == 0 else f"{path}.{label}[{i}]"
        if child is None:
            rep.add(p, "null.omitted", "null value dropped (TOML has no null)", "warning")
            continue
        out.append((label, _strip_nulls(child, p, rep)))
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


def read_xml(text: str, *, schema: Optional["Schema"] = None) -> Any:
    ET = _xml_parser()
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        raise ParseError(f"invalid XML: {exc}") from exc
    node = [(_local(root.tag), _xml_to_node(root, "$", 0))]
    return _materialize(node, schema)


def _xml_to_node(elem: Any, path: str, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        raise DocumentError(f"{path}: nesting exceeds the maximum depth ({_MAX_DEPTH})")
    children = list(elem)
    if children:
        if elem.text and elem.text.strip():
            raise ParseError(
                f"{path}: mixed content (text alongside child elements) is "
                "outside the data-XML profile")
        for c in children:
            if c.tail and c.tail.strip():
                raise ParseError(
                    f"{path}.{_local(c.tag)}: mixed content (text alongside "
                    "child elements) is outside the data-XML profile")
        return [(_local(c.tag), _xml_to_node(c, f"{path}.{_local(c.tag)}", depth + 1))
                for c in children]
    return _coerce(elem.text or "")


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


def _scan_xml(node: Any, path: str, rep: WriteReport) -> None:
    if isinstance(node, list):
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
            _scan_xml(child, p, rep)
        return
    v = node
    if v is None:
        rep.add(path, "null.omitted", "null written as an empty element", "warning")
    elif isinstance(v, (_dt.date, _dt.time)):
        rep.add(path, "temporal.stringified",
                "temporal value written as text (reads back as a string)", "warning")
    elif isinstance(v, str) and not isinstance(_coerce(v), str):
        rep.add(path, "string.ambiguous",
                f"string {v!r} looks like another type and reads back as that type",
                "warning")
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


def _coerce(text: str) -> Any:
    if text == "":
        return ""
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


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
        return ET
    except ImportError:
        warnings.warn(
            "defusedxml is not installed; read_xml() uses the standard library's "
            "XML parser, which is vulnerable to entity-expansion / XXE attacks on "
            "untrusted input. pip install defusedxml to fix this.",
            UnsafeXMLWarning, stacklevel=3)
        import xml.etree.ElementTree as ET
        return ET


def _need(module: str, how: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover
        raise ImportError(f"{module} is required: {how}") from exc
