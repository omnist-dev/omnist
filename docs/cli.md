# CLI

The `omnist` command-line tool — a thin wrapper over the library described
throughout the rest of these docs; every command maps directly onto one or
two calls into the public `omnist` API. This page matches
[the CLI spec](design/cli-spec.md) exactly.

Every example below is real: it's run against the files under
[`examples/cli/`](https://github.com/omnist-dev/omnist/tree/master/examples/cli)
in this repo, and the output shown is the exact, verified output of running
it — see `tests/test_cli_examples.py`, which runs every one of these and
fails CI if the output ever drifts from what's shown here. Run them
yourself from the repo root.

## Commands

- [Version and help](#version-and-help)
- [Machine mode: `--json`](#machine-mode---json)
- [`omnist format`](#omnist-format)
- [`omnist convert`](#omnist-convert)
- [`omnist check`](#omnist-check)
- [`omnist infer`](#omnist-infer)
- [`omnist validate`](#omnist-validate)
- [`omnist schema format`](#omnist-schema-format)
- [`omnist schema normalize`](#omnist-schema-normalize)
- [`omnist schema prune`](#omnist-schema-prune)
- [`omnist schema is-empty`](#omnist-schema-is-empty)
- [`omnist schema lint`](#omnist-schema-lint)
- [`omnist schema extract`](#omnist-schema-extract)
- [`omnist schema compatible-with`](#omnist-schema-compatible-with)
- [`omnist schema equivalent`](#omnist-schema-equivalent)

## Version and help

```sh
$ omnist --version
omnist 0.7.11
```
<!-- verified-by: tests/test_docs.py::test_docs_version_examples_match_live_version -->

`--help` is available on the top-level command and every subcommand
(`omnist <command> --help`) — standard `argparse` behavior, nothing
omnist-specific:

```sh
$ omnist --help
usage: omnist [-h] [--version]
              {format,convert,check,validate,infer,schema} ...

One canonical data model for JSON, YAML, TOML, XML, and OML -- read, validate,
and write any of them. See docs/cli.md for the full command reference.

positional arguments:
  {format,convert,check,validate,infer,schema}
    format              canonicalize an OML document (the only format with no
                        other tool for this)
    convert             convert a document between formats (one in, one out)
    check               report what writing as --to would adjust, without ever
                        writing
    validate            check a document against a schema (no schema-directed
                        upgrading)
    infer               draft a schema from example documents (all the same
                        format)
    schema              operate on a Schema (OSD)

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## Machine mode: `--json`

`--json` is a **global flag accepted by every command** (`format`, `convert`,
`check`, `infer`, `validate`, and every `schema` subcommand). It turns the
command into "machine mode" with a single, uniform guarantee:

- **On any error** — a malformed document, a bad schema, a missing/unreadable
  file, an IO failure, or a command-specific refusal (`convert --strict`'s
  lossy-write refusal, `schema extract`'s "no valid subschema") — the command
  prints `{"ok": false, "message": str, "errors": [{"path", "code", "message"}, ...]}`
  to **stdout** instead of a bare `error: ...` on stderr. `errors` carries the
  structured per-problem list when the failure is a `ParseError` (the
  [same list it exposes since v0.4.1](deserialization.md)); otherwise it's `[]`
  and the detail is in `message`. **stderr stays empty**, so a caller never has
  to string-match stderr to detect or classify a failure.
- **On success**, for the commands that have a single structured result —
  `validate` (conformance), `check` (adjustments), and `schema is-empty` /
  `compatible-with` / `equivalent` (a boolean) — the result is emitted as JSON
  on stdout, the same shape [`--result-format json`](#omnist-validate) gives for
  that command. Commands whose whole purpose is to emit a document or schema as
  text (`format`, `convert`, `infer`, `schema format`/`normalize`/`prune`/`extract`)
  print that text **exactly as without `--json`** — `--json` only governs their
  error shape; wrapping their emitted text in JSON would add nothing.

**Exit codes are identical with and without `--json`, in every case.** `--json`
only changes *where* output goes (stdout vs stderr) and *its shape* — never the
exit status.

The one deliberate boundary: **argparse usage errors** (an unknown flag, a
missing required argument like `--from`) are *not* JSON-ified. Those are caller
bugs, not data errors; argparse still writes its usage message to stderr and
exits `2`, `--json` or not.

```sh
$ omnist check examples/cli/lossy.json --from json --to toml --json
[{"path": "$.age", "code": "null.omitted", "message": "null value dropped (TOML has no null)", "severity": "warning"}]

$ omnist convert examples/cli/lossy.json --from json --to toml --strict --json
{"ok": false, "message": "warning: $.age: null value dropped (TOML has no null)", "errors": []}
# exit 1

$ omnist schema compatible-with examples/cli/v1.osd examples/cli/v2.osd --json
{"compatible": true}
```

### Scripting `omnist`

For a wrapper (a CI step, a Node/Python subprocess) the contract is: **pass
`--json`, read stdout, branch on the exit code.** A `0`/`1` result is the
command's own answer (valid/invalid, compatible/not, empty/not, or a clean
write); its stdout is the JSON result. A non-zero-with-`{"ok": false}` on stdout
is a data/IO error you can parse for `message`/`errors`. The only thing that
still lands on stderr is an argparse usage error (exit `2`, no JSON) — a bug in
how you invoked the tool, worth surfacing loudly rather than parsing.

## `omnist format`

```
omnist format <input> [--compact] [--arrays] [-o OUTPUT]
```

Canonicalizes an OML document — `read_oml` then `write_oml`. `<input>` is a
file path or `-` for stdin; `-o`/`--output` is a file path, or omit it for
stdout.

```sh
$ cat examples/cli/messy-person.oml
name:"Ann"
age:   30
$ omnist format examples/cli/messy-person.oml
name: "Ann"
age: 30
$ echo 'name:   "Ann"' | omnist format -
name: "Ann"
```

`--compact` emits a single-line, machine-oriented form instead
(`write_oml(node, indent=None)`):

```sh
$ omnist format examples/cli/messy-person.oml --compact
name: "Ann"; age: 30
```

`--arrays` collapses runs of ≥ 2 consecutive same-label edges into
`[...]` array syntax (`write_oml(node, arrays=True)`); combines with
`--compact`.

Malformed OML raises the same `ParseError` `read_oml` would, printed to
stderr as `error: ...`, exit code `2` — nothing written.

## `omnist convert`

```
omnist convert <input> --from FMT --to FMT [--schema FILE] [--strict] [--report] [--result-format text|json|oml] [--compact] [--arrays] [-o OUTPUT]
```

`read_<from>(text, schema=...)` → `write_<to>(node, strict=, report=)`.
Reformats data across formats, optionally upgrading/validating it against
a schema on the way in (per the [deserialization guarantee](deserialization.md)).

`--from oml --to oml` is rejected (exit `2`, pointing at `omnist format`
instead) — that's the one same-format case with a real alternative.
Every *other* same-format pair (`json`→`json`, `yaml`→`yaml`, etc.) is
allowed through `convert`, since there's no replacement command for
those (other formats already have their own formatters elsewhere; this
CLI doesn't duplicate them).

If `--schema` is given and the input can't be made to conform,
`materialize` raises `ParseError` (every problem found, not just the
first) — printed to stderr, nothing written, exit `2`.

`--report` and `--strict` map directly to `write_<to>`'s own `report=`/
`strict=` parameters (no effect on `--to oml`, which never needs them —
OML is always exactly lossless):

- **`--report`** prints what got adjusted to **stderr** (`--result-format`,
  default `text`, controls the encoding — same `text`/`json`/`oml`
  convention as everywhere else) — the write still happens normally.
  `--result-format` without `--report` has no effect.
- **`--strict`** refuses to write at all if anything would need
  adjusting — exit `1` (a definite "no, not losslessly possible," grouped
  with `validate`/`compatible-with`'s `1`, not the usage/parse failures
  that exit `2`).

`--compact` emits single-line, machine-oriented OML (`write_oml(node,
indent=None)`) when `--to oml`; no effect for other `--to` values.
`--arrays` likewise passes through to `write_oml(node, arrays=True)` when
`--to oml`, collapsing same-label runs into `[...]` array syntax; no effect
for other `--to` values.

`convert` is one document in, one document out — no batch mode (the
library's `read_xml`/`write_xml` only support a single-rooted Document;
converting many files is a shell loop).

```sh
$ omnist convert examples/cli/person.json --from json --to oml
person: {
  name: "Ann"
  age: 30
}
```

The same person, read from XML this time, upgraded/validated against the
schema on the way in:

```sh
$ omnist convert examples/cli/person.xml --from xml --to oml --schema examples/cli/person.osd
person: {
  name: "Ann"
  age: 30
}
```

Through stdin/stdout:

```sh
$ cat examples/cli/person.toml | omnist convert - --from toml --to json
{"person": {"name": "Ann", "age": 30}}
```

`--report`/`--strict`, on a document TOML can't hold losslessly
(`examples/cli/lossy.json` is `{"name": "Ann", "age": null}`):

```sh
$ omnist convert examples/cli/lossy.json --from json --to toml --report
name = "Ann"
# stderr:
warning: $.age: null value dropped (TOML has no null)

$ omnist convert examples/cli/lossy.json --from json --to toml --strict
# exit 1, nothing written, stderr:
error: warning: $.age: null value dropped (TOML has no null)
```

## `omnist check`

```
omnist check <input> --from FMT --to FMT [--strict] [--result-format text|json|oml]
```

Reports what `write_<to>` would adjust (`check_json`/`check_yaml`/
`check_toml`/`check_xml`/`check_oml`) **without ever writing anything** —
`convert`'s dry-run counterpart, for asking the question without
producing (or risking producing) any output. Unlike `convert`,
`--from`/`--to` may be equal.

By default, `check` always exits `0` — it's purely informational.
`--strict` turns it into a CI gate: exit `0` if nothing would need
adjusting, `1` if anything would.

```sh
$ omnist check examples/cli/lossy.json --from json --to toml
warning: $.age: null value dropped (TOML has no null)

$ omnist check examples/cli/lossy.json --from json --to toml --strict
warning: $.age: null value dropped (TOML has no null)
# exit 1
```

## `omnist infer`

```
omnist infer <input>... --from FMT [--compact] [--allow-any] [-o OUTPUT]
```

All inputs must be the same format. Each is read as a `Doc`,
[`infer(docs)`](schema.md#operations-compare-and-infer) drafts a schema
from them, written out as OSD. `--compact` emits a single-line form
(`to_osd(schema, indent=None)`) instead of the pretty-printed default.
Passing `--arrays` here is an **error** (exit code `2`): the output is OSD,
not OML, and OSD has no array syntax — `--arrays` applies only to OML output
(`format`, `convert --to oml`).

By default a label that is an object in some samples and a scalar in others,
or a scalar of more than one kind, is an error — `infer` never emits `any`.
`--allow-any` opts in to opening those conflict points as `any` fields
instead, for bootstrapping a draft from messy or polymorphic data. The
schema still goes to stdout (so `omnist infer … --allow-any > out.osd` stays
pipeable); the list of opened fields and why goes to **stderr**:

```sh
$ omnist infer messy1.json messy2.json --from json --allow-any > draft.osd
opened 2 field(s) as `any`:
  Root.data — mixes objects and values
  Root.score — values of more than one scalar kind (integer, string)
```

Nothing is printed to stderr when no field is opened. Without `--allow-any`,
a conflicting sample errors exactly as before.

```sh
$ omnist infer examples/cli/sample1.json examples/cli/sample2.json --from json
record Root {
    "name": string,
    "age" [0,1]: integer,
}
root Root
```

(`sample1.json` is `{"name": "Ann"}`; `sample2.json` is `{"name": "Bo", "age": 30}` —
`age` is absent from the first sample, so `infer` drafts it as optional. This
is exactly the same `name`/`age` evolution shown in `schema compatible-with`
below, as data instead of as two schema versions.)

## `omnist validate`

```
omnist validate <input> --from FMT --schema FILE [--result-format text|json|oml] [--json]
```

Reads `<input>` as `FMT` (`json`/`yaml`/`toml`/`xml`/`oml`) **without**
schema-directed upgrading — the same lenient parse a plain `read_<from>`
call would produce — then runs `Schema.validate` against the OSD file
given by `--schema`. This mirrors the library's own validation/
deserialization split: validation only ever *checks* a value already in
the document; it never converts anything (see [Schema-directed
deserialization](deserialization.md) for the upgrading side of that
split, which is what `convert --schema` does instead).

`--result-format` (default `text`) controls the printed result:

- `text` — `ValidationResult`'s own `"invalid:\n  at $.path: message"`
  formatting, or `valid`.
- `json` — `{"ok": bool, "errors": [{"path": str, "message": str}, ...]}`.
- `oml` — the same `{ok, errors}` shape, OML-encoded.

```sh
$ omnist validate examples/cli/person.json --from json --schema examples/cli/person.osd
valid
```

A rejected person (`invalid-person.json` has `"age": "thirty"` — the wrong
type — and no `name` at all):

```sh
$ omnist validate examples/cli/invalid-person.json --from json --schema examples/cli/person.osd
invalid:
  at $.person.age: expected integer, got string ('thirty')
  at $.person: field 'name' occurs 0 time(s), expected exactly 1
# exit 1

$ omnist validate examples/cli/invalid-person.json --from json --schema examples/cli/person.osd --result-format json
{"ok": false, "errors": [{"path": "$.person.age", "message": "expected integer, got string ('thirty')"}, {"path": "$.person", "message": "field 'name' occurs 0 time(s), expected exactly 1"}]}
```

Exit `0` if valid, `1` if invalid, `2` on a read/parse error (malformed
input or schema, printed to stderr as `error: ...`).

### `--json`

A separate, more detailed machine-readable mode for scripts/CI that need
more than `--result-format json`'s `{path, message}` pairs — each entry also
carries the stable, machine-readable `code` from the underlying
`ValidationResult`/`ParseError.errors` (`unexpected-field`, `cardinality`,
`type-mismatch`, `null-not-allowed`, `shape-mismatch`), the same structured
list [`ParseError` exposes since v0.4.1](deserialization.md). Unlike
`--result-format`, `--json` also captures read/parse errors — normally a
bare `error: ...` on stderr with exit `2` — as the same `{ok, message,
errors}` shape on stdout, so a caller never has to string-match stderr.
Exit codes are unchanged in every case; only where the result is printed,
and its shape, differ from the default.

- Success: `{"ok": true}`.
- Conformance failure: `{"ok": false, "message": str, "errors": [{"path": str, "code": str, "message": str}, ...]}` — one entry per problem.
- Format-syntax failure (invalid `FMT` text, or a malformed `--schema`):
  same shape, but `"errors"` is always `[]` — there's no structured
  per-problem list for a document that couldn't even be parsed, so the
  parse error is only in `"message"`.

```sh
$ omnist validate examples/cli/person.json --from json --schema examples/cli/person.osd --json
{"ok": true}

$ omnist validate examples/cli/invalid-person.json --from json --schema examples/cli/person.osd --json
{"ok": false, "message": "invalid:\n  at $.person.age: expected integer, got string ('thirty')\n  at $.person: field 'name' occurs 0 time(s), expected exactly 1", "errors": [{"path": "$.person.age", "code": "type-mismatch", "message": "expected integer, got string ('thirty')"}, {"path": "$.person", "code": "cardinality", "message": "field 'name' occurs 0 time(s), expected exactly 1"}]}
# exit 1

$ echo '{not valid json' | omnist validate - --from json --schema examples/cli/person.osd --json
{"ok": false, "message": "invalid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)", "errors": []}
# exit 2
```

## `omnist schema format`

```
omnist schema format <schema-file> [--compact] [-o OUTPUT]
```

Canonicalizes an OSD ([Omnist Schema Definition](schema.md)) file —
`parse_schema` then `to_osd`. Same records, same names, just canonical
whitespace/field order; it never changes a schema's structure (contrast
[`Schema.normalize()`](schema.md#operations-compare-and-infer), which
computes the canonical minimal equivalent schema — fewest records,
merging more than just plain structurally-identical ones).

```sh
$ cat examples/cli/messy-person.osd
record Person{"name":string,"age" [0,1]:integer}
root Person
$ omnist schema format examples/cli/messy-person.osd
record Person {
    "name": string,
    "age" [0,1]: integer,
}
root Person
```

`--compact` emits a single-line form instead (`to_osd(schema,
indent=None)`):

```sh
$ omnist schema format examples/cli/messy-person.osd --compact
record Person { "name": string, "age" [0,1]: integer } root Person
```

Passing `--arrays` here is an **error** (exit code `2`) — the output is OSD,
not OML; `--arrays` applies only to OML output (`format`, `convert --to oml`).

Malformed OSD raises `SchemaError`, printed to stderr as `error: ...`,
exit code `2`.

## `omnist schema normalize`

```
omnist schema normalize <schema-file> [--compact] [-o OUTPUT]
```

`Schema.normalize()`, written back out as OSD — unlike `schema format`,
this *can* change a schema's structure: it computes the canonical minimal
schema equivalent to the input (fewest env records, unique up to naming;
see [the schema doc](schema.md#operations-compare-and-infer)).
`duplicate-records.osd` defines `Employee` and `Customer` with the exact
same shape (just a `name`); normalizing merges them into one:

```sh
$ cat examples/cli/duplicate-records.osd
record Employee { "name": string }
record Customer { "name": string }
record Company  { "employee": Employee, "customer": Customer }
root Company
$ omnist schema normalize examples/cli/duplicate-records.osd
record Company {
    "employee": Customer,
    "customer": Customer,
}
record Customer {
    "name": string,
}
root Company
```

`--compact` emits the same merged schema on a single line instead
(`to_osd(schema, indent=None)`). Passing `--arrays` here is an
**error** (exit code `2`) — OSD output has no array syntax.

## `omnist schema prune`

```
omnist schema prune <schema-file> [--compact] [-o OUTPUT]
```

`Schema.prune()`, written back out as OSD — removes everything that can
never match: records unreachable from root, never-emittable (`max == 0`)
fields, and optional fields whose type is an unsatisfiable record (see
[the schema doc](schema.md#operations-compare-and-infer)). Unlike
`normalize` it never merges records — it only deletes dead weight:

```sh
$ printf 'record R { "x": integer, "ghost" [0,0]: string }\nrecord Orphan { "y": string }\nroot R\n' \
    | omnist schema prune -
record R {
    "x": integer,
}
root R
```

## `omnist schema is-empty`

```
omnist schema is-empty <schema-file> [--result-format text|json|oml]
```

`Schema.is_empty()` — does the schema accept no documents at all (an
unsatisfiable root, e.g. a mandatory ref cycle)? Prints `true`/`false`
(`text`, default), `{"empty": bool}` (`json`), or the same shape
OML-encoded (`oml`); exit `0` if empty, `1` if not — mirroring
`compatible-with`/`equivalent`'s exit convention:

```sh
$ printf 'record A { "x": B }\nrecord B { "y": A }\nroot A\n' | omnist schema is-empty -
true
```

## `omnist schema lint`

```
omnist schema lint <schema-file> [--json] [--severity info|warning]
```

`lint()` — non-destructive structural diagnostics for the *schema itself*
(as opposed to `validate`, which checks a *document* against a schema). It
**reports, never mutates**: `prune`/`normalize` are the transforms that
fix these problems, `lint` only surfaces them. Four checks:

| Code | Severity | Meaning |
|---|---|---|
| `unsatisfiable-record` | `warning` | a reachable record no finite document can match (e.g. a mandatory ref cycle) |
| `unreachable-record` | `warning` | a record defined in `env` but never reachable from `root` |
| `duplicate-record` | `warning` | two+ structurally identical records under different names |
| `any-field` | `info` | an inventory of every `any`-typed field, for a human to audit |

Findings are sorted by `(code, location)`. Exit `0` if no `warning`-severity
finding survives the `--severity` filter, `1` otherwise — an `any-field`
inventory alone never fails. `--json` prints
`{"ok": bool, "findings": [{"code","severity","location","message"}, ...]}`;
`--severity warning` suppresses the `info`-level `any-field` inventory.

```sh
$ omnist schema lint examples/cli/duplicate-records.osd
warning: duplicate-record: Customer, Employee: records 'Employee' are structurally identical to 'Customer'; merge them with `schema normalize`
```

A clean schema prints `no findings` and exits `0`.

## `omnist schema extract`

```
omnist schema extract <schema-file> --keep label1,label2,... [--compact] [-o OUTPUT]
```

`Schema.extract(*labels)`, written back out as OSD — the minimal subschema
recognizing only documents built from `--keep`'s comma-separated labels
(paper Algorithm 5, ExtractSubschema; see
[the schema doc](schema.md#subschema-extraction)). Fields whose label
isn't kept are dropped, and anything they made unreachable is pruned away
too:

```sh
$ cat examples/cli/quote-order.osd
record Root  { "quote" [0,1]: Quote, "order" [0,1]: Order }
record Quote { "line" [1,]: Line }
record Order { "line" [1,]: OrderLine }
record Line  { "desc": string, "price": number }
record OrderLine { "product" [1,]: Product, "qty": integer }
record Product   { "desc": string, "price": number }
root Root
$ omnist schema extract examples/cli/quote-order.osd --keep quote,line,desc,price
record Line {
    "desc": string,
    "price": number,
}
record Quote {
    "line" [1,]: Line,
}
record Root {
    "quote" [0,1]: Quote,
}
root Root
```

`"order"` wasn't kept, so `Order`/`OrderLine`/`Product` are gone too, once
unreachable. `--compact` emits a single-line form, same as `schema
format`/`schema normalize`.

If dropping a label would delete a *mandatory* field and there's no way to
still build the record that had it (see the schema doc's
[design decision](schema.md#subschema-extraction) on why this errors
rather than silently loosening cardinality), the error goes to stderr and
the exit code is `1` — a definite "no valid subschema," not a parse/usage
failure:

```sh
$ echo 'record R { "must": integer, "opt" [0,1]: string }
root R' | omnist schema extract - --keep opt
error: no valid subschema: removing label 'must' deletes a mandatory field of record 'R'
# exit 1
```

Malformed OSD or a missing `--keep` is a usage/parse error, exit code `2`.

## `omnist schema compatible-with`

```
omnist schema compatible-with <a> <b> [--result-format text|json|oml]
```

`a.compatible_with(b)` — true if every Document `a` accepts, `b` also
accepts (`b` is backward-compatible with `a`). `--result-format` (default
`text`) prints `true`/`false`, `{"compatible": bool}` (`json`), or the
same shape OML-encoded. Exit `0` if true, `1` if false, `2` on a parse
error.

```sh
$ cat examples/cli/v1.osd
record Person { "name": string }
root Person
$ cat examples/cli/v2.osd
record Person { "name": string, "age" [0,1]: integer }
root Person
$ omnist schema compatible-with examples/cli/v1.osd examples/cli/v2.osd
true
```

## `omnist schema equivalent`

```
omnist schema equivalent <a> <b> [--result-format text|json|oml]
```

`a.equivalent(b)` — true if both accept exactly the same Documents. Same
output/exit convention as `compatible-with`. `v1.osd` and `v2.osd` above
are compatible but not equivalent (`v2` accepts a document `v1` doesn't):

```sh
$ omnist schema equivalent examples/cli/v1.osd examples/cli/v2.osd
false
# exit 1
```
