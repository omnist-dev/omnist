# TOML

Reading uses the standard-library `tomllib` (Python 3.11+); writing needs
`pip install tomli_w`.

```python
from omnist import read_toml, Doc

d = Doc(read_toml("""
[order]
id = "A1"
[[order.items]]
sku = "W"
[[order.items]]
sku = "G"
"""))
d.to_json()    # '{"order": {"id": "A1", "items": [{"sku": "W"}, {"sku": "G"}]}}'
```

## How it maps

- A table becomes a list of edges; nested tables (`[a.b]`) nest.
- An **array-of-tables** (`[[order.items]]`) is the idiomatic array of records —
  it maps to a repeated `items` label, the same as JSON `"items": [{…}, {…}]`.

Read raw, each `[[items]]` block becomes its own `items` edge — the repeated
label is in the edge list directly, not just in the regrouped JSON-shaped
projection:

```python
from omnist import read_toml

read_toml("""
[[items]]
sku = "W"
[[items]]
sku = "G"
""")
# [('items', [('sku', 'W')]), ('items', [('sku', 'G')])]
```

## Reading

### Without a schema

Unlike JSON, TOML's grammar has native `date`/`time`/`datetime` literals, and
`tomllib` parses them straight into the matching Python types — no schema
needed:

```python
from omnist import read_toml

read_toml('d = 2024-01-01')
# [('d', datetime.date(2024, 1, 1))]
type(dict(read_toml('d = 2024-01-01'))['d'])
# <class 'datetime.date'>

read_toml('t = 12:00:00')
# [('t', datetime.time(12, 0))]
read_toml('dt = 2024-01-01T12:00:00')
# [('dt', datetime.datetime(2024, 1, 1, 12, 0))]
```

This is a genuinely different "before" picture than JSON's: reading TOML
without a schema can already hand back real temporal objects for any of the
three kinds, not just `date`.

A fractional second holds at most six digits (microseconds, the OML grammar's
`1*6DIGIT`). Zeros beyond the sixth are insignificant and dropped, but a
**non-zero seventh or later digit fails the read** with `parse.codec-syntax`
(at the literal) instead of being truncated silently: `00:32:00.9999999` is an
error. Through 0.17.0 it read as `.999999`. Offsets are kept, never converted.

### With a schema

Because TOML's own parser already produces value-exact `date`/`time`/
`datetime` objects, `schema=` is a no-op for those fields — it still matters
for upgrading other scalars, e.g. an integer to `number`:

```python
from omnist import parse_schema, read_toml

s = parse_schema('record R { "d": date, "n": number }\nroot R')
read_toml('d = 2024-01-01\nn = 3', schema=s)
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

See [schema-directed deserialization](../deserialization.md) for the full
conversion rules. `Doc.from_toml(text, schema=s)` is the same conversion
through the `Doc` wrapper — it just calls `read_toml` underneath:

```python
from omnist import Doc

Doc.from_toml('d = 2024-01-01\nn = 3', schema=s).to_data()
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

## Writing

```python
from omnist import write_toml, Doc

write_toml([("id", "A1")])              # 'id = "A1"\n'
Doc.of({"id": "A1"}).to_toml()          # 'id = "A1"\n'
```

> **No `null`.** TOML has no null value, so writing one fails unconditionally
> (`WriteError`, `code="write.unsupported-value"`, at the path of the null
> leaf), regardless of `strict`.
>
> **Top-level must be a table.** A bare scalar or array at the root isn't valid
> TOML; a single-rooted Document (one top-level key) writes cleanly.

> **Cross-label interleaving is also lost.** Grouping same-label edges
> together can lose their original relative position against *other*
> labels -- `[(m,A),(x,X),(m,B)]` groups to `m = ["A", "B"]` / `x = "X"`,
> and there is no way back to the interleaved order. Reported as
> `format.interleaving-lost` at `$` (the whole document) whenever this
> actually happens -- a label repeated only contiguously
> (`[(m,A),(m,B),(x,X)]`) groups losslessly and is not flagged.

`write_toml`/`check_toml` raise `WriteError` (naming the limit) if a
Document nests past 200 levels — the same limit `read_toml` already
enforces on parse. See [the API reference](../api.md#reading--writing-formats).

## Notes

- **A repeated key is refused** (C-12): `a = 1` followed by `a = 2`, a repeated
  dotted key, and an inline table that repeats a key are all
  `parse.codec-syntax` at the line and column `tomllib` reports; what counts as
  defining a key twice is TOML's own rule.
- TOML round-trips `date`/`time`/`datetime` natively in both directions, with
  one exception (E-37, omnist-spec v0.35.0-beta): TOML has no offset time, so a
  `time` with an offset (`12:00:00+01:00`) is written as a double-quoted ISO-8601
  string with a `format.temporal-stringified` warning (it used to raise). A
  `datetime` is written with the `T` separator (`2024-01-15T12:00:00+01:00`).
- See [the comparison table](overview.md#special-features-mapped-to-oml) for
  how TOML's native temporal types and array-of-tables stack up against the
  other formats.
- For a real-world TOML schema modeled end to end — including where OSD's
  algebra can't fully capture the format's own spec — see
  [Worked example: modeling pyproject.toml](../examples/pyproject.md).
