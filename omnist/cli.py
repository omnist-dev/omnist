"""The ``omnist`` command-line interface.

A thin wrapper over the public :mod:`omnist` API -- see
``docs/design/cli-spec.md`` for the full command surface. Each command maps
to one or two calls into the library; this module adds no new behavior of
its own beyond argument parsing, file/stdio plumbing, and exit codes.
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from typing import Any, Optional, Sequence

from . import (
    Doc,
    DocumentError,
    ParseError,
    SchemaError,
    ValidationResult,
    WriteError,
    WriteReport,
    __version__,
    check_json,
    check_oml,
    check_toml,
    check_xml,
    check_yaml,
    doc,
    infer,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    to_osd,
    write_json,
    write_oml,
    write_toml,
    write_xml,
    write_yaml,
)

FMT_CHOICES = ["json", "yaml", "toml", "xml", "oml"]
RESULT_FORMAT_CHOICES = ["text", "json", "oml"]

_READERS = {
    "json": read_json,
    "yaml": read_yaml,
    "toml": read_toml,
    "xml": read_xml,
    "oml": read_oml,
}

# OML has no strict=/report= -- it's always exactly lossless, so it never
# needs them; the other four writers accept both (see report.finish_write).
_WRITERS = {
    "json": write_json,
    "yaml": write_yaml,
    "toml": write_toml,
    "xml": write_xml,
}

_CHECKERS = {
    "json": check_json,
    "yaml": check_yaml,
    "toml": check_toml,
    "xml": check_xml,
    "oml": check_oml,
}


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_output(path: Optional[str], text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if path is None or path == "-":
        sys.stdout.write(text)
    else:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)


def _encode_validation_result(result: ValidationResult, fmt: str) -> str:
    """Encode a ValidationResult as text/json/oml -- shared by every command
    whose result is an {ok, errors} shape (validate; later schema
    compatible-with/equivalent's boolean is a degenerate case of this)."""
    if fmt == "text":
        return str(result)
    payload: dict[str, Any] = {
        "ok": result.ok,
        "errors": [{"path": e.path, "message": e.message} for e in result.errors],
    }
    if fmt == "json":
        return _json.dumps(payload)
    if fmt == "oml":
        return doc(payload).to_oml()
    # unreachable: argparse restricts --result-format choices
    raise ValueError(f"unknown result format {fmt!r}")  # pragma: no cover


def _cmd_format(args: argparse.Namespace) -> int:
    node = read_oml(_read_input(args.input))
    _write_output(args.output, write_oml(node, indent=None if args.compact else 2))
    return 0


def _encode_write_report(rep: WriteReport, fmt: str) -> str:
    """Encode a WriteReport as text/json/oml -- shared by `convert --report`
    and `check`."""
    if fmt == "text":
        return str(rep)
    payload = [
        {"path": a.path, "code": a.code, "message": a.message, "severity": a.severity}
        for a in rep.adjustments
    ]
    if fmt == "json":
        return _json.dumps(payload)
    if fmt == "oml":
        return doc({"adjustments": payload}).to_oml()
    # unreachable: argparse restricts --result-format choices
    raise ValueError(f"unknown result format {fmt!r}")  # pragma: no cover


def _write_to_format(
    fmt: str, node: Any, *, strict: bool, report: Optional[WriteReport], compact: bool
) -> str:
    if fmt == "oml":
        return write_oml(node, indent=None if compact else 2)
    return _WRITERS[fmt](node, strict=strict, report=report)


def _cmd_convert(args: argparse.Namespace) -> int:
    if args.from_ == "oml" and args.to == "oml":
        print(
            "error: --from oml --to oml is not supported here; use `omnist format` instead",
            file=sys.stderr)
        return 2
    schema = parse_schema(_read_input(args.schema)) if args.schema else None
    node = _READERS[args.from_](_read_input(args.input), schema=schema)
    report = WriteReport() if args.report else None
    try:
        text = _write_to_format(
            args.to, node, strict=args.strict, report=report, compact=args.compact)
    except WriteError as exc:
        if exc.report is not None:
            # --strict refused a lossy write -- a definite "no," not a
            # usage/parse failure, so it's grouped with exit 1 (§1/§6 of
            # the CLI spec), not the generic exit 2 main() would give it.
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise  # a structural failure (e.g. multi-root XML) -- exit 2 via main()
    _write_output(args.output, text)
    if args.report:
        assert report is not None
        print(_encode_write_report(report, args.result_format), file=sys.stderr)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    node = _READERS[args.from_](_read_input(args.input))
    rep = _CHECKERS[args.to](node)
    print(_encode_write_report(rep, args.result_format))
    if args.strict:
        return 0 if not rep.adjustments else 1
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    node = _READERS[args.from_](_read_input(args.input))
    d = Doc(node)
    s = parse_schema(_read_input(args.schema))
    result = s.validate(d)
    print(_encode_validation_result(result, args.result_format))
    return 0 if result.ok else 1


def _cmd_infer(args: argparse.Namespace) -> int:
    reader = _READERS[args.from_]
    docs = [Doc(reader(_read_input(p))) for p in args.input]
    s = infer(docs)
    _write_output(args.output, to_osd(s, indent=None if args.compact else 4))
    return 0


def _cmd_schema_format(args: argparse.Namespace) -> int:
    s = parse_schema(_read_input(args.schema_file))
    _write_output(args.output, to_osd(s, indent=None if args.compact else 4))
    return 0


def _cmd_schema_normalize(args: argparse.Namespace) -> int:
    s = parse_schema(_read_input(args.schema_file))
    _write_output(args.output, to_osd(s.normalize(), indent=None if args.compact else 4))
    return 0


def _cmd_schema_prune(args: argparse.Namespace) -> int:
    s = parse_schema(_read_input(args.schema_file))
    _write_output(args.output, to_osd(s.prune(), indent=None if args.compact else 4))
    return 0


def _cmd_schema_is_empty(args: argparse.Namespace) -> int:
    s = parse_schema(_read_input(args.schema_file))
    result = s.is_empty()
    print(_encode_bool_result("empty", result, args.result_format))
    return 0 if result else 1


def _cmd_schema_extract(args: argparse.Namespace) -> int:
    s = parse_schema(_read_input(args.schema_file))
    labels = [lbl for lbl in args.keep.split(",") if lbl]
    try:
        extracted = s.extract(*labels)
    except SchemaError as exc:
        # A definite "no valid subschema" -- a schema-algebra result, not a
        # usage/parse failure, so exit 1 (like compatible-with's False), not
        # the generic exit 2 main() gives uncaught SchemaErrors.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _write_output(args.output, to_osd(extracted, indent=None if args.compact else 4))
    return 0


def _encode_bool_result(key: str, value: bool, fmt: str) -> str:
    """Encode a single boolean result -- shared by schema compatible-with
    and equivalent."""
    if fmt == "text":
        return "true" if value else "false"
    if fmt == "json":
        return _json.dumps({key: value})
    if fmt == "oml":
        return doc({key: value}).to_oml()
    # unreachable: argparse restricts --result-format choices
    raise ValueError(f"unknown result format {fmt!r}")  # pragma: no cover


def _cmd_schema_compatible_with(args: argparse.Namespace) -> int:
    a = parse_schema(_read_input(args.a))
    b = parse_schema(_read_input(args.b))
    result = a.compatible_with(b)
    print(_encode_bool_result("compatible", result, args.result_format))
    return 0 if result else 1


def _cmd_schema_equivalent(args: argparse.Namespace) -> int:
    a = parse_schema(_read_input(args.a))
    b = parse_schema(_read_input(args.b))
    result = a.equivalent(b)
    print(_encode_bool_result("equivalent", result, args.result_format))
    return 0 if result else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omnist",
        description="One canonical data model for JSON, YAML, TOML, XML, and OML "
                    "-- read, validate, and write any of them. "
                    "See docs/cli.md for the full command reference.")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    format_p = subparsers.add_parser(
        "format", help="canonicalize an OML document (the only format with no other tool for this)")
    format_p.add_argument("input", help="OML file, or - for stdin")
    format_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    format_p.add_argument("-o", "--output", help="output file; omit for stdout")
    format_p.set_defaults(func=_cmd_format)

    convert_p = subparsers.add_parser(
        "convert", help="convert a document between formats (one in, one out)")
    convert_p.add_argument("input", help="document file, or - for stdin")
    convert_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    convert_p.add_argument("--to", required=True, choices=FMT_CHOICES)
    convert_p.add_argument("--schema", help="OSD file for schema-directed deserialization")
    convert_p.add_argument(
        "--strict", action="store_true",
        help="refuse to write at all if anything would need adjusting (exit 1)")
    convert_p.add_argument(
        "--report", action="store_true",
        help="print to stderr what got adjusted, alongside writing normally")
    convert_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text",
        help="encoding for --report's output; no effect without --report")
    convert_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output when --to oml; no effect otherwise")
    convert_p.add_argument("-o", "--output", help="output file; omit for stdout")
    convert_p.set_defaults(func=_cmd_convert)

    check_p = subparsers.add_parser(
        "check", help="report what writing as --to would adjust, without ever writing")
    check_p.add_argument("input", help="document file, or - for stdin")
    check_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    check_p.add_argument("--to", required=True, choices=FMT_CHOICES)
    check_p.add_argument(
        "--strict", action="store_true",
        help="exit 1 if anything would need adjusting, 0 otherwise (default: always 0)")
    check_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    check_p.set_defaults(func=_cmd_check)

    validate_p = subparsers.add_parser(
        "validate", help="check a document against a schema (no schema-directed upgrading)")
    validate_p.add_argument("input", help="document file, or - for stdin")
    validate_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    validate_p.add_argument("--schema", required=True, help="OSD schema file")
    validate_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    validate_p.set_defaults(func=_cmd_validate)

    infer_p = subparsers.add_parser(
        "infer", help="draft a schema from example documents (all the same format)")
    infer_p.add_argument("input", nargs="+", help="document files, same format")
    infer_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    infer_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented OSD output instead of pretty-printed")
    infer_p.add_argument("-o", "--output", help="output file; omit for stdout")
    infer_p.set_defaults(func=_cmd_infer)

    schema_p = subparsers.add_parser("schema", help="operate on a Schema (OSD)")
    schema_sub = schema_p.add_subparsers(dest="schema_command", required=True)

    schema_format_p = schema_sub.add_parser(
        "format", help="canonicalize an OSD schema file (safe reformat only, no structural change)")
    schema_format_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_format_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_format_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_format_p.set_defaults(func=_cmd_schema_format)

    schema_normalize_p = schema_sub.add_parser(
        "normalize",
        help="compute the canonical minimal equivalent schema "
             "(fewest records via partition refinement)")
    schema_normalize_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_normalize_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_normalize_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_normalize_p.set_defaults(func=_cmd_schema_normalize)

    schema_prune_p = schema_sub.add_parser(
        "prune",
        help="remove everything that can never match: unreachable records, "
             "never-emittable fields, optional fields with unsatisfiable types")
    schema_prune_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_prune_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_prune_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_prune_p.set_defaults(func=_cmd_schema_prune)

    schema_is_empty_p = schema_sub.add_parser(
        "is-empty",
        help="does the schema accept no documents at all "
             "(unsatisfiable root, e.g. a mandatory ref cycle)")
    schema_is_empty_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_is_empty_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_is_empty_p.set_defaults(func=_cmd_schema_is_empty)

    schema_extract_p = schema_sub.add_parser(
        "extract",
        help="the minimal subschema recognizing only documents built from --keep labels")
    schema_extract_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_extract_p.add_argument(
        "--keep", required=True,
        help="comma-separated list of labels to keep, e.g. label1,label2,...")
    schema_extract_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_extract_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_extract_p.set_defaults(func=_cmd_schema_extract)

    schema_compat_p = schema_sub.add_parser(
        "compatible-with", help="is every document `a` accepts also accepted by `b`")
    schema_compat_p.add_argument("a", help="OSD file, or - for stdin")
    schema_compat_p.add_argument("b", help="OSD file")
    schema_compat_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_compat_p.set_defaults(func=_cmd_schema_compatible_with)

    schema_equiv_p = schema_sub.add_parser(
        "equivalent", help="do `a` and `b` accept exactly the same documents")
    schema_equiv_p.add_argument("a", help="OSD file, or - for stdin")
    schema_equiv_p.add_argument("b", help="OSD file")
    schema_equiv_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_equiv_p.set_defaults(func=_cmd_schema_equivalent)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)  # type: ignore[no-any-return]
    except (ParseError, SchemaError, WriteError, DocumentError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


# module entry point, exercised only by direct execution
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
