# YAML

The JSON-compatible core of YAML. Needs `pip install pyyaml`.

```python
from omnist import read_yaml, Doc

d = Doc(read_yaml("""
name: Ann
tags: [x, y]
"""))
d.to_json()                      # '{"name": "Ann", "tags": ["x", "y"]}'
```

## How it maps

Identical to [JSON](json.md): a mapping becomes a list of edges, a key whose
value is a sequence expands into a repeated label, scalars are leaves. A YAML
document and the equivalent JSON document read into the **same** Document.

Read raw (no `.to_json()` projection), a YAML sequence comes back as the
repeated-label edge list directly:

```python
from omnist import read_yaml

read_yaml('tags: [x, y]')
# [('tags', 'x'), ('tags', 'y')]
```

## Reading

### Without a schema

Unlike JSON, PyYAML's own loader (`safe_load`) already recognizes unquoted
ISO-8601-looking scalars and parses them into native Python `date`/`datetime`
objects — with no schema involved at all:

```python
from omnist import read_yaml

read_yaml('d: 2024-01-01')
# [('d', datetime.date(2024, 1, 1))]
type(dict(read_yaml('d: 2024-01-01'))['d'])
# <class 'datetime.date'>

read_yaml('dt: 2024-01-01T12:00:00')
# [('dt', datetime.datetime(2024, 1, 1, 12, 0))]
```

There's no standalone "time of day" type in YAML's core schema, so a bare
`12:00:00` is parsed as the sexagesimal integer `43200` (`12*3600`), not a
`datetime.time` — that's PyYAML's own resolver, not omnist.

### With a schema

Because PyYAML already hands back a real `date`/`datetime` for those forms,
passing `schema=` is a no-op for a field that's already value-exact. It still
matters for fields PyYAML's loader can't natively type — a bare time-of-day
string, or a numeric field that needs upgrading to `number`:

```python
from omnist import parse_schema, read_yaml

s = parse_schema('record R { "d": date, "n": number }\nroot R')
read_yaml('d: 2024-01-01\nn: 3', schema=s)
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

See [schema-directed deserialization](../deserialization.md) for the full
conversion rules. `Doc.from_yaml(text, schema=s)` is the same conversion
through the `Doc` wrapper — it just calls `read_yaml` underneath:

```python
from omnist import Doc

Doc.from_yaml('d: 2024-01-01\nn: 3', schema=s).to_data()
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

## Writing

```python
from omnist import write_yaml, Doc

write_yaml([("name", "Ada"), ("born", __import__("datetime").date(1815, 12, 10))])
# 'name: Ada\nborn: 1815-12-10\n'

Doc.of({"name": "Ada"}).to_yaml()
# 'name: Ada\n'
```

> YAML carries `date`/`datetime` natively, but has no standalone time-of-day
> type, so a bare `time` leaf is written as a string and reported as
> `temporal.stringified` (a warning).
>
> A label or string value containing U+0085 (NEL, "next line") is written
> double-quoted rather than plain/single-quoted, since YAML's line-break
> normalization would otherwise turn it into a plain space on read. This is
> reported as the `string.line-break-char` adjustment code (a warning, since
> it round-trips correctly — it's surfaced only so callers know the output
> style was forced for that value). See
> [adjustment reports](../api.md#adjustment-reports-lossy-writes).

`write_yaml`/`check_yaml` raise `WriteError` (naming the limit) if a
Document nests past 200 levels — the same limit `read_yaml` already
enforces on parse. See [the API reference](../api.md#reading--writing-formats).

## Notes

- Only YAML's JSON-compatible core is supported (string keys, standard scalars,
  mappings and sequences). Tags, anchors-as-merge, and non-string keys are
  outside the profile.
- Sequences of mappings (`- {…}`) are the idiomatic way to write an array of
  records, and map to a repeated label — see
  [the real-life example](../example.md).
- See [the comparison table](overview.md#special-features-mapped-to-oml) for
  how YAML's anchors, aliases, and native date handling stack up against the
  other formats.
- For a real instance of the "non-string keys are outside the profile" limit
  above -- PyYAML's YAML 1.1 boolean-coercion rule turning a bare `on:` key
  into the Python boolean `True` -- see
  [Worked example: modeling a GitHub Actions workflow](../examples/github-actions.md).
