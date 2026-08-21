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
    Error,
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
    infer_with_report,
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
    _write_output(
        args.output,
        write_oml(node, indent=None if args.compact else 2, arrays=args.arrays))
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
    fmt: str, node: Any, *, strict: bool, report: Optional[WriteReport], compact: bool,
    arrays: bool = False,
) -> str:
    if fmt == "oml":
        return write_oml(node, indent=None if compact else 2, arrays=arrays)
    return _WRITERS[fmt](node, strict=strict, report=report)


def _cmd_convert(args: argparse.Namespace) -> int:
    if args.from_ == "oml" and args.to == "oml" and not args.schema:
        # With no schema this is a pure no-op (`format` is the dedicated
        # command for that). With a schema it's a real operation --
        # schema-directed materialization -- so only refuse the no-op case.
        return _fail(
            args,
            "--from oml --to oml is not supported here; use `omnist format` instead",
            2)
    schema = parse_schema(_read_input(args.schema)) if args.schema else None
    node = _READERS[args.from_](_read_input(args.input), schema=schema)
    report = WriteReport() if args.report else None
    try:
        text = _write_to_format(
            args.to, node, strict=args.strict, report=report, compact=args.compact,
            arrays=args.arrays)
    except WriteError as exc:
        if exc.report is not None:
            # --strict refused a lossy write -- a definite "no," not a
            # usage/parse failure, so it's grouped with exit 1 (§1/§6 of
            # the CLI spec), not the generic exit 2 main() would give it.
            return _fail(args, exc, 1)
        raise  # a structural failure (e.g. multi-root XML) -- exit 2 via main()
    _write_output(args.output, text)
    if args.report:
        assert report is not None
        print(_encode_write_report(report, args.result_format), file=sys.stderr)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    node = _READERS[args.from_](_read_input(args.input))
    rep = _CHECKERS[args.to](node)
    fmt = "json" if getattr(args, "json", False) else args.result_format
    print(_encode_write_report(rep, fmt))
    if args.strict:
        return 0 if not rep.adjustments else 1
    return 0


def _json_validate_ok() -> str:
    """The --json success payload: {"ok": true}, nothing else."""
    return _json.dumps({"ok": True})


def _json_validate_errors(message: str, errors: list[Error]) -> str:
    """The --json failure payload -- shared by conformance failures (errors
    from a ValidationResult) and format-syntax failures (errors always
    empty, message carries the parse error), per issue #182."""
    payload = {
        "ok": False,
        "message": message,
        "errors": [{"path": e.path, "code": e.code, "message": e.message} for e in errors],
    }
    return _json.dumps(payload)


def _schema_error_as_errors(exc: SchemaError) -> "list[Error]":
    """SchemaError always represents exactly one problem (OSD parsing stops
    at the first error), so a single-item list, not a collected-errors
    list like ParseError's -- empty if the raiser didn't set a code (issue
    #301: still true for any SchemaError site outside osd.py's own
    lexical/well-formedness raises, which is most of schema.py's)."""
    if exc.code is None:
        return []
    return [Error(exc.path or "", str(exc), exc.code)]


def _json_error(exc: Exception) -> str:
    """The uniform --json failure payload for any data/parse/IO error:
    {"ok": false, "message": str(exc), "errors": [...]} -- errors come from
    ParseError.errors or a structured SchemaError's code/path when
    applicable, else []. Single source of the error shape (delegates to
    _json_validate_errors)."""
    if isinstance(exc, ParseError):
        errors = exc.errors
    elif isinstance(exc, SchemaError):
        errors = _schema_error_as_errors(exc)
    else:
        errors = []
    return _json_validate_errors(str(exc), errors)


def _fail(args: argparse.Namespace, exc: "str | Exception", code: int) -> int:
    """Uniform in-handler error emission. Under --json, print a machine-readable
    error object to stdout; otherwise the free-text `error: ...` to stderr.
    Exit `code` is returned unchanged either way. `exc` may be an exception or
    a bare message string (for the convert oml/oml usage guard)."""
    if getattr(args, "json", False):
        if isinstance(exc, str):
            print(_json_validate_errors(exc, []))
        else:
            print(_json_error(exc))
    else:
        msg = exc if isinstance(exc, str) else str(exc)
        print(f"error: {msg}", file=sys.stderr)
    return code


def _cmd_validate(args: argparse.Namespace) -> int:
    if args.json:
        try:
            node = _READERS[args.from_](_read_input(args.input))
            d = Doc(node)
            s = parse_schema(_read_input(args.schema))
        except (ParseError, SchemaError, DocumentError, OSError) as exc:
            if isinstance(exc, ParseError):
                errors = exc.errors
            elif isinstance(exc, SchemaError):
                errors = _schema_error_as_errors(exc)
            else:
                errors = []
            print(_json_validate_errors(str(exc), errors))
            return 2
        result = s.validate(d)
        if result.ok:
            print(_json_validate_ok())
            return 0
        print(_json_validate_errors(str(result), result.errors))
        return 1
    node = _READERS[args.from_](_read_input(args.input))
    d = Doc(node)
    s = parse_schema(_read_input(args.schema))
    result = s.validate(d)
    print(_encode_validation_result(result, args.result_format))
    return 0 if result.ok else 1


