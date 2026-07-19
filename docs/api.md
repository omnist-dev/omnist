# API reference

Everything importable from `import omnist`. Types: a **Document** is held by a
`Doc`; a **Schema** is a `root` reference plus named `Record` definitions, where
a field's type is always exactly one `Scalar` or one `Ref`. See the
[user guide](guide.md) for narrative and the
[model spec](design/model.md) for the formal definitions.

```python
import omnist
omnist.__version__        # "0.7.8"
```
<!-- verified-by: tests/test_docs.py::test_docs_version_examples_match_live_version -->

---

## Documents

### `doc(value) -> Doc`
Build a `Doc` from a plain Python value. A `dict` becomes an edge list; a key
whose value is a `list` expands into one edge per item (a repeated label). A
scalar becomes a leaf. A bare list, an array-of-arrays, a non-string key, a
cycle, or nesting past the depth limit raises `DocumentError`.

### `class Doc`
A guarded handle on a Document node — either a **leaf** (a scalar value) or an
**internal node** (an ordered list of `(label, child)` edges).

**Construction**

| | |
|---|---|
| `Doc.of(value)` | same as `doc(value)` |
| `Doc.from_oml(text)` | read **OML**, Omnist's own format (see [the guide](guide.md#oml--the-native-format)) |
| `Doc.from_json(text)` / `from_yaml` / `from_toml` / `from_xml` | read a format string |
| `Doc.from_format(name, text)` | read by format name (`"json"`, `"oml"`, …) |

**Shape & navigation**

