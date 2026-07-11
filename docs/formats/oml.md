# OML

OML (Omnist Markup Language) is Omnist's **own** format — the only one
designed to hold a Document exactly, with no adjustments. Where JSON/YAML/
TOML/XML each give up something (TOML has no `null`, JSON has no native
dates, XML forces a single root), OML maps onto the Document model 1:1: all
seven scalars, `null`, repeated labels, interleaving, and multiple top-level
edges are all native — `check_oml` is always an empty report.

```python
from omnist import read_oml, write_oml, Doc

d = Doc.from_oml('name: "Ann"\ntags: "x"\ntags: "y"\n')
d.to_grouped()                     # {'name': 'Ann', 'tags': ['x', 'y']}
d.to_oml()
```

## Shape

A document is zero or more `label: value` edges, one per line (or
`;`-separated on one line). A repeated label is how an array appears — same
as every other format. Values nest with `{ }`:

```oml
venue: {
    name: "Strange Loop"
    building: {
        address: { street: "123 Main St"; city: "St. Louis"; country: "US" }
        room: "Ballroom A"
    }
}
session: {
    title: "Schema Compatibility, Revisited"
    speaker: {
        name: "Ada Lovelace"
        bio: """
Works on data models and provenance.
Quote: "Hopper said it best".
Path: C:\\talks\\ada\\slides.key
"""
    }
    note: "Recording starts five minutes late."
    note: 'Slides posted after the talk -- path on the laptop: C:\talks\ada\slides.key'
    start: 2024-09-18T14:00:00
    duration: 50
    tags: "schemas"
    tags: "compatibility"
}
attendee_count: 312
virtual: false
```

This reads straight into the Document `[(venue, [...]), (session, [...]),
(attendee_count, 312), (virtual, False)]` — `session.note` is a repeated
label (two notes, in order), `session.tags` likewise, and `session.start`
comes back as a real `datetime.datetime`, not a string.

Edge order here is **data**, not metadata: the order edges are written and
read in OML is preserved in the resulting Document, exactly like any other
value. But order is *not* a schema constraint — a schema validating that
Document never looks at the order its edges came in. Two OML documents with
the same edges in a different order build two different Documents (they
compare unequal), yet both validate identically against the same schema:

```python
from omnist import Doc, parse_schema

doc1 = Doc.from_oml('a: 1\nb: 2')
doc2 = Doc.from_oml('b: 2\na: 1')
doc1 == doc2                     # False -- different Documents, order is data

s = parse_schema('record R { "a": integer, "b": integer }\nroot R')
s.validate(doc1).ok              # True
s.validate(doc2).ok              # True -- same result; validation ignores order
```

