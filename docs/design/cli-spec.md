# CLI Spec

> Status: **implemented** — `omnist/cli.py` has shipped since 2026-06-26.
> This document specified the command surface before implementation, the
> same way the [model spec](model.md) and the
> [grammars](schema-osd-grammar.md) preceded theirs; it's kept as the
> normative spec the shipped CLI is checked against. See [the CLI
> reference](../cli.md) for the current, example-verified command docs.

## 1. Command tree

```
omnist format     <input>                          [--compact] [--arrays] [-o OUTPUT] [--json]
omnist convert    <input>   --from FMT --to FMT [--schema FILE] [--strict] [--report] [--result-format text|json|oml] [--compact] [--arrays] [-o OUTPUT] [--json]
omnist validate   <input>   --from FMT --schema FILE [--result-format text|json|oml] [--json]
omnist infer      <input>...  --from FMT             [--compact] [--allow-any] [-o OUTPUT] [--json]
omnist check      <input>   --from FMT --to FMT [--strict] [--result-format text|json|oml] [--json]

omnist schema format           <schema-file>  [--compact] [-o OUTPUT] [--json]
omnist schema normalize        <schema-file>  [--compact] [-o OUTPUT] [--json]
omnist schema prune            <schema-file>  [--compact] [-o OUTPUT] [--json]
omnist schema is-empty         <schema-file>  [--result-format text|json|oml] [--json]
omnist schema lint             <schema-file>  [--json] [--severity info|warning]
omnist schema extract          <schema-file>  --keep label1,label2,... [--compact] [-o OUTPUT] [--json]
omnist schema compatible-with  <a> <b>        [--result-format text|json|oml] [--json]
omnist schema equivalent       <a> <b>        [--result-format text|json|oml] [--json]
```

`FMT` is one of `json|yaml|toml|xml|oml`. A schema file is always OSD
(Omnist Schema Definition; `parse_schema`/`to_osd`) — schema commands take
no `--from`/`--to`.

