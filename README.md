# Omnist

[![tests](https://github.com/omnist-dev/omnist/actions/workflows/test.yml/badge.svg)](https://github.com/omnist-dev/omnist/actions/workflows/test.yml)
[![pypi](https://img.shields.io/pypi/v/omnist)](https://pypi.org/project/omnist/)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](#installation)
[![license](https://img.shields.io/badge/license-Apache--2.0-lightgrey)](LICENSE)
[![status](https://img.shields.io/badge/status-beta-yellow)](#status)

**Omnist** ("omni-structure") is **one canonical data model for JSON, YAML,
TOML, XML, and its own native OML (Omnist Markup Language)** — read any of
them into a single tree, validate it against a schema, compare schema
versions, and write it back out to any of the others.

```python
from omnist import parse_schema, doc

s = parse_schema('''
    record Member { "name": string, "role": string }
    record Team   { "name": string, "members" [1,]: Member }
    root Team
''')

s.validate(doc({"name": "Platform",
                "members": [{"name": "Ann", "role": "dev"}]})).ok    # True
```

## Why Omnist

Three things you can do with Omnist that are genuinely hard anywhere else:

- **Gate schema changes in CI.** `v1.compatible_with(v2)` answers "does every
  document the old schema accepts still validate under the new one?" with a
  decidable **yes or no** — an algorithm with a proof behind it, not a
  heuristic or a sampled guess. Put it in a pipeline and schema evolution
  stops being a code-review judgment call.
- **One model across five formats.** Read JSON, YAML, TOML, XML, or
  [OML](docs/formats/oml.md) into the *same* tree, validate it against the
  *same* schema, write it back out to any of the others — one library, one
  mental model, and a written report of anything a lossy format had to
  adjust.
- **Cut a big schema down to what one service needs.** `schema.extract(...)`
  computes the *minimal* subschema recognizing only the labels you keep —
  the operation that trimmed industrial XML schemas to a fraction of their
  size in the research this library grew from.

What makes those possible is a deliberately small formal model (inspired by
Lee & Cheung, CIKM 2010):

- A **Document** is a *tree* — an ordered list of labeled edges. Arrays are
  just repeated labels, so the *same* Document represents JSON, YAML, TOML,
  XML (including its interleaved repeated elements), and OML — Omnist's own
  format, the only one with zero loss in either direction.
- A **Schema** is named `record` definitions (closed named fields, each with
  a cardinality), where every field's type is always exactly one fixed
  scalar (optionally nullable), one `Ref` to a named record — referenced
  by name for reuse and recursion — or `any`, an explicitly-marked
  unchecked subtree. Written as **OSD** (Omnist Schema Definition).
- **Closed by default; open only where explicitly marked** — records are
  closed, and scalar types are never composed into enums or unions. The
  one deliberate opening is the `any` type (v0.5.0), and it carries its
  cost openly: compatibility checking ends exactly where `any` begins.
  That discipline is not a constraint bolted on top; it is what makes
  `compatible_with`, `equivalent`, `normalize`, `extract`, and `infer`
  well-defined, decidable operations instead of best-effort heuristics.
  See [why Omnist](docs/why-omnist.md) for the case in full — including a
  verified capability matrix and the honest non-goals.

### Boringly correct

The claims above are checked, not asserted: **100% line coverage**, a
**`mypy --strict` CI gate**, **property-based fuzzing**, **formal ABNF
grammars** verified against the parsers, **every documentation example
executed in CI**, and the schema algebra verified **three independent
ways** — bidirectional inclusion, the paper's minimize-and-isomorphism
theorem, and brute-force enumeration against set-theoretic ground truth.
Performance is measured and published, not implied: a 100k-edge document
validates in about a third of a second
([the numbers](docs/why-omnist.md#performance)). See
[testing](docs/testing.md) for how the suite is built.

The model is defined formally in
[docs/design/model.md](docs/design/model.md); see
[the quickstart](docs/quickstart.md) for the shortest possible example, or
[the user guide](docs/guide.md) for the practical tour.

## A 60-second tour

```python
from omnist import Doc, parse_schema, infer, doc, read_json

# OML is omnist's own format -- see docs/formats/oml.md
Doc.from_oml('id: 1\ntags: "a"\ntags: "b"\n').to_oml()

# converting from other formats is just read one, write another
Doc.from_json('{"id": 1, "tags": ["a", "b"]}').to_yaml()

# describe a shape and check data against it; errors carry exact paths
s = parse_schema('record R { "id": integer, "tags" [0,]: string }\nroot R')
print(s.validate(doc({"id": "x", "tags": ["a"]})))
#   invalid:
#     at $.id: expected integer, got string ('x')

# learn a schema from examples
print(infer([doc({"id": 1, "tags": ["a"]})]).to_osd())
#   record Root {
#       "id": integer,
#       "tags": string,
#   }
#   root Root

# is a schema change backward-compatible? (operations are Schema methods)
v1 = parse_schema('record R { "host": string }\nroot R')
v2 = parse_schema('record R { "host": string, "port" [0,1]: integer }\nroot R')
v1.compatible_with(v2)        # True -- adding an optional field is safe

# schema-directed deserialization: upgrade leaves to match the schema
s2 = parse_schema('record R { "d": date }\nroot R')
read_json('{"d": "2024-01-01"}', schema=s2)   # [('d', datetime.date(2024, 1, 1))]
```

Run the full demo: `python3 examples/canonical_model.py`.

## Installation

Requires **Python 3.11+** (it uses the standard-library `tomllib`). The core and
JSON support have no dependencies.

```bash
pip install omnist                      # core + JSON
pip install omnist[all]                 # + pyyaml, tomli_w, defusedxml
```

Installing also provides an `omnist` CLI command; see [the CLI
docs](docs/cli.md).

Or from a checkout:

```bash
git clone https://github.com/omnist-dev/omnist.git
cd omnist
python3 -m venv .venv && source .venv/bin/activate
pip install .                    # core + JSON
pip install pyyaml tomli_w defusedxml   # YAML / writing TOML / hardened XML
```

## Documentation

Full index: **[docs/](docs/README.md)**, also browsable as a site at
**[omnist.dev](https://omnist.dev/)**.

- **[Quickstart](docs/quickstart.md)** — the shortest possible example: one
  OML snippet, one schema, `validate()`, `infer()`.
- **[Why Omnist](docs/why-omnist.md)** — the differentiation case: a
  falsifiable thesis, a verified capability matrix against JSON/YAML/TOML/XML,
  a worked `compatible_with` comparison against `jsonschema`, and the honest
  non-goals (including XML attribute/namespace dropping).
- **[User guide](docs/guide.md)** — the practical tour: documents,
  [**OML**](docs/guide.md#oml--the-native-format) (the native format),
  [**OSD**](docs/guide.md#schemas--osd), the Python builder,
  validation, operations, other codecs, inference.
- **[OML](docs/formats/oml.md)** — Omnist's own format, designed alongside the
  model so every Document round-trips with zero adjustments, and how it maps
  onto the Python Document.
- **[The Schema model & OSD](docs/schema.md)** — Omnist's other central
  feature: `record` definitions, cardinality, the Python builder, and the
  comparison/inference operations.
- **[API reference](docs/api.md)** — every public name, with signatures.
- **[CLI](docs/cli.md)** — the `omnist` command-line tool.
- **[Schema-directed deserialization](docs/deserialization.md)** — what
  changes (and what doesn't) about a Document's Python types when a schema
  is, vs. isn't, passed to a reader.
- **[A real-life example](docs/example.md)** — one order schema validated against
  documents in JSON, YAML, TOML, and XML, plus a compatibility check.
- **[Formats](docs/formats/overview.md)** — how each format maps to the model and
  its caveats ([OML](docs/formats/oml.md) · [JSON](docs/formats/json.md) ·
  [YAML](docs/formats/yaml.md) · [TOML](docs/formats/toml.md) ·
  [XML](docs/formats/xml.md)).
- **[Model spec](docs/design/model.md)** — the formal Document and Schema models,
  self-contained and plain (no paper required).
- **[Glossary](docs/glossary.md)** — one definition per term used across the
  docs and code, grouped by concept area.
- **[Testing](docs/testing.md)** — the test suite layout, coverage tooling and
  target, the fuzzing approach, and what CI runs.
- **[Repo layout](docs/layout.md)** — how the repo itself is organized:
  `omnist/*.py` module responsibilities, the docs page map, and the
  test file map.

## Status

Omnist is **beta**. The surfaces you build on — the Document model, the OSD
and OML grammars, the public API importable from `omnist`, and the error
types — change only through a deprecation cycle; see the
[stability policy](docs/stability.md) for exactly what is covered and what
may still change. Beta is not 1.0: 1.0 remains gated on the `any`-type
openness decision, spelled out in the same policy. See the PyPI badge above
(or [CHANGELOG.md](CHANGELOG.md)) for the current version.

Feedback and bug reports welcome:
<https://github.com/omnist-dev/omnist/issues>. See [SECURITY.md](SECURITY.md) for
the trust model if you parse untrusted input.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Background

The model is **inspired by** Lee & Cheung,
[*"XML Schema Computations: Schema Compatibility Testing and Subschema
Extraction"*](docs/paper/Lee-Cheung-2010-XML-Schema-Computations-CIKM.pdf)
(CIKM 2010), simplified for the JSON family of formats. You don't need the
paper to use Omnist — the [model spec](docs/design/model.md) is self-contained.
