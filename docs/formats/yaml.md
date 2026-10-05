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
> `format.temporal-stringified` (a warning).

> Grouping same-label edges together can also lose their original relative
> position against *other* labels -- `[(m,A),(x,X),(m,B)]` groups to
> `m: [A, B]\nx: X\n`, and there is no way back to the interleaved order.
> Reported as `format.interleaving-lost` at `$` (the whole document)
> whenever this actually happens -- a label repeated only contiguously
> (`[(m,A),(m,B),(x,X)]`) groups losslessly and is not flagged.
>
> A label or string value containing U+0085 (NEL, "next line") is written
> double-quoted rather than plain/single-quoted, since YAML's line-break
> normalization would otherwise turn it into a plain space on read. This is
> reported as the `format.string-line-break-char` adjustment code (a warning, since
> it round-trips correctly — it's surfaced only so callers know the output
> style was forced for that value). See
> [adjustment reports](../api.md#adjustment-reports-lossy-writes).

`write_yaml`/`check_yaml` raise `WriteError` (naming the limit) if a
Document nests past 200 levels — the same limit `read_yaml` already
enforces on parse. See [the API reference](../api.md#reading--writing-formats).

## Alias limits

`read_yaml` bounds alias expansion **before** it expands anything
(omnist-spec D-18, D-18a, D-19, D-20 and D-22, section 2.4.1). It composes the
document into PyYAML's anchor/alias graph, which is linear in the input however
large the expansion it describes, measures that graph in one iterative pass,
and only then constructs the value. A "billion laughs" input costs
milliseconds, not seconds or gigabytes.

| option | default | most it may be set to | refused with |
|---|---|---|---|
| `max_alias_expansion` | 50 | 10 000 | `document.limit.alias-expansion` |
| `max_expanded_slots` | 1 000 000 | 10 000 000 | `document.limit.expanded-size` |

Both are keyword arguments of `read_yaml` and `Doc.from_yaml`. A value that is
not an `int` (a `bool` included) raises `TypeError`; one outside `1 .. ceiling`
raises `ValueError`. `Doc.from_format("yaml", ...)`, the format registry and
the CLI use the defaults.

**The ratio (`max_alias_expansion`).** Every mapping and sequence, anchored or
not, the root and an inline merge source included, is measured as `E = W / S`:
`W` is the value slots it materializes, `S` the value slots written in it. A
scalar and a container are one slot each, a mapping key none; an alias is one
slot in `S` and its target's `W` in `W`; a merge key `<<` is one slot in `S`
and contributes `W - 1` per merged mapping. An input where any `E` exceeds the
maximum is refused, `E` equal to it is accepted. Scalars are never checked.
A sequence in merge position (`<<: [*a, *b]`, anchored or not) is only a
carrier: it holds no slot. `W` is a conservative count (it does not resolve
key collisions), so a mapping whose merged keys are overridden can be refused
though it materializes less.

A mapping that merges a large block reads `E` of about `(keys + 2) / 3`:
`job: {<<: *base, script: x}` is accepted over a 148-key `base` and refused
over a 149-key one at the default. A hundred services each merging a 20-key
block reads 7.3 at worst, and a 100-key block aliased 60 times at the root
reads 38 (refused at 100 times). Raise `max_alias_expansion` if a real file
needs more.

**The size (`max_expanded_slots`).** The ratio bounds amplification, not size:
a large document in which every container sits just under 50 is accepted by it
and can still allocate gigabytes. So `W` of the root over `max_expanded_slots`
is refused too, after the ratio check (an input failing both reports
`document.limit.alias-expansion`).

**The exemption, and its cliff.** The size limit applies only to an input that
contains at least one alias or merge key. A plain, alias-free YAML file is not
subject to it, however large, as a JSON or OML file of the same size is: a
two-million-slot plain file is read, and adding one alias to it subjects it to
the one-million cap. That is deliberate; the size of a plain input is the
caller's to bound.

Both codes carry the path `$`.

**Also refused, by the same pass.**

- A self-referential anchor, directly or through a cycle (`a: &a {<<: *a}`),
  is `document.limit.alias-expansion`; nothing cyclic is built.
- A merge value that is not a mapping or a sequence of mappings (`<<: 1`,
  `<<: [1]`, `<<: [[{a: 1}]]`, `<<: *s` over scalars) is `parse.codec-syntax`
  at the line and column of the offending node, and wins over any limit code.
  `<<: []`, and an alias to an empty sequence, merge nothing and are accepted.
- An empty merge sequence (`<<: []`, or `<<: *s` over `s: &s []`) is a
  well-formed carrier that merges nothing (omnist-spec v0.27.0-beta); an empty
  sequence anywhere else is an ordinary node and, as a value, yields no edge.
- A container used as a mapping key is counted like any value, so it cannot
  hide a bomb; the specification is silent on it, and PyYAML then refuses the
  unhashable key when it constructs, so only the reported error differs.
- Limit options of `0` or less raise `ValueError` (as in omnist-j); the
  TypeScript, Go and Rust ports treat `0` as "use the default".
- An anchor may be defined again; the latest definition applies to the aliases
  after it, as YAML 1.2 allows (PyYAML alone refuses it).

**What it does not bound.** PyYAML's own parse is pure Python and costs
seconds per megabyte whatever the aliases: measured on one machine
(the alias check adds under 1.2 seconds per 100,000 nodes), a 1.1 MB block
mapping of 50,000 keys takes about 4 seconds in `read_yaml` (the same as before
the limits existed), a 150,000-item root sequence (0.94 MB) 5 to 6 seconds to
compose, and a 1.8 MB plain file 20 to 23 seconds. The limits above refuse an
over-limit input after composing it, not before reading it; the input is
bounded first by `max_input_bytes` (64 MiB by default,
[limitations](../limitations.md#the-64-mib-input-size-limit)), which you may
lower (see [SECURITY.md](https://github.com/omnist-dev/omnist/blob/master/SECURITY.md)).

```python
from omnist import read_yaml

shared = "b: &b {k1: 1, k2: 2, k3: 3}\nt: {a: *b, b: *b, c: *b, d: *b}\n"
read_yaml(shared, max_expanded_slots=22)   # accepted: W(root) is exactly 22
read_yaml(shared, max_expanded_slots=21)   # DocumentError, code "document.limit.expanded-size"
```
<!-- verified-by: tests/test_yaml_alias.py::TestDocExample::test_the_size_example -->

## Notes

- Only YAML's JSON-compatible core is supported (string keys, standard scalars,
  mappings and sequences). Tags and non-string keys are outside the profile.
- The merge key `<<` flattens in **source order**: merged entries first (each
  merged mapping in its own order, `<<: [*a, *b]` as `a` then `b`), then the
  mapping's own; a key supplied twice is one edge at its first position,
  carrying the mapping's own value if it writes one and otherwise the earliest
  alias's. (PyYAML flattens a merge sequence in reverse; `read_yaml` does not
  inherit that.)
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
