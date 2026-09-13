# The Schema model & OSD

For the formal Schema model and the full OSD grammar, see
**[spec.omnist.dev's Schema Model chapter](https://spec.omnist.dev/03-schema-model/)**
and **[its OSD Grammar chapter](https://spec.omnist.dev/05-osd-grammar/)**.
This page covers only how OSD and the Schema model map to this library's
Python API.

```python
from omnist import parse_schema, doc

s = parse_schema('''
    record Database { "type": string, "server": string, "port": integer }
    record Service  { "host": string, "port": integer,
                       "databases" [1,]: Database, "tags" [0,]: string }
    root Service
''')
s.validate(doc({"host": "api.internal", "port": 8443,
                "databases": [{"type": "prod", "server": "db1.internal.example.com", "port": 5432}],
                "tags": ["prod", "us-east"]})).ok    # True
```

## Scalar kinds and their Python types

A `Scalar`'s kind determines which Python type a conforming value is held
as. **Validation only checks; deserialization (`materialize`, or `schema=`
on a reader) additionally converts**, succeeding only when the conversion
is value-exact, and raising `ParseError` otherwise.

| Scalar kind | Canonical Python type | What deserialization additionally converts | What it rejects |
|---|---|---|---|
| `string` | `str` | nothing | every non-`str` value |
| `integer` | `int` | a `float` with no fractional part (`4.0 → 4`) | `bool`; a `float` with a fractional part; any `str` |
| `number` | `float` | an `int` is always upgraded to `float` (`3 → 3.0`) | `bool`; any `str` |
| `boolean` | `bool` | nothing (no `"true"`/`"false"` string parsing) | every non-`bool` value |
| `date` | `datetime.date` | an ISO-8601 date string, to a real `date` | a real `datetime` (even though it's a `date` subclass); an invalid date string |
| `time` | `datetime.time` | an ISO-8601 time string, to a real `time` | an invalid time string |
| `datetime` | `datetime.datetime` | a full ISO-8601 timestamp string, to a real `datetime` | a bare ISO date string (satisfies only `date`); an invalid timestamp string |

`bool` never satisfies `integer`/`number` even though Python's `bool` is an
`int` subclass, and `datetime` never satisfies `date` even though it's a
`date` subclass — both scalars stay mutually exclusive on purpose. See
[Schema-directed deserialization](deserialization.md) for the full
conversion pipeline.

## The Python builder

The same schema, built from Python instead of parsed from text. Scalar
instances live under the `t` namespace (and also as top-level names
`STRING`, `INTEGER`, …) and are passed as-is as a field's type:

```python
from omnist import schema, record, field, ref, nullable, t

address = record(field("street", t.string), field("city", t.string))
user = record(
    field("name",     t.string),
    field("nickname", t.string, min=0, max=1),
    field("emails",   t.string, min=1, max=None),     # [1,]
    field("address",  ref("Address")),
    field("note",     nullable(t.string)),            # nullable scalar
)
s2 = schema(ref("User"), User=user, Address=address)

s.equivalent(s2)      # True -- same schema, built two different ways
```

`t.string` / `t.integer` / `t.number` / `t.boolean` / `t.date` / `t.time` /
`t.datetime` are ready-to-use `Scalar` instances; `nullable(scalar)` returns
a nullable copy; `field(label, type, min=1, max=1)`; `record(*fields)`;
`schema(root_ref, **named_definitions)`. `to_osd(schema)` serializes a
`Schema` built either way back to OSD text, and `to_osd(schema, indent=None)`
renders it on a single line instead:

```python
from omnist import to_osd

to_osd(parse_schema('record Car { "license": string }\nroot Car'))
# 'record Car {\n    "license": string,\n}\nroot Car\n'
to_osd(parse_schema('record Car { "license": string }\nroot Car'), indent=None)
# 'record Car { "license": string } root Car\n'
```

Both forms round-trip through `parse_schema` to an equivalent `Schema`.
OSD comments (`#` to end of line) are lexical trivia and never round-trip
through `to_osd()`.

## Schema operations, by Python call

Each schema-algebra operation ([spec.omnist.dev
ch. 6](https://spec.omnist.dev/06-schema-algebra/)) is a method on `Schema`
(or, for `infer`, a top-level function):

| Operation | Python call |
|---|---|
| Validate a document | `schema.validate(doc)` → `ValidationResult(.ok, .errors)` |
| Compatibility / equivalence | `schema.compatible_with(other)`, `schema.equivalent(other)` |
| Canonical minimal form | `schema.normalize()` |
| Drop unreachable/unsatisfiable structure | `schema.prune()` |
| Subschema by label set | `schema.extract(*labels)` — raises `SchemaError` if dropping a label would delete a mandatory field |
| Draft a schema from samples | `infer(samples)` (top-level function) |
| Structural lint | `schema.lint()` → list of `LintFinding(code, severity, location, message)`; see [the CLI reference](cli.md#omnist-schema-lint) |

See [the guide](guide.md#operations) for a worked walkthrough of all of
these, including `infer`'s exact cardinality/nullability rules.

## See also

- [User guide](guide.md) — the practical tour, including the Python
  builder, validation, operations, and inference in full.
- [OML](formats/oml.md) — the native format for the Documents a schema
  validates.
- [A real-life example](example.md) — one order schema validated against
  an OML document, plus a backward-compatibility check.
- [Schema Model chapter](https://spec.omnist.dev/03-schema-model/) and
  [OSD Grammar chapter](https://spec.omnist.dev/05-osd-grammar/) on
  spec.omnist.dev — the formal definitions.