_ARRAYS_OSD_ONLY_MSG = "--arrays applies only to OML output (format, convert --to oml)"


def _cmd_infer(args: argparse.Namespace) -> int:
    if args.arrays:
        return _fail(args, _ARRAYS_OSD_ONLY_MSG, 2)
    reader = _READERS[args.from_]
    docs = [Doc(reader(_read_input(p))) for p in args.input]
    if args.allow_any:
        s, fallbacks = infer_with_report(docs, allow_any=True)
        if fallbacks:
            if getattr(args, "json", False):
                payload = {"opened": [{"location": fb.location, "reason": fb.reason}
                                      for fb in fallbacks]}
                print(_json.dumps(payload), file=sys.stderr)
            else:
                print(f"opened {len(fallbacks)} field(s) as `any`:", file=sys.stderr)
                for fb in fallbacks:
                    print(f"  {fb.location} — {fb.reason}", file=sys.stderr)
    else:
        s = infer(docs)
    _write_output(args.output, to_osd(s, indent=None if args.compact else 4))
    return 0


def _cmd_schema_format(args: argparse.Namespace) -> int:
    if args.arrays:
        return _fail(args, _ARRAYS_OSD_ONLY_MSG, 2)
    s = parse_schema(_read_input(args.schema_file))
    _write_output(args.output, to_osd(s, indent=None if args.compact else 4))
    return 0


def _cmd_schema_normalize(args: argparse.Namespace) -> int:
    if args.arrays:
        return _fail(args, _ARRAYS_OSD_ONLY_MSG, 2)
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
    fmt = "json" if getattr(args, "json", False) else args.result_format
    print(_encode_bool_result("empty", result, fmt))
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
        return _fail(args, exc, 1)
    _write_output(args.output, to_osd(extracted, indent=None if args.compact else 4))
    return 0


def _cmd_schema_lint(args: argparse.Namespace) -> int:
    from . import lint
    s = parse_schema(_read_input(args.schema_file))
    order = {"info": 0, "warning": 1}
    threshold = order[args.severity]
    findings = [f for f in lint(s) if order.get(f.severity, 1) >= threshold]
    has_warning = any(f.severity == "warning" for f in findings)
    if args.json:
        payload = {
            "ok": not has_warning,
            "findings": [
                {"code": f.code, "severity": f.severity,
                 "location": f.location, "message": f.message}
                for f in findings
            ],
        }
        print(_json.dumps(payload))
    else:
        if not findings:
            print("no findings")
        else:
            for f in findings:
                print(f"{f.severity}: {f.code}: {f.location}: {f.message}")
    return 1 if has_warning else 0


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
    fmt = "json" if getattr(args, "json", False) else args.result_format
    print(_encode_bool_result("compatible", result, fmt))
    return 0 if result else 1