See [Validation](../schema.md#validation) for the schema side of this.

## Scalars are typed by their spelling, not a tag

There's no type annotation — the literal's shape says what it is:

| Spelling | Scalar |
|---|---|
| `"text"` | string |
| `42` / `-42` | integer |
| `3.14` / `1e10` / `nan` / `inf` / `-inf` | number |
| `true` / `false` | boolean |
| `2024-01-01` | date |
| `12:30:00` | time |
| `2024-01-01T12:30:00` | datetime |
| `null` | null |

Bare words are never strings — `name: Ann` is a syntax error; quote it:
`name: "Ann"`.

## Mapping to the Python Document

`read_oml` doesn't build a special OML object — it builds exactly the same
canonical node every other reader builds: a scalar, or a list of
`(label, value)` edges (see [the model spec](../design/model.md)). Each OML
scalar spelling becomes one specific Python type, with no ambiguity:

| OML spelling | Python type |
|---|---|
| `"text"` | `str` |
| `42` | `int` |
| `3.14` / `nan` / `inf` | `float` |
| `true` / `false` | `bool` |
| `2024-01-01` | `datetime.date` |
| `12:30:00` | `datetime.time` |
| `2024-01-01T12:30:00` | `datetime.datetime` |
| `null` | `None` |

A `{ }` node becomes a nested edge list; a repeated label becomes the same
label appearing more than once, in order — not a list value. That means the
Python **builder** (`doc(...)`, see [the guide](../guide.md#documents)) can
construct the exact same Document a piece of OML parses to, field for field:

```python
import datetime
from omnist import read_oml, doc

node = read_oml('''
name: "Ann"
role: "dev"
joined: 2024-01-01
tag: "x"
tag: "y"
manager: null
''')

built = doc({
    "name": "Ann",
    "role": "dev",
    "joined": datetime.date(2024, 1, 1),
    "tag": ["x", "y"],     # a repeated key -- becomes the label 'tag' twice
    "manager": None,
})

node == built.to_data()    # True -- identical Document, two different sources
```

This is what "lossless" means concretely: there is no OML feature that
needs a special case in the builder, and no Document shape the builder can
make that OML can't spell out (every scalar type, `null`, repeats,
interleaving, arbitrary nesting).

## Reading

### Without a schema

Because every OML scalar is already exactly typed by its own literal
spelling (the two tables above), reading OML without a schema already hands
back the exact right Python type for every leaf — there's no separate
coercion step the way there is for JSON/XML, and no "before" picture that
differs from the "after" one for any *unquoted* literal:

```python
from omnist import read_oml

read_oml('d: 2024-01-01\nn: 3')
# [('d', datetime.date(2024, 1, 1)), ('n', 3)]
type(dict(read_oml('d: 2024-01-01\nn: 3'))['d'])
# <class 'datetime.date'>
```

The one case that *isn't* already typed is a value written as a quoted
string — `"2024-01-01"` is unambiguously a `str` by its own spelling (OML
has no separate date literal that also happens to be quotable), so it stays
a `str` unless a schema says otherwise:

```python
read_oml('s: "2024-01-01"')
# [('s', '2024-01-01')]
type(dict(read_oml('s: "2024-01-01"'))['s'])
# <class 'str'>
```

### With a schema: validation, not type-upgrading

Like every other format, `read_oml(text, schema=...)` runs the leaves
through the same schema-directed conversion described in
[schema-directed deserialization](../deserialization.md). For OML this
matters less for *type-upgrading* than it does for the other formats,
precisely because OML's literal syntax already produces the exact right
type for any unquoted scalar — `schema=` is a no-op for `d: 2024-01-01`
above. Where it does still convert is the quoted-string case (the one OML
spelling that's deliberately ambiguous about whether it's "just a string"
or "a date written defensively in quotes"):

```python
from omnist import parse_schema, Doc, read_oml

s = parse_schema('record R { "d": date, "n": number }\nroot R')
read_oml('d: "2024-01-01"\nn: 3', schema=s)
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

`Doc.from_oml(text, schema=s)` is the same conversion through the `Doc`
wrapper — it just calls `read_oml` underneath:

```python
Doc.from_oml('d: "2024-01-01"\nn: 3', schema=s).to_data()
# [('d', datetime.date(2024, 1, 1)), ('n', 3.0)]
```

Once read, the result **validates** the same way regardless of format (see
[the Schema model & OSD](../schema.md) for the schema side of this) — for
OML, `Schema.validate` is the main reason to pass a schema at all, since
shape and field-presence problems (a missing field, the wrong cardinality)
are exactly what validation — not deserialization — catches.

## Writing

```python
from omnist import write_oml, Doc

write_oml([("name", "Ada")])          # 'name: "Ada"'
Doc.of({"name": "Ada"}).to_oml()      # 'name: "Ada"'
```

> OML is the one format with no `WriteReport` adjustments: `check_oml`
> always returns an empty report, because every Document shape (all seven
> scalars, `null`, repeats, interleaving, multiple top-level edges) maps
> onto OML without loss. There is no `strict=`/`report=` machinery on
> `write_oml` for the same reason.
>
> The canonical writer always emits `LF` newlines, 2-space indentation, and
> the minimal string-escape form (`\"` and `\\` plus literal Unicode) — same
> input always produces the same output (useful for diffing/snapshotting).

`write_oml(node, indent=None)` switches to a single-line, machine-oriented
form — edges joined by `; ` instead of newlines — for cases like log lines
or diffless storage where pretty-printing isn't useful:

```python
node = [("name", "Ada"), ("tags", [("tag", "x"), ("tag", "y")])]
write_oml(node)             # 'name: "Ada"\ntags: {\n  tag: "x"\n  tag: "y"\n}'
write_oml(node, indent=None) # 'name: "Ada"; tags: { tag: "x"; tag: "y" }'
```

Both forms round-trip through `read_oml` to the same Document — `indent`
only changes layout, never meaning.

## Strings: escaping, raw, and multiline

A normal string escapes the usual set: `\"`, `\\`, `\n`, `\t`, `\r`, `\b`,
`\f`, and `\uXXXX` (a surrogate pair of two `\uXXXX` escapes denotes one
astral code point, e.g. U+1F600). The canonical writer only ever emits this
minimal form — `\"` and `\\` plus literal Unicode, nothing more.

Two extra spellings (read-only — `write_oml` never produces them, so reading
one and writing it back changes layout, never meaning):

- **Raw** `'…'` — no escape processing at all; ideal for paths/regexes:
  `'C:\talks\ada\slides.key'`. The one limitation: it can't contain `'`
  (there's no escape for it inside raw strings) — use the quoted or
  multiline form instead.
- **Multiline** `"""…"""` — may contain literal newlines (a newline right
  after the opening `"""` is stripped, so the first content line doesn't
  have to share the delimiter's line); ordinary escapes still work inside.
  Because the terminator is three quotes, a lone or double `"` is just
  content — only a run of three needs `\"""`.

Newlines *inside* a multiline string are never confused with the structural
line separator: the tokenizer reads `"""…"""` as one token from open to
close (the same way a string can contain `#` without it becoming a
comment), so only a newline *outside* any token separates one edge from the
next.

## Separators

Edges are separated by one or more newlines and/or `;`. There's no comma —
OML has no array literal, so nothing invites one. `;` is for one-line
("inline") style: `{ a: 1; b: 2 }`.

## Comments

`#` starts a comment that runs to the end of the line, discarded by the
tokenizer. It's valid anywhere whitespace is valid — a string can contain a
literal `#` without it becoming a comment, since the tokenizer reads a
quoted string as one token:

```
name: "Ann"   # required
# a full-line comment is fine too
tag: "x"
```

Comments are lexical trivia, not part of the Document model, so they
**don't round-trip**: `write_oml` drops them. Write your notes in the
`.oml` source for readers; don't expect them to survive a parse-and-write
round trip.

## Errors, not silent surprises

A few things that look almost-valid are deliberate hard errors, not lenient
parses:

```python
read_oml("a: 1 b: 2")          # ParseError -- no separator between edges
read_oml('{ a: 1 }\nb: 2')      # ParseError -- braces must wrap the WHOLE document
read_oml("true: 1")             # ParseError -- true/false/null can't be bare labels
read_oml('"true": 1')           # fine -- quoting always works
read_oml("inf: 1")               # ParseError -- inf/nan are reserved NUMBER spellings too
read_oml('"inf": 1')            # fine -- write_oml always quotes these labels for you
```

There's also a digit-count limit on bare integers (4300 digits, matching
CPython's own default `sys.get_int_max_str_digits()`) and a nesting-depth
limit of 200, matching the Document model's own bound — both raise
`ParseError` rather than letting a pathological input hang or crash the
process.

## Notes

- Not yet implemented: a few further OML-Extended conveniences from the
  design draft — digit separators (`1_000_000`), non-decimal integer
  literals (`0x1F`, `0o17`, `0b1010`), the pair-free astral escape
  `\u{1F600}`, a lenient `date time` (space) datetime separator, and a
  trailing `Z` UTC-zone marker. None of these affect what OML can
  *represent* (every Document already round-trips); they're optional input
  sugar for later.
- For the full formal grammar, see
  [the OML-Core grammar](../design/oml-grammar.md).
- See [the comparison table](overview.md#special-features-mapped-to-oml) for
  how OML maps every other format's special-cased features, feature by
  feature.
