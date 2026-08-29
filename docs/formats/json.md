# JSON

The baseline format — no dependencies (uses the standard-library `json`).

```python
from omnist import read_json, write_json, Doc

d = Doc.from_json('{"name": "Ann", "tags": ["x", "y"]}')
d.to_json()                      # '{"name": "Ann", "tags": ["x", "y"]}'
```

## How it maps

- A JSON object becomes a list of edges.
- A key whose value is an array expands into **one edge per item** (a repeated
  label): `{"tags": ["x", "y"]}` → `[(tags, "x"), (tags, "y")]`.
- A nested object becomes a nested node; scalars are leaves.

That's the raw edge list, not a round-tripped projection — `read_json` itself
returns it directly:

```python
from omnist import read_json

read_json('{"tags": ["x", "y"]}')
# [('tags', 'x'), ('tags', 'y')]
```

## Reading

### Without a schema

JSON has no native date/time type, so a date-looking string comes back as a
plain `str` — there's nothing else it could be:

```python
from omnist import read_json

read_json('{"d": "2024-01-01", "n": 3}')
# [('d', '2024-01-01'), ('n', 3)]
type(dict(read_json('{"d": "2024-01-01", "n": 3}'))['d'])
# <class 'str'>
```

### With a schema

`schema=` upgrades each leaf to match the schema's declared scalar, wherever
the conversion is value-exact — here the date string becomes a real
`datetime.date`, and the integer `3` becomes the `float` `3.0` (a `number`
field always materializes as `float`). See
[schema-directed deserialization](../deserialization.md) for the full
conversion rules.

```python
from omnist import parse_schema, read_json

s = parse_schema('record R { "d": date, "n": number }\nroot R')
read_json('{"d": "2024-01-01", "n": 3}', schema=s)
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

`Doc.from_json(text, schema=s)` is the same conversion through the `Doc`
wrapper — `Doc.from_json` just calls `read_json` underneath:

```python
from omnist import Doc

Doc.from_json('{"d": "2024-01-01", "n": 3}', schema=s).to_data()
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

## Writing

`write_json` groups same-label edges back into a JSON array. A label seen more
than once becomes a list; a label seen exactly once stays a single value (the
**count-1 rule**: a single-element array can't be told apart from a single
value, so it always serializes as a bare value). `write_json` (like every
writer) never takes a schema — a writer serializes the Document exactly as it
is, with no schema-driven override of this rule. Schema awareness is read-side
only.

> Grouping same-label edges together can lose their original relative
> position against *other* labels -- `[(m,A),(x,X),(m,B)]` groups to
> `{"m":[A,B],"x":X}`, and there is no way back to the interleaved
> order. Reported as `format.interleaving-lost` at `$` (the whole
> document) whenever this actually happens -- a label repeated only
> contiguously (`[(m,A),(m,B),(x,X)]`) groups losslessly and is not
> flagged. See [adjustment reports](../api.md#adjustment-reports-lossy-writes).


```python
from omnist import write_json, Doc

write_json([("tag", "x"), ("tag", "y")])     # '{"tag": ["x", "y"]}'
write_json([("tag", "x")])                    # '{"tag": "x"}'

Doc.of({"tag": ["x", "y"]}).to_json()         # '{"tag": ["x", "y"]}'
```

> JSON has no date type, so a `date`/`time`/`datetime` leaf is written out as
> an ISO-8601 string (reported as `temporal.stringified`), and reads back as
> a plain `str` unless `schema=` is given on the way back in. See
> [adjustment reports](../api.md#adjustment-reports-lossy-writes).
>
> JSON has no `NaN`/`Infinity`, and there's no safe substitute: a
> substituted `null` is indistinguishable, on read-back, from a leaf that
> was genuinely `null` to begin with. `write_json` now fails unconditionally
> on a `NaN`/`Infinity`/`-Infinity` leaf -- `code="write.unsupported-value"`
> -- lenient or `strict=True` alike (issue #325).

```python
from omnist import WriteError, write_json

try:
    write_json([("a", float("inf"))])
except WriteError as e:
    e.code                                      # 'write.unsupported-value'
```

`write_json`/`check_json` raise `WriteError` (naming the limit) if a
Document nests past 200 levels — the same limit `read_json` already
enforces on parse. See [the API reference](../api.md#reading--writing-formats).

## Notes

- `date`, `time`, and `datetime` strings are mutually exclusive even before a
  schema is involved: `"2024-01-01"` could only ever satisfy `date`, not
  `datetime` (it has no time component to satisfy it with).
- A bare top-level array (`[1, 2, 3]`) has no labels, so it isn't a Document on
  its own — wrap it under a key.
- See [the comparison table](overview.md#special-features-mapped-to-oml) for
  how JSON's quirks stack up against the other formats.
- For a real-world JSON schema modeled end to end -- including a format
  with no formal spec at all -- see
  [Worked example: modeling package.json](../examples/package-json.md).