def _cmd_schema_equivalent(args: argparse.Namespace) -> int:
    a = parse_schema(_read_input(args.a))
    b = parse_schema(_read_input(args.b))
    result = a.equivalent(b)
    fmt = "json" if getattr(args, "json", False) else args.result_format
    print(_encode_bool_result("equivalent", result, fmt))
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

    # Shared parent giving every subcommand a uniform --json "machine mode".
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument(
        "--json", action="store_true",
        help="machine-readable JSON on stdout: errors as {ok:false,message,errors}; "
             "results as JSON where the command has one; exit codes unchanged")

    format_p = subparsers.add_parser(
        "format", parents=[json_parent],
        help="canonicalize an OML document (the only format with no other tool for this)")
    format_p.add_argument("input", help="OML file, or - for stdin")
    format_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    format_p.add_argument(
        "--arrays", action="store_true",
        help="collapse runs of >=2 consecutive same-label edges into [...] array syntax")
    format_p.add_argument("-o", "--output", help="output file; omit for stdout")
    format_p.set_defaults(func=_cmd_format)

    convert_p = subparsers.add_parser(
        "convert", parents=[json_parent],
        help="convert a document between formats (one in, one out)")
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
    convert_p.add_argument(
        "--arrays", action="store_true",
        help="collapse runs of >=2 consecutive same-label edges into [...] array syntax "
             "when --to oml; no effect otherwise")
    convert_p.add_argument("-o", "--output", help="output file; omit for stdout")
    convert_p.set_defaults(func=_cmd_convert)

    check_p = subparsers.add_parser(
        "check", parents=[json_parent],
        help="report what writing as --to would adjust, without ever writing")
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
        "validate", parents=[json_parent],
        help="check a document against a schema (no schema-directed upgrading)")
    validate_p.add_argument("input", help="document file, or - for stdin")
    validate_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    validate_p.add_argument("--schema", required=True, help="OSD schema file")
    validate_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    validate_p.set_defaults(func=_cmd_validate)

    infer_p = subparsers.add_parser(
        "infer", parents=[json_parent],
        help="draft a schema from example documents (all the same format)")
    infer_p.add_argument("input", nargs="+", help="document files, same format")
    infer_p.add_argument("--from", dest="from_", required=True, choices=FMT_CHOICES)
    infer_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented OSD output instead of pretty-printed")
    infer_p.add_argument(
        "--arrays", action="store_true",
        help="rejected: OSD has no array syntax, --arrays applies only to OML output")
    infer_p.add_argument(
        "--allow-any", action="store_true",
        help="opt in to opening conflicting fields as `any` instead of erroring; "
             "reports which fields were opened, and why, on stderr")
    infer_p.add_argument("-o", "--output", help="output file; omit for stdout")
    infer_p.set_defaults(func=_cmd_infer)

    schema_p = subparsers.add_parser("schema", help="operate on a Schema (OSD)")
    schema_sub = schema_p.add_subparsers(dest="schema_command", required=True)

    schema_format_p = schema_sub.add_parser(
        "format", parents=[json_parent],
        help="canonicalize an OSD schema file (safe reformat only, no structural change)")
    schema_format_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_format_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_format_p.add_argument(
        "--arrays", action="store_true",
        help="rejected: OSD has no array syntax, --arrays applies only to OML output")
    schema_format_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_format_p.set_defaults(func=_cmd_schema_format)

    schema_normalize_p = schema_sub.add_parser(
        "normalize", parents=[json_parent],
        help="compute the canonical minimal equivalent schema "
             "(fewest records via partition refinement)")
    schema_normalize_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_normalize_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_normalize_p.add_argument(
        "--arrays", action="store_true",
        help="rejected: OSD has no array syntax, --arrays applies only to OML output")
    schema_normalize_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_normalize_p.set_defaults(func=_cmd_schema_normalize)

    schema_prune_p = schema_sub.add_parser(
        "prune", parents=[json_parent],
        help="remove everything that can never match: unreachable records, "
             "never-emittable fields, optional fields with unsatisfiable types")
    schema_prune_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_prune_p.add_argument(
        "--compact", action="store_true",
        help="single-line, machine-oriented output instead of pretty-printed")
    schema_prune_p.add_argument("-o", "--output", help="output file; omit for stdout")
    schema_prune_p.set_defaults(func=_cmd_schema_prune)

    schema_is_empty_p = schema_sub.add_parser(
        "is-empty", parents=[json_parent],
        help="does the schema accept no documents at all "
             "(unsatisfiable root, e.g. a mandatory ref cycle)")
    schema_is_empty_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_is_empty_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_is_empty_p.set_defaults(func=_cmd_schema_is_empty)

    schema_extract_p = schema_sub.add_parser(
        "extract", parents=[json_parent],
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

    schema_lint_p = schema_sub.add_parser(
        "lint", parents=[json_parent],
        help="report structural problems without mutating: unsatisfiable, "
             "unreachable, and duplicate records, plus an any-field inventory")
    schema_lint_p.add_argument("schema_file", help="OSD file, or - for stdin")
    schema_lint_p.add_argument(
        "--severity", choices=["info", "warning"], default="info",
        help="minimum severity to report (default: info, i.e. everything)")
    schema_lint_p.set_defaults(func=_cmd_schema_lint)

    schema_compat_p = schema_sub.add_parser(
        "compatible-with", parents=[json_parent],
        help="is every document `a` accepts also accepted by `b`")
    schema_compat_p.add_argument("a", help="OSD file, or - for stdin")
    schema_compat_p.add_argument("b", help="OSD file")
    schema_compat_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_compat_p.set_defaults(func=_cmd_schema_compatible_with)

    schema_equiv_p = schema_sub.add_parser(
        "equivalent", parents=[json_parent],
        help="do `a` and `b` accept exactly the same documents")
    schema_equiv_p.add_argument("a", help="OSD file, or - for stdin")
    schema_equiv_p.add_argument("b", help="OSD file")
    schema_equiv_p.add_argument(
        "--result-format", choices=RESULT_FORMAT_CHOICES, default="text")
    schema_equiv_p.set_defaults(func=_cmd_schema_equivalent)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``omnist`` command-line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)  # type: ignore[no-any-return]
    except (ParseError, SchemaError, WriteError, DocumentError, OSError) as exc:
        if getattr(args, "json", False):
            print(_json_error(exc))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


# module entry point, exercised only by direct execution
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