| | |
|---|---|
| `.is_leaf` *(property)* | `True` for a scalar leaf |
| `.value` *(property)* | the scalar of a leaf (raises on an internal node) |
| `.edges() -> list[(str, Doc)]` | the ordered `(label, child)` edges |
| `.labels() -> list[str]` | distinct labels, in first-seen order |
| `.get(label) -> list[Doc]` | all children under `label` (a list — labels may repeat) |
| `.get_one(label) -> Doc` | the single child under `label` (raises unless exactly one) |
| `.count(label) -> int` | how many edges carry `label` |
| `.child(label) -> Doc` | a cursor to the single child (editable if it's a node) |

**Editing** (mutates the edge list; returns `self` for chaining)

| | |
|---|---|
| `.add(label, value)` | append an edge — a repeated label is how an array grows |
| `.set(label, value)` | replace all edges under `label` with a single new edge (positioned at the first old occurrence); `set` = `remove` + `add` |
| `.remove(label)` | drop every edge under `label` |

**Export**

| | |
|---|---|
| `.to_data()` | the canonical Python form — a scalar, or a list of `(label, …)` tuples |
| `.to_grouped()` | a JSON-shaped projection: same-label edges grouped into a list |
| `.to_oml(**opts)` | serialize to **OML** — the only format with zero adjustments; `arrays=True` collapses same-label runs into `[...]` array syntax (default `False`, byte-identical to today) |
| `.to_json(**opts)` / `.to_yaml()` / `.to_toml()` / `.to_xml()` | serialize to a format |
| `.to_format(name, **opts)` | serialize by format name |
| `.check_oml() -> WriteReport` | always empty — see [OML](guide.md#oml--the-native-format) |
| `.check_json()` / `.check_yaml()` / `.check_toml()` / `.check_xml() -> WriteReport` | simulate the matching `to_*`, no output |
| `.check_format(name) -> WriteReport` | simulate `to_format(name)`, no output (needs the format's `check`) |
| `.validate(schema) -> ValidationResult` | shorthand for `schema.validate(self)` |

`.to_*`/`.check_*` raise `WriteError` past 200 levels of nesting;
`.to_data()`/`.to_grouped()` raise `DocumentError` instead — see
[Adjustment reports](#adjustment-reports-lossy-writes) below.

`Doc` also supports `==` (compares the underlying data, against a `Doc` or a
plain value).

---

## Schemas

### `parse_schema(text) -> Schema`
Parse OSD text (`record` / `root`) into a `Schema`. Raises
`SchemaError` on malformed text or an undefined reference. See the
[OSD section of the guide](guide.md#schemas--osd).

### `to_osd(schema, *, indent=4) -> str`
Serialize a `Schema` back to OSD text. `parse_schema(to_osd(s))` is equivalent
to `s`. `indent=None` renders a single-line, machine-oriented form instead
of the pretty-printed default; both round-trip through `parse_schema`.

### `infer(samples, root_name="Root", *, allow_any=False) -> Schema`
Draft a schema from example Documents (`Doc`s or plain values). Cardinality
follows observed counts (present in every sample → required; sometimes absent →
optional; seen more than once → array); object children become nested named
records.

A scalar field's `Scalar` is determined from the kinds of its observed
values: `integer` and `number` collapse to `number` (the one subset relation
between scalars); any *other* mix of kinds for the same field (e.g. an
`integer` and a `string`) raises `SchemaError` — a field infers to exactly
one scalar, never a composition. The field is nullable iff any sample's
value was `null`, independent of which kind(s) were observed; if a field
occurred but every observed value was `null`, `infer` defaults to a
nullable `string`. The full algorithm, with the exact collapse and default
rules, is
[model.md §11](design/model.md#11-inference-determining-a-fields-scalar-from-samples).

By default (`allow_any=False`) both conflict points — an object/scalar mix
for one label, and a scalar-of-more-than-one-kind — raise `SchemaError`, so
`infer` never emits `any`. Passing `allow_any=True` opts in to turning those
two failure points into `any` fields instead, for bootstrapping a draft
schema from messy or polymorphic data. The fallback happens at the narrowest
node (the conflicting field only); clean nested structure still infers as a
record. Wherever `infer` fell back, the result has vacuous compatibility at
that field, exactly like a hand-written `any`.

### `infer_with_report(samples, root_name="Root", *, allow_any=False) -> tuple[Schema, list[AnyFallback]]`
Same as `infer`, but also returns the list of fields it opened as `any`.
`infer(...)` is a thin wrapper that returns just the schema. The list is
empty when nothing was opened (always, when `allow_any=False`). Each
`AnyFallback` is a frozen dataclass:

- `location: str` — the opened field, as `RecordName.label`.
- `reason: str` — either `"mixes objects and values"` or
  `"values of more than one scalar kind (…)"` (kinds sorted, comma-joined).

```python
schema, fallbacks = infer_with_report(samples, allow_any=True)
for fb in fallbacks:
    print(fb.location, "—", fb.reason)
```

### The Python builder

| Function | Builds |
|---|---|
| `record(*fields) -> Record` | a closed record from `Field`s |
| `field(label, type, min=1, max=1) -> Field` | one field; `type` is a `Scalar` (e.g. `t.string`), a `Ref`, or `t.any`; `max=None` is unbounded |
| `nullable(scalar) -> Scalar` | a copy of `scalar` that also accepts `null` (the `?` form). Raises `SchemaError` on `t.any` — `any` already includes null |
| `ref(name) -> Ref` | a reference to a named record |
| `schema(root, **env) -> Schema` | assemble a `Schema` (`root` is a `Ref` or a name string) |
| `t` | the type namespace: `t.string`, `t.integer`, `t.number`, `t.boolean`, `t.date`, `t.time`, `t.datetime` — ready-to-use `Scalar` instances — plus `t.any`, the [`any` type](schema.md#the-any-type) singleton (an `AnyType`, exported for `isinstance` checks); all passed as-is as a field's type |

```python
from omnist import schema, record, field, ref, nullable, t
s = schema(ref("User"),
           User=record(field("name", t.string),
                       field("note", nullable(t.string), min=0, max=1),
                       field("tags", t.string, min=0, max=None)))
```

### `class Schema`
`Schema(root: Ref, env: dict[str, Record] = None)` — a root reference plus
named record definitions. Raises `SchemaError` if `root` isn't a `Ref`, if any
`env` entry isn't a `Record`, or if a `Ref` (the root or one inside a field)
names an entry not present in `env`.

| Method | |
|---|---|
| `.validate(doc) -> ValidationResult` | check a `Doc` against this schema |
| `.accepts(doc) -> bool` | `validate(doc).ok` |
| `.compatible_with(other) -> bool` | every document this accepts, `other` also accepts (backward-compat); **vacuously `True`** if this schema is empty (see below) |
| `.equivalent(other) -> bool` | both accept exactly the same documents; two distinct empty schemas are always equivalent |
| `.normalize() -> Schema` | canonical minimal equivalent schema — fewest env records, unique up to record naming (partition refinement, i.e. `prune()` then merge equivalent records) |
| `.is_empty() -> bool` | `True` iff the root record is unsatisfiable — no finite document conforms (e.g. a mandatory ref cycle) |
| `.prune() -> Schema` | an equivalent schema with unreachable records, never-emittable (`max == 0`) fields, and optional-but-unsatisfiable fields removed |
| `.extract(*labels) -> Schema` | minimal subschema recognizing only documents built from `labels` (paper Algorithm 5); raises `SchemaError` if dropping a non-kept label deletes a mandatory field with no valid subschema left — see [the schema doc](schema.md#subschema-extraction) |
| `.to_osd(*, indent=4) -> str` | serialize back to OSD; `indent=None` for a single-line, compact form |
| `.root`, `.env` | the root `Ref` and the name→record map |
| `.resolve(t) -> Record` | follow a `Ref` chain to a `Record` |

**Vacuity note.** `compatible_with`/`equivalent` are defined over the set of
documents a schema accepts. An unsatisfiable schema (`is_empty()` is
`True`) accepts no documents at all, so it is trivially `compatible_with`
any other schema, and any two empty schemas are `equivalent` to each other
regardless of how their record definitions look. See
[the schema doc](schema.md#empty-schemas) and
[model spec §12](design/model.md#12-satisfiability-and-pruning).

### Definition & type classes

These are produced by OSD and the builder; you can also construct them directly.

- **`Record(fields: list[Field])`** — a closed record. `.fields`;
  `.field(label) -> Field | None`.
- **`Field(label, type, min=1, max=1)`** — one labeled edge rule. `.label`,
  `.type` (a `Scalar` or a `Ref`), `.min`, `.max` (`None` = unbounded).
- **`Scalar(name, nullable=False)`** — one of the seven fixed value types,
  optionally nullable; never composed with another kind or a literal value.
  `.name` (one of `"string"`, `"integer"`, `"number"`, `"boolean"`, `"date"`,
  `"time"`, `"datetime"`), `.nullable` (bool).
- **`Ref(name)`** — a reference to a named record in the schema's `env`.
- Ready-to-use instances: `STRING`, `INTEGER`, `NUMBER`, `BOOLEAN`, `DATE`,
  `TIME`, `DATETIME` (also under `t.*`).

---

## Validation results

### `class ValidationResult`
Returned by `Schema.validate`.

| | |
|---|---|
| `.ok` *(property)* | `True` if the document conforms |
| `bool(result)` | same as `.ok` |
| `.errors -> list[Error]` | every failure |
| `str(result)` | a readable multi-line summary |

### `class Error`
A named tuple `Error(path, message, code)` — unpacks as `(path, message,
code)` and exposes `.path` (e.g. `"$.order.items"`), `.message`, and a
stable machine-readable `.code`:

| code | meaning |
|---|---|
| `unexpected-field` | a label the (closed) record doesn't declare |
| `cardinality` | a label occurs outside its `[min,max]` range |
| `type-mismatch` | a value doesn't match the field's scalar type |
| `null-not-allowed` | `null` for a non-nullable (`?`-less) scalar |
| `shape-mismatch` | an object where a value was expected, or vice versa |

The codes are part of the API contract — match on `.code`, not on message
text, when reacting to failures programmatically. `str(result)` output is
unchanged (codes don't appear in the human-readable summary).

```python
r = s.validate(doc({"id": "x"}))
if not r.ok:
    for e in r.errors:
        print(e.path, e.code, e.message)
```

---

## Reading & writing formats

Low-level codecs over the canonical node form (a scalar, or a list of
`(label, node)` edges). Most code uses `Doc.from_*` / `Doc.to_*` instead.

| | |
|---|---|
| `read_oml(text)` / `read_json` / `read_yaml` / `read_toml` / `read_xml` | parse → a node |
| `write_oml(node, *, indent=2, arrays=False)` | a node → **OML**, losslessly — no `strict`/`report` needed (see below); `indent=None` for a single-line, compact form; `arrays=True` collapses any maximal run of ≥ 2 consecutive same-label edges into `label: [v1, v2, ...]` array syntax (a run of 1 stays a plain scalar edge, pretty mode never wraps an array onto multiple lines); default `arrays=False` is byte-identical to `write_oml` without the parameter at all |
| `write_json(node, *, strict=False, report=None, indent=None)` | a node → JSON (groups same-label edges) |
| `write_yaml(node, *, strict=False, report=None)` | a node → YAML |
| `write_toml(node, *, strict=False, report=None)` | a node → TOML |
| `write_xml(node, *, strict=False, report=None)` | a node → XML |
| `check_oml(node)` | always an empty `WriteReport` — OML holds every node shape exactly |
| `check_json(node)` / `check_yaml` / `check_toml` / `check_xml` | simulate a write; return a `WriteReport`, no output |

`read_yaml`/`write_yaml` need `pyyaml`; `write_toml` needs `tomli_w`; `read_xml`
requires `defusedxml` (raises `ImportError` if it's missing). See
[Formats](formats/overview.md) for per-format mapping and caveats.

**Depth limit on write.** Every `write_*`/`check_*` above raises `WriteError`
(naming the limit) if a Document nests past 200 levels — the same shared
limit the readers already enforce on parse. `Doc.to_data()`/`.to_grouped()`
raise `DocumentError` instead, for the same reason. The one residual
caveat: a `Doc` built directly from a raw hand-assembled node (bypassing
`Doc.of`/`build_node`/the readers, which guard depth themselves) can still
overflow `validate`/`infer` on such a node — accepted, documented behavior,
not a bug.

### Schema-directed deserialization

Pass `schema=` to any reader (or `Doc.from_json` / `Doc.from_yaml` /
`Doc.from_toml` / `Doc.from_xml`) for a **guaranteed-conforming** Document:
each leaf is upgraded to match what the schema declares wherever the
conversion is value-exact, and the result's shape (closed fields,
cardinality) is checked too — raising `ParseError`, with every problem
found, if it can't be made to conform. See
[Schema-directed deserialization](deserialization.md) for the full
explanation, the conversion rules, and `materialize`.

| | |
|---|---|
| `read_oml(text, schema=...)` / `read_json` / `read_yaml` / `read_toml` / `read_xml` | parse → a node, upgrading leaves to match `schema` |
| `materialize(node, schema) -> node` | apply the same upgrade directly to an already-parsed node |

### Adjustment reports (lossy writes)

Writing to a format that can't hold every value (TOML has no `null`; JSON/XML
have no date type) is **lenient by default**: the writer adjusts the value and
records it. `Doc.to_*` and `write_*` accept the same two options:

| | |
|---|---|
| `strict=True` | raise `WriteError` (carrying the report) if anything was adjusted |
| `report=a_WriteReport` | collect the adjustments into it, without raising |

```python
from omnist import doc, WriteReport, WriteError

d = doc({"a": 1, "b": None})
d.to_toml()                          # 'a = 1\n' -- 'b' dropped, silently

rep = WriteReport()
d.to_toml(report=rep)
[(a.code, a.severity) for a in rep]  # [('null.omitted', 'warning')]

d.to_toml(strict=True)               # raises WriteError
```

### `class WriteReport`
Every adjustment a writer made. `.warnings` / `.errors` (lists of
`Adjustment`); `bool(report)` is `True` when there are no `"error"`-severity
entries (warnings are fine) — `if check_toml(node): ...` reads as "safe to
write." Iterable; `str(report)` is a readable multi-line summary.

### `class Adjustment`
A named tuple `Adjustment(path, code, message, severity)` — `severity` is
`"warning"` or `"error"`. Stable codes: `null.omitted` (TOML/XML), `temporal.stringified`
(JSON/YAML/XML), `float.special` (JSON, `"error"` — a `NaN`/`Infinity`/`-Infinity`
leaf isn't valid JSON; lenient `write_json` substitutes `null` there so the
output stays well-formed, `strict=True` raises instead), `key.sanitized` (XML),
`string.ambiguous` (XML — a string value that looks like another type, e.g. a
digit string or `"true"`, and would read back as that type), `shape.empty_ambiguous`
(XML — an empty internal node, i.e. zero edges, is written as `<tag />` and
reads back as the empty-string leaf `""`, not `[]`), `string.illegal_xml_char`
(XML, `"error"` — a string contains a character XML 1.0 cannot represent, e.g.
a C0 control other than tab/LF/CR, or a surrogate; `write_xml` replaces it with
U+FFFD so the output is always well-formed), `string.cr_normalized` (XML — a
string contains `\r`, which is legal XML but normalizes to `\n` on parse per
the XML spec, so it doesn't round-trip byte-for-byte), and `string.line-break-char`
(YAML — a label or value containing U+0085 NEL, which YAML's line-break rules would
otherwise normalize to a space; written double-quoted to round-trip correctly).

---

## Format registry

Formats are plugins. The four built-ins register themselves on import.

| | |
|---|---|
| `register_format(Format(name, read, write, check=None))` | add a format, usable via `Doc.from_format` / `Doc.to_format` / `Doc.check_format` |
| `get_format(name) -> Format` | look one up by name (raises `OmnistError` if unknown) |
| `formats() -> list[str]` | every registered name, sorted |

```python
from omnist import Format, register_format, Doc

register_format(Format(
    name="lines",
    read=lambda text: [("n", int(x)) for x in text.split()],
    write=lambda node, **opts: " ".join(str(v) for _, v in node),
))
Doc.from_format("lines", "1 2 3").to_format("lines")    # '1 2 3'
```

### `class Format`
A named tuple `Format(name, read, write, check=None)` — `read(text) -> node`,
`write(node, **opts) -> str`, and an optional `check(node) -> WriteReport` for
simulating a write without producing output. The four built-ins all provide
`check`; a plugin that omits it can still be used with `from_format`/
`to_format`, but `Doc.check_format` raises `DocumentError` for it.

---

## Exceptions & warnings

| | Raised when |
|---|---|
| `OmnistError` | base class for all Omnist errors |
| `SchemaError` | invalid schema text or structure (bad OSD, undefined `Ref`, bad cardinality) |
| `ParseError` | a document couldn't be read from its format, or didn't conform to a schema — see [Schema-directed deserialization](deserialization.md) for the structured `.errors` list |
| `DocumentError` | a value isn't a legal Document, or an invalid `Doc` operation |
| `WriteError` | a Document can't be represented in the target format (e.g. multi-rooted XML) |
| `DetachedNode` | (`DocumentError` subclass) a cursor used after its node was removed |
| `UnsafeXMLWarning` | unused as of the fail-closed XML fix (issue #173) — kept exported for backward compatibility |

---

## See also

- [User guide](guide.md) — narrative tour with examples.
- [A real-life example](example.md) — one schema across all four formats.
- [Formats](formats/overview.md) — per-format mapping and caveats.
- [Model spec](design/model.md) — the formal Document and Schema definitions.