`--json` is a **shared flag on every command** (an `argparse` parent parser),
specified once in [§1a](#1a-json-machine-mode-shared) rather than repeated per
command below.

## 1a. `--json` (machine mode, shared)

Every command accepts `--json`, with one uniform guarantee:

- **On any error** — `ParseError`/`SchemaError`/`WriteError`/`DocumentError`/
  `OSError`, whether raised through `main()`'s top-level handler or caught in a
  handler for a command-specific exit code (`convert --strict`'s WriteError→`1`,
  the `--from oml --to oml` guard→`2`, `schema extract`'s SchemaError→`1`) — the
  command prints `{"ok": false, "message": str(exc), "errors": [{"path","code",
  "message"}, ...]}` to **stdout** (stderr empty). `errors` is `ParseError.errors`
  when the exception is a `ParseError`, else `[]`. Exit code is **unchanged** from
  the non-`--json` run.
- **On success**, the commands with a single structured result — `validate`,
  `check`, `schema is-empty`/`compatible-with`/`equivalent` — emit that result as
  JSON on stdout, the same shape `--result-format json` produces for that command
  (reusing the existing json encoders; no new shapes). The text-emitting commands
  (`format`, `convert`, `infer`, `schema format`/`normalize`/`prune`/`extract`)
  print their document/schema text unchanged; `--json` governs only their error
  shape.

Exit codes are identical with and without `--json`, everywhere.

**Boundary:** argparse usage errors (unknown flag, missing required arg) are
*not* JSON-ified — they occur in `parse_args`, before any handler runs, and stay
argparse's own stderr message + exit `2`. Those are caller bugs, not data errors.

`--result-format` is unchanged and retained (it additionally offers `oml`
encoding and does not catch parse errors); `--json` is the recommended machine
interface. `validate --json` (issue #182) and `schema lint --json` predate this
and keep their exact prior output — they are the same shared flag, wired to their
existing richer handlers.

## 2. Format handling

- `<input>`/`<a>`/`<b>` may be a file path or `-` for stdin; `-o`/
  `--output` may be a file path or omitted for stdout.
- `--from` is always required wherever it appears, file or stream alike —
  no extension-based inference.
- `--to` is always required on `convert`/`check` — no defaulting.
- `format`/`schema format`/`schema normalize`/`schema prune`/
  `schema is-empty`/`schema lint`/`schema extract`/`schema compatible-with`/
  `schema equivalent` take no `--from`/`--to`: each reads/writes exactly
  one format (OML or OSD).
- Schema files conventionally use `.osd`; not enforced.

## 3. Commands

### `omnist format <input> [--compact] [--arrays] [-o OUTPUT]`

`read_oml(text)` → `write_oml(node)`. OML only; `--compact`
(`write_oml(node, indent=None)` — single-line output) and `--arrays`
(`write_oml(node, arrays=True)` — collapses same-label runs into `[...]`
array syntax, issue #218) are the flags beyond `-o`; they combine freely.

```sh
omnist format messy.oml -o clean.oml
omnist format messy.oml --compact
omnist format messy.oml --arrays
```

### `omnist convert <input> --from FMT --to FMT [--schema FILE] [--strict] [--report] [--result-format text|json|oml] [--compact] [--arrays] [-o OUTPUT]`

`read_<from>(text, schema=...)` → `write_<to>(node, strict=, report=)`.

- `--schema FILE`: schema-directed deserialization on read. If the input
  can't be made to conform, raises `ParseError` (every problem found),
  nothing written, exit `2`.
- `--report`: prints what `write_<to>` adjusted to stderr (encoding per
  `--result-format`, default `text`); the write still happens.
- `--strict`: refuses to write at all if anything would need adjusting —
  exit `1`.
- `--compact`: single-line OML output (`write_oml(node, indent=None)`)
  when `--to oml`; no effect for other `--to` values.
- `--arrays`: OML output collapses same-label runs into `[...]` array
  syntax (`write_oml(node, arrays=True)`) when `--to oml`; no effect for
  other `--to` values.
- `--from oml --to oml` with no `--schema` is rejected (exit `2`, use
  `format`) — a pure no-op otherwise. With `--schema` it's allowed: real
  schema-directed materialization, and the only CLI path to it (`format`/
  `check` have no `--schema`). Every other same-format pair (`json`→`json`,
  etc.) is always allowed.
- One document in, one document out; no batch mode.

```sh
omnist convert order.json --from json --to oml
omnist convert order.xml --from xml --to oml --schema order.osd -o order.oml
omnist convert data.oml --from oml --to oml --schema data.osd -o data.oml
omnist convert data.json --from json --to toml --report -o data.toml
omnist convert data.json --from json --to toml --strict -o data.toml
```
<!-- doc-illustrative -->

### `omnist validate <input> --from FMT --schema FILE [--result-format text|json|oml] [--json]`

Reads without schema-directed upgrading, then `Schema.validate`.

- `text` (default): `ValidationResult`'s `"invalid:\n  at $.path: message"` (or `valid`).
- `json`: `{"ok": bool, "errors": [{"path": str, "message": str}, ...]}`.
- `oml`: same shape, OML-encoded.

Exit `0` valid, `1` invalid, `2` read/parse error.

```sh
omnist validate order.json --from json --schema order.osd
omnist validate order.xml --from xml --schema order.osd --result-format json
```

- `--json`: a distinct, more detailed machine-readable mode (issue #182),
  independent of `--result-format`. Each errors entry also carries the
  stable machine-readable `code` (`validate.unexpected-field`, `validate.cardinality`,
  `validate.type-mismatch`, `validate.null-not-allowed`, `validate.shape-mismatch`) from
  `ValidationResult`/`ParseError.errors` (the same structured list
  `ParseError` has exposed since v0.4.1). Unlike `--result-format`,
  `--json` also converts read/parse errors -- normally `error: ...` on
  stderr -- into the same `{ok, message, errors}` shape on stdout:
  - success: `{"ok": true}`.
  - conformance failure: `{"ok": false, "message": str, "errors": [{"path": str, "code": str, "message": str}, ...]}`.
  - format-syntax failure (invalid input text, or a malformed schema): same shape, `"errors"` always `[]`, parse error in `"message"`.
  - Exit codes are unchanged in every case (`0`/`1`/`2` as above); only the
    printed shape and destination (stdout, not stderr, for read/parse
    errors) differ.

```sh
omnist validate order.json --from json --schema order.osd --json
omnist validate order.xml --from xml --schema order.osd --json
```

### `omnist infer <input>... --from FMT [--compact] [--allow-any] [-o OUTPUT]`

All inputs same format; `infer(docs)`, writes the result as OSD.
`--compact` emits a single-line schema (`to_osd(schema, indent=None)`).
Passing `--arrays` here is an **error** (exit code `2`) — the output is
always OSD, and OSD has no array syntax; `--arrays` applies only to OML
output (issues #218, #220). `--allow-any` opts in
to opening the two `infer` conflict points
(object/scalar mix, multi-kind scalar) as `any` fields instead of erroring;
the schema still goes to stdout, and a per-field report of what was opened
and why goes to stderr (nothing printed when zero fields open). Like every
other diagnostic-producing command, `--json` switches that report to
structured JSON (`{"opened": [{"location", "reason"}, ...]}`, matching
`AnyFallback`) instead of the text form.

```sh
omnist infer samples/*.json --from json -o inferred.osd
```

### `omnist check <input> --from FMT --to FMT [--strict] [--result-format text|json|oml]`

`check_<to>` — reports what `write_<to>` would adjust, never writes
anything. `--from`/`--to` may be equal (unlike `convert`).

- Default: exit `0` regardless of result; purely informational.
- `--strict`: exit `0` if nothing would need adjusting, `1` otherwise.

```sh
omnist check data.json --from json --to toml
omnist check data.json --from json --to toml --strict
```

### `omnist schema format <schema-file> [--compact] [-o OUTPUT]`

`parse_schema` → `to_osd`. Safe reformat only — same records, same names,
canonical whitespace/field order. No structural change (contrast
`normalize`). `--compact` emits a single-line schema (`to_osd(schema,
indent=None)`). Passing `--arrays` here is an **error** (exit code `2`) — OSD output, no
array syntax (issues #218, #220).

```sh
omnist schema format messy.osd -o clean.osd
omnist schema format messy.osd --compact
```

### `omnist schema normalize <schema-file> [--compact] [-o OUTPUT]`

`Schema.normalize()`, written back as OSD. Computes the canonical minimal
equivalent schema (partition refinement, fewest env records, unique up to
naming) — a structural change, unlike `schema format`. `--compact` emits a
single-line schema, same as `schema format`. Passing `--arrays` here is
likewise an **error** (exit code `2`) — OSD output, no array syntax.

### `omnist schema prune <schema-file> [--compact] [-o OUTPUT]`

`Schema.prune()`, written back as OSD. Removes everything that can never
match — unreachable records, never-emittable (`max == 0`) fields, and
optional fields whose type is an unsatisfiable record — without ever
merging records (that's `normalize`'s job; `normalize` runs `prune` as its
own first step). `--compact` as elsewhere.

### `omnist schema is-empty <schema-file> [--result-format text|json|oml]`

`Schema.is_empty()` — True iff the schema accepts no documents at all
(unsatisfiable root, e.g. a mandatory ref cycle). Prints `true`/`false`
(`text`, default), `{"empty": bool}` (`json`), or the same shape
OML-encoded (`oml`). Exit `0` if empty, `1` if not — the same
boolean-result convention as `compatible-with`/`equivalent`.

### `omnist schema lint <schema-file> [--json] [--severity info|warning]`

`lint()` — non-destructive structural diagnostics for the schema itself.
Reports, never mutates (`prune`/`normalize` are the transforms). Four
checks: `lint.unsatisfiable-record` (reachable but no finite document matches),
`lint.unreachable-record` (defined but not reachable from root),
`lint.duplicate-record` (structurally identical records under different names),
each `warning`; and `lint.any-field` (inventory of every `any`-typed field),
`info`. Findings sort by `(code, location)`. Text output is one
`severity: code: location: message` line per finding, or `no findings`.
`--json` prints `{"ok": bool, "findings": [{"code","severity","location",
"message"}, ...]}`, mirroring `validate --json`'s shape. `--severity`
filters by minimum severity (`info` default keeps everything; `warning`
drops the `lint.any-field` inventory). Exit `0` if no surviving finding is
`warning`-severity, `1` if any is — an `info`-only result always exits `0`.

### `omnist schema extract <schema-file> --keep label1,label2,... [--compact] [-o OUTPUT]`

`Schema.extract(*labels)`, written back as OSD (paper Algorithm 5,
ExtractSubschema). The minimal subschema recognizing only documents built
from `--keep`'s comma-separated labels: fields whose label isn't kept are
dropped, and anything they make unreachable is pruned away too (`prune()`
+ `normalize()` is the algorithm's own final step). `--compact` emits a
single-line schema, same as `schema format`/`schema normalize`.

If deleting a non-kept label would remove a *mandatory* (`min >= 1`)
field, the record that had it -- and transitively anything mandatorily
depending on it -- is invalidated; deliberately an error rather than a
silent relaxation to optional (see `docs/schema.md`'s "Subschema
extraction" section for the rationale). If that invalidation reaches the
root, there is no valid subschema for this `--keep` set: `SchemaError`
naming the first offending label and record, printed to stderr as
`error: ...`, exit `1` (a definite "no," like `compatible-with`'s False --
not the generic exit `2` for parse/usage errors).

```sh
omnist schema extract order.osd --keep quote,line,desc,price
omnist schema extract order.osd --keep quote,line,desc,price --compact
```

### `omnist schema compatible-with <a> <b> [--result-format text|json|oml]`

`a.compatible_with(b)`. `text`: `true`/`false`. `json`:
`{"compatible": bool}`. `oml`: `compatible: true`/`compatible: false`.
Exit `0`/`1`.

```sh
omnist schema compatible-with v1.osd v2.osd
```

### `omnist schema equivalent <a> <b> [--result-format text|json|oml]`

`a.equivalent(b)`. Same output/exit convention as `compatible-with`.

## 4. Conventions

| | |
|---|---|
| Exit `0` | success / valid / compatible / equivalent / losslessly-writable |
| Exit `1` | a definite "no" — invalid, incompatible, not equivalent, or (`--strict`) not losslessly writable |
| Exit `2` | usage error, parse error, missing file, unsupported format, schema non-conformance |
| `--result-format` | `text` (default) / `json` / `oml` — encodes a command's own result, not Document/Schema content; `convert` only uses it together with `--report` |
| `-`/`-o` | stdin/stdout |

## 5. Non-goals

- No format auto-detection (content or extension).
- No batch/multi-document conversion.
- No alternate Schema serialization (e.g. JSON-Schema-shaped import/export).
- No `schema diff` (structural diff beyond the boolean `compatible-with`/`equivalent`).
- No schema editing (only whole-schema read/transform).

## 6. Packaging

```toml
[project.scripts]
omnist = "omnist.cli:main"
```

`omnist/cli.py` — `argparse`-based, public `omnist` API only. No new
required dependency.
