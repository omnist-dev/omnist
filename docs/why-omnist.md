# Why Omnist

## The thesis

JSON, YAML, TOML, and XML are markup languages that got a schema system
bolted on afterward, if at all -- JSON Schema, XSD, or (for YAML and TOML)
nothing. Because the schema wasn't designed together with the data model,
it can only ever check a document against a shape; it has no way to relate
two shapes to each other.

Omnist designs the Document and the Schema as one formalism from the start
(see the [model spec](design/model.md)): a Document is a canonical edge
list, and a Schema is a closed, exactly-typed grammar over those same
edges. Because every field has exactly one type -- never an enum, a union,
or an open/`Any` escape hatch -- two schemas can be compared structurally,
not just used to check data. That's what makes operations like
`compatible_with` (is every document valid under schema A also valid under
schema B?), `equivalent`, and `infer` *decidable*: there's always exactly
one answer, never "it depends which branch of the union matched."

This is a falsifiable claim. It would be false if a mainstream JSON Schema
library already had a clean way to ask "is this schema change backward
compatible," or if YAML/TOML had any schema system at all. Both are checked
below, against the real libraries -- not assumed.

## Capability matrix

Verified against the actual library/spec for each column (see the worked
comparison below for the `compatible_with` row, and the
[non-goals](#non-goals) section for the XML row).

| Capability | JSON + `jsonschema` | YAML (PyYAML) | TOML (`tomllib`) | XML + XSD | Omnist |
|---|---|---|---|---|---|
| Schema validation | yes | no (no schema concept) | no (no schema concept) | yes | yes |
| Backward-compat checking | no (no API; see below) | no | no | no (no standard API; XSD has no compat operation) | yes (`compatible_with`) |
| Schema-from-examples (inference) | no (no standard API in `jsonschema`) | no | no | no (no standard tool ships with XSD) | yes (`infer`) |
| Type-exact schema-directed deserialization | partial (validates types but doesn't convert/upgrade values) | no (PyYAML's loader infers types itself, not from a schema) | no (`tomllib` likewise infers types itself, not schema-directed) | partial (XSD types validate; bindings to native types need a separate codegen tool, e.g. `xmlschema`/`xsdata`) | yes (`schema=` upgrades leaves only when value-exact) |
| Native lossless round-trip | yes (within JSON's own type system) | yes (within YAML's own type system) | yes (within TOML's own type system) | no (attributes/namespaces/mixed content not modeled by Omnist; see non-goals) | yes (OML only -- JSON/YAML/TOML/XML round-trip within *their own* type systems, same as the other columns) |
| Multi-format read/write (one model, many formats) | no (`jsonschema` only ever speaks JSON) | no (PyYAML only speaks YAML) | no (`tomllib` only speaks TOML, and is read-only) | no (XML tooling only speaks XML) | yes (`read_*`/`write_*` for JSON/YAML/TOML/XML/OML all target one Document model) |
| Subschema extraction (minimal schema for a label subset) | no (no packaged operation in `jsonschema`/the JSON Schema spec; `$ref`/`$defs` can be hand-pruned, not derived) | no (no schema concept) | no (no schema concept) | no (no standard XSD tool computes this; component reuse via `xs:include`/`xs:import` is manual) | yes (`Schema.extract()`, paper Algorithm 5) |

Notes on cells double-checked while writing this table:

- **Subschema extraction row, hedged deliberately.** This check is against
  general-purpose JSON Schema/XSD tooling, not the whole schema-technology
  landscape -- Avro and Protobuf don't really have an analogous "trim to a
  label subset" operation either (their compatibility tooling is about
  reader/writer schema evolution, not extraction), and CUE's `cue export`/
  unification *can* narrow a value to a subset of fields but that's value
  extraction against a concrete instance, not deriving a minimal schema
  purely from a permissible label set the way Algorithm 5 does. If there's
  a packaged tool that does exactly this and this claim turns out wrong,
  that's a documentation bug -- open an issue.

- **PyYAML and `tomllib` have no schema concept whatsoever** -- confirmed by
  inspecting their public APIs (`yaml.safe_load`/`dump` and
  `tomllib.load`/`loads`); there is nothing resembling validation,
  comparison, or inference to even attempt.
- **`jsonschema` 4.26.0's public API** (`validate`, the `DraftNValidator`
  classes, `FormatChecker`) is entirely about checking one document against
  one schema. There is no method, function, or companion package shipped
  with it for comparing two schemas to each other.
- **XSD** has a `validate`-only contract in every mainstream tool we're
  aware of (e.g. `lxml.etree.XMLSchema`); there's no standard "is this XSD
  change backward compatible" operation, and no inference tool ships with
  the spec.

## Worked comparison: `compatible_with`

Omnist:

```python
from omnist import parse_schema

v1 = parse_schema('record R { "host": string }\nroot R')
v2 = parse_schema('record R { "host": string, "port" [0,1]: integer }\nroot R')

v1.compatible_with(v2)   # True  -- every v1 document is still valid under v2
v2.compatible_with(v1)   # False -- a v2 document with a port isn't valid under v1
```

One method call. The answer is decidable because every Omnist field has
exactly one type (Section 5 of the [model spec](design/model.md)) -- there's
no union or enum branch that could make "is A's document set a subset of
B's" ambiguous.

`jsonschema` (the most common Python JSON Schema validator, version 4.26.0,
checked directly in this repo's venv): there is no `compatible_with`,
`is_subset`, or any comparison API at all. The library's entire public
surface (`validate`, the `DraftNValidator` family, `FormatChecker`) is
shaped around checking *one document* against *one schema* -- never two
schemas against each other:

```python
import jsonschema

v1 = {
    "type": "object",
    "properties": {"host": {"type": "string"}},
    "required": ["host"],
    "additionalProperties": False,
}
v2 = {
    "type": "object",
    "properties": {"host": {"type": "string"}, "port": {"type": "integer"}},
    "required": ["host"],
    "additionalProperties": False,
}

# jsonschema.validate(instance, schema) only checks a document against
# ONE schema. To approximate "is v1 backward compatible with v2" you'd
# have to hand-write your own diff over the two schema dicts yourself --
# walking properties, required, additionalProperties, and (in the
# general case) oneOf/anyOf/$ref branches, recursively, with no
# library support for any of it. jsonschema gives you no starting point.
jsonschema.validate({"host": "x"}, v1)  # only proves a fact about ONE document
```

This isn't a contrived gap: `jsonschema`'s own docs and API surface confirm
it's a validator, not a schema-algebra library. Searching the package
index for the natural alternative (`pip index versions jsonschema`, and
`pip list` for anything diff/compat-shaped already installed) turned up no
companion package that adds this. The claim survives unsoftened: a
project that wants schema-version compatibility checking with `jsonschema`
has to build that logic itself, by hand, over the raw schema dicts --
recursing through `oneOf`/`anyOf`/`$ref` in the general case -- where
Omnist ships it as one method that's correct by construction because the
type system has no branches to get wrong.

## Non-goals

Omnist is not trying to be a bigger hammer than it is. Specifically:

- **No value-domain constraints.** Omnist has no regex/pattern matching, no
  numeric ranges, no custom predicates (JSON Schema's `pattern`, `minimum`,
  `format: email`, and friends). A field's type is exactly one of seven
  scalar kinds (optionally nullable) -- never a refinement of a kind. If
  you need "a string matching this regex," Omnist isn't the tool.
- **No enums or unions.** "Either an integer or the string `unlimited`" or
  "one of `a`, `b`, `c`" can't be expressed. This is deliberate (see
  [the model spec, Section 2](design/model.md#2-why-the-model-looks-this-way)):
  a value that matches more than one candidate has no principled Python
  type to materialize to. If your data needs literal-value validation,
  you'll need something else for that part.
- **Not a replacement for XML with attributes, mixed content, or
  namespaces.** This was checked directly against this repo's `read_xml`/
  `check_xml`, not assumed:

  ```python
  from omnist import read_xml, check_xml

  read_xml('<a x="1"><b>hi</b></a>')
  # [('a', [('b', 'hi')])]   -- the x="1" attribute is silently gone

  check_xml('<a x="1"><b>hi</b></a>')
  # no adjustments -- check_xml reports nothing about the dropped attribute
  ```

  Namespace prefixes are stripped the same way: an element like
  `foo:b` under an `xmlns:foo` binding reads as plain `b` -- the prefix and
  its namespace binding both vanish, with no warning. Omnist's Document
  model has no edge shape for attributes, mixed text+element content, or
  namespace-qualified names, so none of the three survive a round trip. If
  your XML relies on attributes or namespaces as meaningful data (not just
  structure), Omnist will silently lose it -- use a real XML library
  (`lxml`, `xml.etree`) for that data instead. This is a genuine, named
  limitation for attributes and namespaces specifically: nothing in Omnist
  currently detects or warns about either being dropped. (A separate issue
  may exist to track making that loss visible at read/check time; this page
  only documents the current behavior.)

  **Mixed content is the one exception: it's rejected, not silently
  dropped.** As of `read_xml` in v0.2.23+, non-whitespace text alongside
  child elements raises `ParseError` naming the element, rather than being
  discarded:

  ```python
  from omnist import read_xml, ParseError

  try:
      read_xml("<p>Hello <b>world</b></p>")
  except ParseError as e:
      print(e)   # $: mixed content (text alongside child elements) ...
  ```

  See [the XML format page](formats/xml.md#mixed-content-is-rejected).
- **No structureless escape hatches, by design, not by oversight.** There's
  no `Any` type and no open/wildcard record. This isn't a missing feature
  on the roadmap -- it's the property that makes `compatible_with`,
  `equivalent`, `normalize`, and `infer` well-defined in the first place
  (see the [thesis](#the-thesis) above). If you need a schema that accepts
  arbitrary, unstructured data, Omnist's schema model isn't going to do
  that for you.

## Performance

Measured on an ordinary laptop (WSL2, Python 3.13), so you can decide
whether Omnist's pure-Python implementation fits your workload — the point
is transparency, not benchmarketing. A 100k-edge document (33k records of
three fields each; ~1.5MB as JSON, ~1.7MB as OML):

| Operation | Time |
|---|---|
| build the Document (`doc(...)`) | ~0.3s |
| `validate` against a schema | ~0.3s |
| `infer` a schema from it | ~0.1s |
| JSON write / read | ~0.5s each |
| OML write | ~0.25s |
| OML read | ~1s |

Schema operations on a 200-record schema: `normalize` ~0.2s,
`compatible_with` ~3ms. Everything scales linearly (the one quadratic
codepath ever found — the original OML tokenizer — was caught by review and
fixed in v0.2.21; a ratio-bound regression test now guards it). OML reading
used to be the one outlier here by an order of magnitude; a single-pass
rewrite around one master regex (issue #168, v0.2.27) cut it to roughly 2x
JSON's read time — much closer, though JSON's C-backed parser is still
faster for latency-sensitive, megabyte-scale streaming. Use JSON as the
wire format there, and OML where humans read the files.

## See also

- [Model spec](design/model.md) -- the formal Document and Schema
  definitions this page's claims are checked against.
- [Schema model & OSD](schema.md) -- `compatible_with`, `equivalent`,
  `normalize`, and `infer` in full.
- [Formats](formats/overview.md) -- the per-format mapping and caveats,
  including [XML](formats/xml.md)'s in more detail.
