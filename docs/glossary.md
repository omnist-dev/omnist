# Glossary

One definition per term, grouped by concept area. Each entry links to where
the term is defined or used in depth. Where two terms look similar but mean
different things (the most common source of confusion in this codebase),
the entry says so explicitly.

## Document model terms

These describe the **data** — the canonical tree every supported format
reads into and writes out of. Defined formally in
[the model spec, §4](design/model.md#4-document-model).

- **node** — the canonical Python value of the Document model: either a
  scalar value (a leaf), or an ordered list of labeled edges (an internal
  node). `node` is the *model* term — the shape itself, independent of any
  wrapper class. See [model spec §4](design/model.md#4-document-model).
- **Document** — the data model as a whole: "a Document is a tree of
  ordered, labeled edges." Used for the *concept*, not a specific Python
  class — a node *is* a Document, in the sense that any node is an instance
  of the Document model. See [model spec §4](design/model.md#4-document-model)
  and [the guide](guide.md#the-two-ideas).
- **`Doc`** — the guarded Python wrapper class around a node, with
  navigation and editing helpers (`.edges()`, `.get()`, `.add()`, ...).
  Where "Document" names the model/concept, `Doc` is the specific class
  that holds one. See [the API reference](api.md#documents).
- **tree** — informal, non-technical synonym for the Document's overall
  shape (an ordered, nested structure of edges). Not a distinct technical
  term from "node" — used in prose to evoke the shape, e.g. "a Document is a
  *tree*: a node is either a scalar value or an ordered list of labeled
  edges" ([guide](guide.md#the-two-ideas)).
- **edge** — a `(label, node)` pair: the Document-model unit of structure.
  "Many" is a repeated label, i.e. several edges sharing one label — not a
  single edge pointing at an array. Contrast with **field**, the
  Schema-model term for the corresponding *named, cardinality-bound slot* a
  record declares. See [model spec §4](design/model.md#4-document-model).
- **label** — the string key half of an edge (`(label, node)`). The same
  word is used on the Schema side for a field's name (`Field.label`) — by
  design, since a field's label is exactly the edge label it constrains.
  See [model spec §4](design/model.md#4-document-model) and
  [§5](design/model.md#5-schema-model).
- **leaf** — a node holding a scalar value rather than a list of edges.
  `Doc.is_leaf` is `True` exactly for this case. See
  [the API reference](api.md#documents).
- **scalar value** — a Python value that can sit at a Document leaf:
  `str`, `int`, `float`, `bool`, `datetime.date`/`time`/`datetime`, or
  `None`. Contrast with **Scalar** (capitalized), the Schema-side type
  object described below — a scalar *value* is data; a `Scalar` is a
  type constraint on what scalar values are allowed. See
  [model spec §4](design/model.md#4-document-model).

## Schema model terms

These describe the **constraint** — the shape a Document must have to be
valid. Defined formally in
[the model spec, §5](design/model.md#5-schema-model).

- **`Scalar`** — the Schema-side type object: one of the seven fixed kinds
  (`string`, `integer`, `number`, `boolean`, `date`, `time`, `datetime`),
  optionally nullable, used as a field's type (e.g. `Scalar("string")`,
  or the ready-made `STRING`/`t.string`). A `Scalar` is a *type*; it
  constrains which scalar values are valid, it is not itself a value. See
  [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py) and
  [the schema doc](schema.md#shape).
- **`any`** / **`AnyType`** — the eighth type keyword (v0.5.0): a field
  typed `any` accepts *every* legal Document value — any scalar, `null`,
  or a subtree of any shape — and validation does not descend into it.
  The field's label stays fixed and counted (cardinality applies); only
  the value is unchecked. `AnyType` is the exported class (`t.any` is its
  singleton instance); `any?` is rejected as redundant (null is already
  included), `any` is reserved as a record name, and `infer` never
  produces it. It is the model's one deliberate opening — and
  `compatible_with` is vacuous inside `any` regions, so checking ends
  exactly where `any` begins. See [the schema doc](schema.md#the-any-type)
  and [any-type-spec.md](design/any-type-spec.md).
- **kind** / **`value_kind()`** — `kind` is the plain string name
  (`"string"`, `"integer"`, ...) classifying a Python *value* — what
  `value_kind(v)` returns, used for inference and error messages. It is the
  same vocabulary as a `Scalar`'s `.name`, but `kind`/`value_kind()` answers
  "what kind of value is this, at runtime?" while `Scalar` answers "what
  type does this field declare?" `matches_kind(value, name)` is the
  boolean predicate form, with a wider match set (e.g. an `integer` value
  also matches a `"number"` check). See
  [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py) and
  [model spec §10](design/model.md#10-scalar-and-python-type).
- **data type** — not used as a distinct term in this codebase; the
  intentional vocabulary is **kind** (a value's runtime classification),
  **`Scalar`** (a field's declared type), and **Python type** (the actual
  `str`/`int`/`date`/... class a value materializes as) — see
  [model spec §10](design/model.md#10-scalar-and-python-type) for how the
  three relate. Avoid "data type" in new docs/comments; use the specific
  one of the three meant.
- **field** — the Schema-model term for a named, cardinality-bound slot of
  a `Record`: `Field(label, type, min, max)`. A field is what a `Record`
  declares; an **edge** (Document-model term, above) is what a `Doc`
  actually contains. A field's `type` is a `Scalar` or a `Ref`, never both
  or a composition. See
  [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py) and
  [the schema doc](schema.md#shape).
- **`Field`** — the Python class implementing a field (capitalized,
  contrast with lowercase **field**, the general concept, and with the
  `field()` builder function below).
- **record** (lowercase) — the OSD keyword that introduces a record
  definition (`record Member { ... }`), and the general concept: a closed
  set of named fields. See [the schema doc](schema.md#shape).
- **`Record`** — the Python class: a closed set of `Field`s, constructed
  by the lowercase `record(*fields)` builder function. Lowercase `record`
  is the keyword/concept; `Record` is the class — distinguished by case
  and code-formatting throughout the docs. See
  [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py).
- **`Ref`** — a pointer into the schema's named environment (`env`),
  resolving to a `Record`. Used for reuse and recursion; a field's type is
  a `Scalar` or a `Ref`, never an inline/anonymous record. See
  [model spec §5](design/model.md#5-schema-model).
- **cardinality** — the `[min, max]` range on a `Field`, the single
  mechanism for required/optional/array (`max=None` is unbounded). There
  is no separate array type — "array" is a field with `max > 1`. See
  [model spec §5](design/model.md#5-schema-model) and
  [the schema doc](schema.md#shape).
- **`Schema`** — the root object: a `root` `Ref` plus an `env` dict mapping
  names to `Record` definitions. See
  [`omnist/schema.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/schema.py) and
  [the API reference](api.md#schemas).
- **schema** (lowercase, general use) — the constraint as a concept, or an
  instance of `Schema`; also used loosely for "the OSD text describing one."
  Distinguished from **OSD** (below) by context: "a schema" is the
  parsed/constructed object or the idea; "OSD" is the text syntax used
  to write one.
- **satisfiable** — a record admits at least one finite document; the least
  fixpoint over `min >= 1` fields being `Scalar`s or `Ref`s to other
  satisfiable records (`ops/prune.py`, `satisfiable_set`). The complement
  of the paper's "useless"/"irrational" states. See
  [model spec §12](design/model.md#12-satisfiability-and-pruning).
- **empty schema** — a `Schema` whose root record is unsatisfiable, so it
  accepts the empty language (no document at all) — typically a mandatory
  ref cycle with no base case. `Schema.is_empty()` detects it. An empty
  schema is vacuously `compatible_with` any other schema, and any two
  empty schemas are `equivalent`. See
  [the schema doc](schema.md#empty-schemas) and
  [model spec §12](design/model.md#12-satisfiability-and-pruning).
- **prune** / **`Schema.prune()`** — the paper's MakeUsefulSA analog:
  returns an equivalent schema with unreachable records, never-emittable
  (`max == 0`) fields, and optional-but-unsatisfiable fields removed. A
  precondition `compatible_with`/`equivalent` need to be correct on
  unsatisfiable input, though callers don't need to prune manually — those
  methods account for satisfiability internally. Also the mandatory first
  step of `normalize()`. See
  [model spec §12](design/model.md#12-satisfiability-and-pruning).
- **normalize** / **`Schema.normalize()`** — the paper's Algorithm 2
  (MinimizeSA): partition refinement (the DFA-minimization family) that
  returns the *canonical minimal form* equivalent to its input. Prunes
  first, then repeatedly splits blocks of env records apart wherever their
  ref-typed fields point at still-distinguishable targets, then merges
  each stable block to one representative name. See
  [model spec §13](design/model.md#13-minimization-and-canonical-form).
- **canonical form** / **minimal schema** — the result of `normalize()`:
  the fewest possible env records equivalent to a given schema, unique up
  to record naming (paper Theorems 3-4). Two equivalent schemas normalize
  to isomorphic results. See
  [model spec §13](design/model.md#13-minimization-and-canonical-form).
- **subschema extraction** / **`Schema.extract(*labels)`** — the paper's
  Algorithm 5 (ExtractSubschema): given a set of permissible labels,
  produces the minimal subschema recognizing only documents built from
  them. Fields whose label isn't kept are dropped; dropping a *mandatory*
  field invalidates the record that had it, invalidation propagates
  through mandatory refs, and if it reaches the root, `extract` raises
  `SchemaError` rather than silently loosening cardinality. Ends with the
  same `prune()` + `normalize()` as Algorithm 5's own MakeUseful +
  Minimize step. See
  [the schema doc](schema.md#subschema-extraction).

## OML / OSD format terms

- **OSD** (Omnist Schema Definition) — the small text language (`record` /
  `root` syntax) for writing a `Schema`, parsed by `parse_schema()` and
  produced by `to_osd()`. See [the schema doc](schema.md#shape).
- **OML** (Omnist Markup Language) — Omnist's own native format, designed
  so every Document shape round-trips through it with zero adjustments.
  Distinct from OSD: OML is a *data* format (like JSON/YAML/TOML/XML),
  while OSD is a *schema* text syntax — they look superficially similar
  (both use `label: value`-ish syntax) but describe different things (data
  vs. constraints). See [the OML format page](formats/oml.md).
- **codec** — a `Format`'s `read`/`write` (and optional `check`) functions,
  bundled together and registered by name (`register_format`), letting
  `Doc.from_format`/`to_format`/`check_format` use it like a built-in
  format. See [the API reference](api.md#format-registry).
- **round-trip** — reading a value in one format and writing it back out
  (same format or another) without losing information. OML round-trips
  every Document shape losslessly; other formats may need an *adjustment*
  (below) to round-trip. See [the OML format page](formats/oml.md) and
  [Formats](formats/overview.md).
- **adjustment** — a recorded change a writer made because the target
  format cannot hold a value losslessly (e.g. TOML dropping `null`, JSON
  stringifying a date). Collected in a `WriteReport`; `strict=True` raises
  a `WriteError` instead of adjusting silently. See
  [the API reference](api.md#adjustment-reports-lossy-writes).
- **deserialization** / **materialize** — converting a freshly-read node's
  leaf values to match a `Schema`'s declared `Scalar` kinds (e.g. an
  ISO-8601 string to a real `datetime.date`), as distinct from
  **validation**, which only *checks* a match without converting anything.
  See [model spec §10](design/model.md#10-scalar-and-python-type).
- **inference** — drafting a `Schema` from example Documents (`infer()`),
  determining each field's `Scalar`, nullability, and cardinality from
  observed samples. See
  [model spec §11](design/model.md#11-inference-determining-a-fields-scalar-from-samples).
