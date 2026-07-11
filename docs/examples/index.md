# Real-world examples: overview

Four real, external formats — none designed for Omnist — each run
through the whole pipeline: an OSD schema, real fixtures, validation,
OML output. Together they're a stress test of the codecs and a candid
account of what OSD's schema algebra can and can't express, across
formats with very different amounts of design discipline behind them.

| Example | Format | Spec rigor | Fields | Closed | `any` | `any` % | Gaps exercised |
|---|---|---|---|---|---|---|---|
| [pyproject.toml](pyproject.md) | TOML | Multiple PEPs (517/621/639/794) | 20 | 13 | 7 | 35% | Union, open key set, cross-field |
| [package.json](package-json.md) | JSON | None — prose docs only, third-party schema | 16 | 8 | 8 | 50% | Union, open key set |
| [GitHub Actions workflow](github-actions.md) | YAML | None — prose docs only, third-party schema | 8 | 2 | 6 | 75% | Union (3-way), open key set, shape-depends-on-sibling-key |
| [sitemap.xml](sitemap.md) | XML | One small, official XSD spec | 4 | 4 | 0 | 0% | Value refinement (enum/range) |

All four counts are computed directly from the schemas by
`tests/test_examples_*.py`, not typed by hand — the table above can't
silently drift from what `parse_schema` actually reports.

## The spec-rigor spectrum

Ordered by how much formal ground truth each format actually has:
**pyproject.toml** (several numbered PEPs, each enumerating exact field
shapes) → **sitemap.xml** (one small, official, narrow XSD) →
**GitHub Actions workflows** (a community-maintained schema only,
never an official GitHub artifact, though you can at least *observe*
real CI runs to check behavior) → **package.json** (no spec and no
official schema at all — just years of accreted convention).

The `any` proportion doesn't track schema size or effort — it tracks
**where a format sits on this spectrum**. `pyproject.toml` has the most
fields and the lowest `any` fraction; the GitHub Actions workflow
schema is the smallest of the four by field count and still comes out
worst, because `jobs:` alone is irreducibly open and carries most of a
workflow's real content. Sitemap.xml, the most formally specified
format after pyproject.toml, is the only one of the four with zero
`any` fields at all.

## The four gap categories, one worked example of each

1. **Union** — a field that's legitimately more than one shape.
   `pyproject.toml`'s `license` (a string *or* a table) is the simplest
   case; GitHub Actions' `on` (string, array, *or* map) is the sharpest,
   a genuine three-way union. OSD's field type is always exactly one
   scalar or one `Ref` — there's no "A or B" combinator.
2. **Open key set** — a record where the label set isn't fixed by the
   format, it's chosen by whoever writes the file. `[tool]` in
   pyproject.toml, `dependencies` in package.json, `jobs` in GitHub
   Actions workflows. OSD records are closed by design — see
   [the openness design record](../design/openness.md) for why that's
   deliberate, not an oversight.
3. **Cross-field constraint** — a rule spanning sibling fields, like
   pyproject.toml's `version` being required unless `"version"` appears
   in `dynamic`. OSD's cardinality is per-field only.
4. **Value refinement** — a field with the right *type* but a
   restricted *value* set or range. Only sitemap.xml surfaced this:
   `changefreq` restricted to 7 enumerated strings, `priority`
   restricted to `[0.0, 1.0]`. It took the cleanest, most tightly
   specified format in the set to expose this gap — the messier formats
   never got clean enough to show it on its own.

## If you're designing a format for OSD

Lessons drawn from all four examples, not just pyproject.toml:

1. **Avoid same-key polymorphism.** `readme`/`license` (pyproject.toml)
   and `author`/`bugs`/`repository` (package.json) being a string *or*
   a table under one key is the single biggest source of unchecked
   surface across this whole set. If a format needs both a short and a
   long form of something, use **different keys**, not one polymorphic
   key.
2. **Hoist open keys into their own namespace.** `[tool]` in
   pyproject.toml does this correctly — all openness lives in one
   dedicated, clearly-open section. `urls`/`scripts`/`entry-points`
   scattered through pyproject.toml's otherwise-closed `[project]`
   table, and GitHub Actions' `jobs`/`env`/`defaults` mixed alongside
   closed fields like `name`, don't. If part of a structure needs
   arbitrary keys, give it its own top-level section.
3. **Avoid conditional requiredness across sibling fields** ("at least
   one of A or B," "A required unless B says otherwise"). Pick one
   canonical, always-required field instead of an either/or.
4. **Avoid meta-referential fields** — a field whose *value* names
   other fields and changes their shape or requiredness.
   pyproject.toml's `dynamic` (a list of field names that make those
   fields optional) and GitHub Actions' `steps:` (each item's shape
   depends on whether `uses:` or `run:` is present) are both instances
   of this. No static schema language can express it; it requires
   runtime interpretation of the data to know what shape is even
   expected.
5. **If you need restricted values, say so in the spec explicitly, and
   expect most schema languages to only enforce the type, not the
   restriction.** sitemap.xml's `changefreq`/`priority` show this isn't
   even about *open-endedness* — a small, fully closed format can still
   have unchecked value constraints if the schema language it's checked
   against has no enum or range type.
6. **Silent forward-extension of a closed section is a versioning
   problem, not a modeling one.** pyproject.toml's `import-names`/
   `import-namespaces` arriving after the fact is the example here — if
   a section needs to grow over time, decide upfront whether it's
   genuinely closed (and accept that growth needs an explicit version
   marker) or genuinely open (and give it its own namespace from day
   one).

The common thread: OSD models cleanly whatever a format's design keeps
**structurally uniform, value-restricted where it matters, and
unconditional**. Every gap in this set traces back to a format that
didn't hold one of those three lines — usually because its real
validator is prose plus executable code, which was never forced to
commit to them in the first place.

## Read the four in order

1. [pyproject.toml](pyproject.md) — the most formally specified format
   in the set; the baseline for all three gap categories before value
   refinement.
2. [package.json](package-json.md) — no spec at all; a smaller schema
   with a *higher* `any` fraction than pyproject.toml's, showing the
   proportion tracks the format's own rigor, not schema size.
3. [GitHub Actions workflow](github-actions.md) — the worst `any`
   fraction of the four, plus a real codec-level finding (YAML 1.1's
   boolean-coercion rule breaking the ordinary `on:` key).
4. [sitemap.xml](sitemap.md) — the clean contrast case, and the one
   that surfaces the fourth gap type the other three couldn't.
