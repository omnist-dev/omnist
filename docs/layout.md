# Repo layout

How the repo is organized: the canonical model's modules, the docs page
map, and the test file map. For anything deeper than a one-line summary,
follow the link.

## `omnist/*.py`

The implementation of the Document/Schema model described in
`docs/design/model.md`. `import omnist` re-exports its public surface; this
is where the logic actually lives.

- **`document.py`** -- the Document model: `Doc` and the edge-list node shape
  (`[(label, node), ...]` / scalar leaf), with navigation/editing helpers.
- **`schema.py`** -- the Schema model: `Record`, `Scalar`, `Ref`, `Field`,
  `Schema` (with `validate`), and the seven scalar kinds.
- **`osd.py`** -- OSD (Omnist Schema Definition): `parse_schema` / `to_osd`,
  parsing and serializing the `record ... root ...` text syntax.
- **`oml.py`** -- OML (Omnist's own format): tokenizer, parser, and writer;
  the only format with zero adjustments on write.
- **`formats.py`** -- the JSON/YAML/TOML/XML codecs (`read_*`/`write_*`/
  `check_*`), each going through the shared grouped/edge-list conversion.
- **`infer.py`** -- `infer()`: draft a schema from example Documents.
- **`ops/`** -- schema operations package, one module per algorithm from
  the paper: `subschema.py` (`compatible_with`/`equivalent`), `prune.py`
  (`prune`/`is_empty`), `minimize.py` (`normalize`), `extract.py`
  (`extract`), `isomorphic.py` (test-only equivalence oracle), plus
  `signature.py` helpers.
- **`deserialize.py`** -- `materialize()`: schema-directed upgrading of a
  freshly-read node's leaf values (e.g. ISO string -> `date`) when the
  schema is known and the conversion is value-exact.
- **`report.py`** -- `Adjustment`/`WriteReport`: records what a lossy
  writer had to change, with severities, and drives lenient/inspect/strict
  write modes.
- **`registry.py`** -- the format plugin registry: `Format`,
  `register_format`, and the built-in JSON/YAML/TOML/XML registrations.
- **`__init__.py`** -- re-exports the package's public names from the
  modules above.

`omnist/errors.py` defines the exception hierarchy
(`OmnistError`, `DocumentError`, `SchemaError`, `ParseError`, `WriteError`,
`UnsafeXMLWarning`); `omnist/__init__.py` is the public package surface;
`omnist/cli.py` is the `omnist` command-line tool (see [cli.md](cli.md)),
a thin argument-parsing layer over that same public surface.

## `docs/` page map

- **[README.md](README.md)** -- the docs index (this page is linked from it).
- **[quickstart.md](quickstart.md)** -- the shortest possible tour: one OML
  snippet, one schema, `validate()`, `infer()`.
- **[guide.md](guide.md)** -- the practical, narrative tour of the whole
  library. Read this first if you're not in a hurry.
- **[schema.md](schema.md)** -- the Schema model and OSD on their own:
  `record` definitions, cardinality, the Python builder, the comparison/
  inference operations.
- **[example.md](example.md)** -- one order/address/line-item schema
  validated against a document in OML (and the other formats), plus a
  backward-compatibility check. The full worked example; `quickstart.md`
  is the short one.
- **[api.md](api.md)** -- every public name importable from `omnist`, with
  signatures.
- **[cli.md](cli.md)** -- the `omnist` command-line tool; the planned full
  surface is [design/cli-spec.md](design/cli-spec.md).
- **[glossary.md](glossary.md)** -- one definition per term used across the
  docs and code, grouped by concept area.
- **[testing.md](testing.md)** -- the test suite layout, coverage tooling
  and target, the fuzzing approach, and what CI runs. The tests section
  below points here for depth.
- **[layout.md](layout.md)** -- this page.
- **`formats/`** -- one page per format, plus an overview:
  [overview.md](formats/overview.md) (how each format maps to the model),
  [oml.md](formats/oml.md), [json.md](formats/json.md),
  [yaml.md](formats/yaml.md), [toml.md](formats/toml.md),
  [xml.md](formats/xml.md).
- **`design/model.md`** ([design/model.md](design/model.md)) -- the formal
  Document and Schema model definitions; self-contained, no paper required.
- **`paper/`** -- the Lee & Cheung CIKM 2010 paper that inspired the model
  (background reading only, not required to use Omnist).
- **`examples/`** -- one page per real-world worked example, alongside
  `example.md`'s single canonical one, plus
  [index.md](examples/index.md) tying all four together (comparison
  table, four gap categories, consolidated lessons):
  [pyproject.md](examples/pyproject.md) models `pyproject.toml`, an
  external format not designed for Omnist -- includes a candid
  can/cannot-model analysis (unions, open key sets, cross-field
  constraints) and a comparison against hand-written JSON Schema.
  [package-json.md](examples/package-json.md) models `package.json`, a
  format with no formal spec at all -- how that shows up as a *higher*
  proportion of unchecked (`any`) fields despite a smaller schema.
  [github-actions.md](examples/github-actions.md) models a GitHub
  Actions workflow -- the highest `any` proportion of the four, plus a
  real codec-level finding (YAML 1.1's boolean-coercion rule breaking
  the ordinary `on:` key). [sitemap.md](examples/sitemap.md) models
  sitemap.xml -- structurally the cleanest of the four, and the only one
  to surface the fourth gap category (value refinement: enums, ranges).

## `tests/` file map

Full test strategy (coverage target, fuzzing approach, CI) is in
[testing.md](testing.md) -- this is just a map of what lives where.

- **`test_canonical.py`** -- the core suite for the Document/Schema model:
  `Doc`, the `record`/`Ref` schema, OSD, validation, the schema
  operations (`compatible_with`/`equivalent`/`infer`), and the format
  codecs.
- **`test_oml.py`** -- OML round-tripping: every scalar kind, escaping,
  raw/multiline strings, separators, reserved words, numeric and nesting
  edge cases, and schema-directed reads.
- **`test_docs.py`** -- executes the key snippets shown in the docs
  (`README.md`, `docs/guide.md`, `docs/schema.md`, `docs/quickstart.md`,
  etc.) as assertions, so a docs change that breaks the described behavior
  fails CI instead of rotting silently.
- **`test_examples.py`** -- runs every `examples/*.py` file as a subprocess
  and asserts a clean exit, since examples are documentation too.
- **`test_examples_pyproject.py`** -- validates each `examples/pyproject/
  fixtures/*.toml` file against `pyproject.osd` directly (not just a
  clean-exit check), and checks the `any`-field count against what
  [docs/examples/pyproject.md](examples/pyproject.md) claims, so
  that page can't drift from what validation actually does.
- **`test_examples_package_json.py`** -- the same discipline applied to
  `examples/package-json/`: validates each fixture against
  `package.osd`, checks committed `.oml` files stay byte-exact, and
  checks the `any`-field count against
  [docs/examples/package-json.md](examples/package-json.md).
- **`test_examples_github_actions.py`** -- the same discipline for
  `examples/github-actions/`, plus asserts the read-failure finding
  itself: three fixtures with a bare `on:` key raise `DocumentError`,
  not just fail validation.
- **`test_examples_sitemap.py`** -- the same discipline for
  `examples/sitemap/`, plus asserts the value-refinement finding: an
  out-of-enum `changefreq` and out-of-range `priority` both validate.
- **`test_fuzz.py`** -- property-based fuzzing (Hypothesis) of the Document
  model, codecs, and the OSD parser.
- **`test_cli.py`** -- the `omnist` CLI (`omnist/cli.py`), invoked
  in-process via `main(argv)`: per-command behavior, stdin/stdout/file I/O,
  and clean (non-traceback) exits on malformed input.
- **`test_cli_fuzz.py`** -- property-based crash-freedom fuzzing of the
  CLI's own error-surfacing path (arbitrary input across every command/
  format combination); doesn't re-fuzz the codecs, already covered by
  `test_fuzz.py`.
- **`test_cli_examples.py`** -- executes the exact CLI examples shown in
  [docs/cli.md](cli.md), against the real fixture files in
  [`examples/cli/`](https://github.com/omnist-dev/omnist/tree/master/examples/cli),
  so that page can't silently drift from what running it actually
  produces (same convention as `test_docs.py`, applied to the CLI page).

See also [testing.md](testing.md) for coverage measurement, the fuzzing
methodology, and what CI runs on every push and PR.

## Other top-level files

- **`mkdocs.yml`** + **`.github/workflows/docs.yml`** -- build this `docs/`
  tree into a browsable site (mkdocs-material) and deploy it to GitHub
  Pages on every push to `master` that touches `docs/`, `mkdocs.yml`, or
  `README.md`. Isolated from the package: its dependencies aren't part of
  any `pyproject.toml` extra, so installing `omnist` never pulls in
  documentation-site tooling.
