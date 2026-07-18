# Omnist documentation

Start here, in roughly this order:

| Doc | What it covers |
|---|---|
| **[Quickstart](quickstart.md)** | The shortest possible tour — one OML snippet, one schema, `validate()`, `infer()`. Read this if you just want to see it work. |
| **[Why Omnist](why-omnist.md)** | The differentiation case: a falsifiable thesis, a verified capability matrix against JSON/YAML/TOML/XML, a worked `compatible_with` comparison against `jsonschema`, and the honest non-goals. |
| **[User guide](guide.md)** | The practical tour — documents, OML, OSD and the Python builder, validation, the schema operations, codecs, inference. Read this first. |
| **[OML](formats/oml.md)** | Omnist's own format: the only one with zero adjustments, and how it maps onto the Python Document. |
| **[The Schema model & OSD](schema.md)** | Omnist's other central feature: `record` definitions, cardinality, the Python builder, and the comparison/inference operations. |
| **[A real-life example](example.md)** | One order schema validated against an order written in OML, plus a backward-compatibility check. |
| **[Real-world examples: overview](examples/index.md)** | Four real, external formats — pyproject.toml, package.json, a GitHub Actions workflow, sitemap.xml — each run end to end, with a comparison table and the four gap categories OSD's schema algebra can't express. |
| **[API reference](api.md)** | Every public name: `Doc`, `Schema`, the builders, codecs, validation results, and exceptions, with signatures. |
| **[CLI](cli.md)** | The `omnist` command-line tool, fully implemented: `format`, `convert`, `check`, `validate`, `infer`, and seven `schema` subcommands (`format`/`normalize`/`prune`/`is-empty`/`extract`/`compatible-with`/`equivalent`), specified in [the CLI spec](design/cli-spec.md). |
| **[Schema-directed deserialization](deserialization.md)** | What changes (and what doesn't) about a Document's Python types when a schema is, vs. isn't, passed to a reader — the conversion rules, and why they're unambiguous. |
| **[Formats](formats/overview.md)** | How each format maps to the model and its caveats — [OML](formats/oml.md) · [JSON](formats/json.md) · [YAML](formats/yaml.md) · [TOML](formats/toml.md) · [XML](formats/xml.md). |
| **[Model spec](design/model.md)** | The formal definitions of the Document and Schema models — self-contained, no paper required. |
| **[OML-Core grammar](design/oml-grammar.md)** | The formal ABNF grammar for OML, verified against the parser: tokens, disambiguation rules, escaping, and documented limits. |
| **[OSD grammar](design/schema-osd-grammar.md)** | The formal ABNF grammar for OSD, verified against the parser: keywords, field syntax, cardinality, and the seven scalars. |
| **[Glossary](glossary.md)** | One definition per term used across the docs and code, grouped by concept area. |
| **[Testing](testing.md)** | The test suite: layout, coverage tooling and target, the fuzzing approach, and what CI runs. |
| **[Repo layout](layout.md)** | How the repo itself is organized: `omnist/*.py` module responsibilities, the docs page map, and the test file map. |

## The model in one minute

- A **Document** is a *tree*: a node is either a scalar value or an **ordered
  list of labeled edges**. An array is just a label that repeats — so the same
  Document represents JSON, YAML, TOML, XML, and **OML** (Omnist Markup
  Language, Omnist's own format).
- A **Schema** is named **`record`** definitions (closed named fields, each
  with a cardinality `[min,max]`), where each field's type is always exactly
  one fixed scalar (optionally nullable) or one `Ref` to a named record —
  referenced by name for reuse and recursion. Written as **OSD** (Omnist
  Schema Definition), Omnist's own schema text syntax.
- **Validate** a Document against a schema, **compare** two schemas for
  backward-compatibility (`compatible_with`), or **infer** a schema from
  examples.
- Readers accept an optional `schema=` to upgrade leaves (ISO strings to real
  `date`/`time`/`datetime`, numeric types) to match the schema, when the
  conversion is value-exact.

```python
from omnist import parse_schema, doc

s = parse_schema('''
    record Database { "engine": string, "port": integer }
    record Service  { "host": string, "port": integer, "database": Database }
    root Service
''')
s.validate(doc({"host": "api.internal", "port": 8443,
                "database": {"engine": "postgres", "port": 5432}})).ok   # True
```
