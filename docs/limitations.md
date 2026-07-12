# Known limitations

Omnist's schema algebra, formats, and depth handling are all deliberately
scoped. This page collects the edges in one place — each one is a design
decision documented in full elsewhere, not a bug waiting to be filed. Follow
the links for the reasoning and worked examples; this page is the map, not
the territory.

## The four expressiveness gaps

OSD's schema algebra can't express every shape a real-world format uses.
Running four external formats (none designed for Omnist) through the whole
pipeline surfaced exactly four gap categories — see
[Real-world examples: overview](examples/index.md#the-four-gap-categories-one-worked-example-of-each)
for the full taxonomy and worked examples from real fixtures:

1. **Union** — a field that's legitimately more than one shape (a string
   *or* a table). OSD's field type is always exactly one scalar or one
   `Ref`; there's no "A or B" combinator. See
   [pyproject.toml's `license`](examples/pyproject.md) and
   [GitHub Actions' three-way `on`](examples/github-actions.md).
2. **Open key set** — a record whose label set isn't fixed by the format.
   OSD records are closed by design; see
   [the openness design record](design/openness.md) for why `Map` was
   refused and `any` was shipped instead.
3. **Cross-field constraint** — a rule spanning sibling fields (a field
   required unless another says otherwise). OSD's cardinality is per-field
   only. See [pyproject.toml's `version`/`dynamic`](examples/pyproject.md).
4. **Value refinement** — the right *type* but a restricted *value* set or
   range (an enum, a numeric range). See
   [sitemap.xml's `changefreq`/`priority`](examples/sitemap.md), the only
   one of the four examples formal enough to expose this gap on its own.

## `any` and the vacuity of `compatible_with`

A field typed `any` accepts any value, unchecked — the escape hatch for
genuinely open-ended data. The cost is stated loudly in
[the schema model docs](schema.md#the-any-type): **checking ends exactly
where `any` begins**. `compatible_with` is vacuously `True` inside an `any`
region, because there is no structure left to compare — a schema that's 40%
`any` gives compatibility verdicts that are 40% meaningless while looking
authoritative.

```python
from omnist import parse_schema

s = parse_schema('''
record Event {
    "id":   string,
    "data": any,
}
root Event
''')

# Two independently-parsed but identical schemas compare equivalent --
# there's nothing inside `data`'s `any` region left to distinguish.
s2 = parse_schema('''
record Event {
    "id":   string,
    "data": any,
}
root Event
''')
assert s.equivalent(s2)
```

See [the openness design record](design/openness.md) for why `any` opens
only the value domain (never the label alphabet), and why that line is what
keeps the algebra decidable at all.

## The 200-level depth limit

Documents nest at most **200 levels** deep. The limit is `_MAX_DEPTH`, a
single shared constant enforced by every reader, every writer, and — as of
this release — `infer` and `validate` too, so the same document either
passes or fails consistently everywhere it's touched. Past the limit, a
reader raises a clean `DocumentError` (or `WriteError` on the write side)
naming the limit, rather than exhausting the call stack. See
[the API reference](api.md#reading--writing-formats) and each format page
(for example [XML](formats/xml.md#reading)) for the exact exception types.

```python
from omnist import doc, infer, DocumentError

deep = {"a": 1}
for _ in range(205):
    deep = {"a": deep}

try:
    infer([doc(deep)])
    raised = False
except DocumentError as e:
    raised = "nesting exceeds the maximum depth" in str(e)

assert raised
```

## Format lossiness

Every non-OML codec makes documented adjustments when a Document shape
doesn't map cleanly onto the target format — a stringified date, a
sanitized key, a dropped XML attribute. OML is the only format with zero
adjustments, because its edge-list syntax *is* the Document model rather
than a projection of it. See
[the formats overview's feature table](formats/overview.md#special-features-mapped-to-oml)
for the full list, and
[adjustment reports](api.md#adjustment-reports-lossy-writes) for how to
inspect (or `strict=True` to reject) any of them at write time. Each
per-format page ([JSON](formats/json.md), [YAML](formats/yaml.md),
[TOML](formats/toml.md), [XML](formats/xml.md)) documents its own specific
adjustments in context.

## XML's narrow data profile

The XML codec targets a deliberately narrow **data-XML** profile: elements
only, used to carry the same Documents as the other formats. Attributes and
CDATA are outside the profile and silently dropped on read, with no path
back out on write; namespace prefixes are stripped; mixed content (text
alongside child elements) is rejected outright rather than silently
discarded. See [XML](formats/xml.md#notes) for the full list of what's in
and out of scope, and why `defusedxml` is a hard dependency for security
reasons independent of the profile's narrowness.

## Performance is not a promise

Timings, memory use, and algorithmic constants may change between releases
without notice — see
[the stability policy](stability.md#stable-surfaces). Published
[benchmark numbers](why-omnist.md#performance) describe a point in time,
not a floor. A weekly, non-gating benchmark
(`.github/workflows/bench.yml`) prints current numbers to the CI log for
trend-watching, with no pass/fail threshold — shared-runner timings are too
noisy to gate on.

---

None of the above is accidental. Each gap traces back to a deliberate
line — decidability over expressiveness for the schema algebra, a narrow
and secure profile for XML, a shared depth bound over unbounded recursion.
Where a limitation can be worked around (tightening an `any` region with
`infer`, choosing OML for lossless storage), the linked pages above show
how.
