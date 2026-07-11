# Worked example: modeling sitemap.xml

The fourth and last real, external format in this set — XML, and
deliberately the **clean contrast case** next to the other three.
Where `pyproject.toml`, `package.json`, and a GitHub Actions workflow
each hit unions and open key sets, the
[sitemaps.org protocol](https://www.sitemaps.org/protocol.html) mostly
doesn't. It surfaces a fourth gap type instead, one none of the other
three did.

Modeled against the sitemaps.org protocol page directly, retrieved
2026-07-11 — a genuine, small, **official** spec, not a guide and not a
third-party schema. Alongside pyproject.toml's PEPs, this is the most
formally specified format in the set.

Source, code, and fixtures:
[`examples/sitemap/`](https://github.com/omnist-dev/omnist/tree/master/examples/sitemap).
Schema: [`sitemap.osd`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/sitemap.osd).
Script: [`convert.py`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/convert.py).

## Run it

```
python3 examples/sitemap/convert.py
```

`read_xml` is called with `schema=` — and unlike every other example in
this set, it's **not** a no-op: `lastmod` is schema-typed `date`, so
schema-directed reading upgrades the ISO string to a real
`datetime.date`. See
[schema-directed deserialization](../deserialization.md) for the
general rule.

XML always has exactly one document element, so `sitemap.osd` needs the
same explicit wrapper record used in
[the order/address example](../example.md#the-schema)
(`record Root { "order": Order }` there; `record Root { "urlset":
UrlSet }` here) — not a gap, just XML's structural requirement.

## The fixtures

| File | OML | Arrays OML | What it is | What it exercises |
|---|---|---|---|---|
| [`minimal.xml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/minimal.xml) | [`.oml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/minimal.oml) | [`.arrays.oml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/minimal.arrays.oml) | The official example from the sitemaps.org protocol page, verbatim | The full, well-formed shape: `loc`, `lastmod`, `changefreq`, `priority`, all spec-valid |
| [`invalid-values.xml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/invalid-values.xml) | [`.oml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/invalid-values.oml) | [`.arrays.oml`](https://github.com/omnist-dev/omnist/blob/master/examples/sitemap/fixtures/invalid-values.arrays.oml) | Synthetic, written for this example — **not** sourced from any real site | `changefreq: sometimes` (not one of the spec's 7 allowed values) and `priority: 1.5`/`-0.2` (outside the spec's `[0.0, 1.0]` range) — both validate anyway |

`invalid-values.xml` has two `<url>` entries — its `.arrays.oml` is the one
example in this whole set where array collapse applies to a run of brace
subtrees combined with a schema-directed `date` upgrade (`lastmod`). See
[OML arrays](../formats/oml.md#arrays).

## What OSD can model exactly

Structurally, this is the **cleanest of the four examples**: all 4
`Url` fields (`loc`, `lastmod`, `changefreq`, `priority`) are closed and
checked. No unions, no open key sets, no cross-field constraints — the
format is simple enough that none of the first three gap categories
show up at all.

## What it can't, and why — a fourth gap: value refinement

The spec restricts `changefreq` to exactly 7 strings
(`always`/`hourly`/`daily`/`weekly`/`monthly`/`yearly`/`never`) and
`priority` to the numeric range `[0.0, 1.0]`. OSD's `string` and
`number` scalars check *type*, not *value* — there's no enum type and
no range constraint. `invalid-values.xml` demonstrates this directly:
`changefreq: sometimes` and `priority: 1.5` are both wrong per the
spec, and both pass validation cleanly, because a string is a string
and a number is a number as far as OSD's algebra is concerned.

None of the pyproject.toml, package.json, or GitHub Actions examples
surfaced this gap — they're messy enough (unions, open maps) that a
clean value-refinement violation never got the chance to show up on its
own. It took a genuinely simple, closed format to expose it. Worth
stating explicitly: **you don't see every gap in a schema language
until you test a format simple enough not to hide it behind bigger
ones.**

## Comparison note

XML itself has no native schema language either — but unlike TOML,
XML's own ecosystem long predates JSON Schema: **XSD** (XML Schema
Definition) is XML's own, decades-old, W3C-standardized schema
language, and it *can* express both gaps here directly — `xs:enumeration`
for `changefreq`, `xs:minInclusive`/`xs:maxInclusive` for `priority`.
This is the one example in the set where the "obvious" comparison
schema language is strictly more expressive than OSD on the exact gap
that shows up, not a wash of tradeoffs like the JSON Schema comparisons
elsewhere in this set.

See also: [the other three examples](index.md) for where the union and
open-map gaps come from instead.
