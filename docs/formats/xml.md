# XML

A deliberately narrow **data-XML** profile: elements only, used to carry the
same Documents as the other formats. `defusedxml` is a hard requirement for
`read_xml` — install it with `pip install defusedxml` (or the `xml`/`all`
extra). Without it, `read_xml` raises `ImportError` immediately rather than
falling back to the standard library's parser, which is vulnerable to
entity-expansion / XXE attacks on untrusted input.
Element nesting is also capped at 200 levels, the same `_MAX_DEPTH` bound
every other reader enforces via `build_node` — deeper input raises a clean
`DocumentError` naming the limit rather than exhausting the call stack.

```python
from omnist import read_xml, Doc

d = Doc(read_xml("<person><name>Ann</name><tags>x</tags><tags>y</tags></person>"))
d.to_json()    # '{"person": {"name": "Ann", "tags": ["x", "y"]}}'
```

## How it maps

- An element with child elements becomes a node; each child tag is an edge label.
- **Repeated elements are a repeated label** — `<item/><item/>` is the label
  `item` twice, i.e. an array, exactly like JSON `"item": [{…}, {…}]`.
- A leaf element is a scalar — its text content.

Read raw, repeated `<item>` elements come back as the repeated-label edge list
directly, not the regrouped JSON-shaped array:

```python
from omnist import read_xml

read_xml('<items><item>x</item><item>y</item></items>')
# [('items', [('item', 'x'), ('item', 'y')])]
```

## Single document element

XML has exactly **one** top-level element, so an XML Document always has a
**single top-level edge** (the document element's tag). That's why a Document
meant to round-trip through XML is *single-rooted* — wrap your data under one
top-level key:

```python
read_xml("<order>…</order>")          # -> [("order", […])]
```

To share a Document with JSON/YAML/TOML, give them a matching single top-level
key (`{"order": {…}}`). Writing requires a single top-level edge — a Document
with several top-level edges has no single XML document form and raises.

## Interleaving is preserved

Because the Document is an *ordered* edge list, XML's interleaved repeats
survive on read — `<m/><x/><m/>` reads as `[(m,…), (x,…), (m,…)]`, the one thing
a dict-with-arrays can't represent. (Projecting to JSON groups the `m`s, since
JSON can't interleave.)

## Reading

### Without a schema

Element text is untyped, but `read_xml`'s coercion heuristic does try
`int`/`float`/`bool` before falling back to `str` — it does **not** attempt
any date/time coercion, since a date string is indistinguishable from any
other string by spelling alone without a declared scalar to check it against:

```python
from omnist import read_xml

read_xml('<r><n>30</n><f>3.5</f><ok>true</ok><d>2024-01-01</d></r>')
# [('r', [('n', 30), ('f', 3.5), ('ok', True), ('d', '2024-01-01')])]
```

`<n>30</n>` reads as the integer `30` and `<ok>true</ok>` as `True`, but
`<d>2024-01-01</d>` stays the plain `str` `'2024-01-01'` — XML has no date
type and `read_xml` doesn't guess one from the shape of the text.

### With a schema

`schema=` upgrades a leaf to match the schema's declared scalar wherever the
conversion is value-exact — this is what turns the date string above into a
real `datetime.date`:

```python
from omnist import parse_schema, read_xml

s = parse_schema('record Inner { "d": date, "n": number }\n'
                  'record R { "r": Inner }\nroot R')
read_xml('<r><d>2024-01-01</d><n>3</n></r>', schema=s)
# [('r', [('d', datetime.date(2024, 1, 1)), ('n', 3.0)])]
```

(The schema's shape has to mirror the document's — XML always wraps its
content in a single document element, here `<r>`, so the schema needs a
record for that wrapper too.) See
[schema-directed deserialization](../deserialization.md) for the full
conversion rules. `Doc.from_xml(text, schema=s)` is the same conversion
through the `Doc` wrapper — it just calls `read_xml` underneath:

```python
from omnist import Doc

Doc.from_xml('<r><d>2024-01-01</d><n>3</n></r>', schema=s).to_data()
# [('r', [('d', datetime.date(2024, 1, 1)), ('n', 3.0)])]
```

## Writing

```python
from omnist import write_xml, Doc

write_xml([("order", [("id", "A1")])])
# '<order>\n  <id>A1</id>\n</order>\n'

Doc.of({"order": {"id": "A1"}}).to_xml()
# '<order>\n  <id>A1</id>\n</order>\n'
```

> A key that isn't a legal XML element name is sanitized on write (e.g.
> `"a b"` → `<a_b>`, reported as `key.sanitized`), and a date/time value is
> written as text (`temporal.stringified`).
>
> **A string that looks like another type reads back as that type.** If you
> write the string `"30"` as a leaf, it round-trips as the *integer* `30`,
> not the string `"30"` — `write_xml` reports this ahead of time as
> `string.ambiguous` so you know it won't come back the way it went in.
>
> **An empty internal node (zero edges, `[]`) is indistinguishable from an
> empty-string leaf (`""`)** once written: both serialize to `<tag />`, and
> `read_xml` always reconstructs the empty-string leaf. Writing `[]` is
> reported as `shape.empty_ambiguous` so you know ahead of time that it won't
> round-trip; writing `""` round-trips fine and is not flagged.
>
> **A string containing a character XML 1.0 cannot represent** (most C0
> control characters -- everything below U+0020 except tab/LF/CR -- or a
> UTF-16 surrogate) would otherwise produce text that isn't well-formed XML,
> so `write_xml` replaces each such character with U+FFFD (the standard
> replacement character) and reports `string.illegal_xml_char` with
> `"error"` severity -- `strict=True` raises instead of silently substituting.
>
> **A string containing `\r`** is legal XML, but XML mandates line-ending
> normalization on parse (`\r` and `\r\n` both become `\n`), so it doesn't
> round-trip byte-for-byte. `write_xml` leaves `\r` as-is (no substitution
> needed) and reports it as `string.cr_normalized` so you know ahead of time
> the read-back value will differ.
>
> See [adjustment reports](../api.md#adjustment-reports-lossy-writes) to
> inspect any of these, or `strict=True` to raise instead of adjusting.

## Mixed content is rejected

**Mixed content** — non-whitespace text alongside child elements (either the
element's own leading text, or a child's trailing "tail" text) — is outside
the data-XML profile. `read_xml` raises `ParseError`, naming the element,
rather than silently discarding the text (which is what it used to do):

```python
from omnist import read_xml, ParseError

try:
    read_xml("<p>Hello <b>world</b></p>")   # text before a child element
except ParseError as e:
    print(e)   # $: mixed content (text alongside child elements) ...

try:
    read_xml("<p><b>world</b> tail</p>")    # text after a child element
except ParseError as e:
    print(e)   # $.b: mixed content ...
```

Whitespace-only text/tail — the shape pretty-printed XML has, including
`write_xml`'s own output — is unaffected and still parses:

```python
read_xml("<p>\n  <b>world</b>\n</p>")   # [('p', [('b', 'world')])]
```

## Notes

- **Not supported** (outside the data-XML profile): attributes and CDATA. A
  namespace prefix is stripped (`<n:a>` reads as `a`).
- See [the comparison table](overview.md#special-features-mapped-to-oml) for
  how XML's attribute- and namespace-dropping stack up against the other
  formats.
