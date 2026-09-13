# Glossary

For the formal definitions of Omnist's terms (node, edge, Document, Schema,
Scalar, cardinality, satisfiability, normalize, extract, infer, and the
rest), see
**[the Glossary chapter of spec.omnist.dev](https://spec.omnist.dev/01-glossary/)**
(and the [Document Model](https://spec.omnist.dev/02-document-model/) and
[Schema Model](https://spec.omnist.dev/03-schema-model/) chapters for the
full formal treatment). This page only maps those terms to their Python
names in this library.

## Concept → Python name

| Concept (spec.omnist.dev) | Python name here |
|---|---|
| node / Document | `Doc` — the wrapper class (`.edges()`, `.get()`, `.add()`, ...); see [the API reference](api.md#documents) |
| Scalar | `Scalar` class; ready-made instances under `t` (`t.string`, ...) or as top-level names (`STRING`, ...) |
| `any` type | `AnyType` class; singleton instance `t.any` |
| field | `Field(label, type, min, max)` |
| record (concept) | `Record`, built by the `record(*fields)` builder |
| Ref | `Ref`, built by the `ref(name)` builder |
| Schema | `Schema` — `root` `Ref` plus an `env` dict of `Record`s; see [the API reference](api.md#schemas) |
| a value's runtime classification | `value_kind(v)` / `matches_kind(value, name)` in [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py) |
| `compatible_with` / `equivalent` | `Schema.compatible_with()` / `Schema.equivalent()` |
| `normalize` | `Schema.normalize()` |
| `extract` | `Schema.extract(*labels)` — raises `SchemaError` if a kept label set would drop a mandatory field |
| `prune` | `Schema.prune()` |
| `infer` | top-level `infer(samples)` function |
| lint | `Schema.lint()`, returning `LintFinding(code, severity, location, message)` — see [the CLI reference](cli.md#omnist-schema-lint) |
| OSD | parsed by `parse_schema()`, produced by `to_osd()` |
| OML | read/written via [`read_oml`/`write_oml`](formats/oml.md) |

## Python-only terms

These have no spec counterpart — they're implementation details of this
library:

- **adjustment** / **`WriteReport`** — a recorded change a writer made
  because the target format can't hold a value losslessly (e.g. TOML
  dropping `null`). `strict=True` raises `WriteError` instead of adjusting
  silently. See [the API reference](api.md#adjustment-reports-lossy-writes).
- **codec** — a `Format`'s registered `read`/`write`/`check` functions
  (`register_format`), letting `Doc.from_format`/`to_format`/`check_format`
  use it like a built-in format. See
  [the API reference](api.md#format-registry).
