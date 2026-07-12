# Stability policy

What you can build on in Omnist's **beta** series, what may still change,
and how changes are made when they happen.

Omnist is beta as of v0.7.0. Beta means the surfaces listed under
[Stable surfaces](#stable-surfaces) below are now worth building on: they
change only through the [deprecation cycle](#deprecation-policy), never
silently between releases. It does **not** mean 1.0 — see
[Beta is not 1.0](#beta-is-not-10) for what remains open.

This policy covers behavior, not wording. Where the docs already state a
caveat, this page points to it rather than restating it, so there is one
authoritative description of each limit and no second copy to drift.

## Stable surfaces

Changes to anything in this section go through a deprecation cycle.

### The Document and Schema models

Both models as defined in [the model spec](design/model.md). On the
Document side: a Document is an **ordered list of labeled edges** (not a
map), a node is either a scalar of one of the **seven scalar kinds**
(`string`, `integer`, `number`, `boolean`, `date`, `time`, `datetime`)
or such an edge list, **repeated labels** are how arrays appear, and
**edge order is data** — preserved on round-trip, never a schema
constraint. On the Schema side: a field's type is exactly one of those
seven scalars (optionally nullable), a `Ref` to a named record, or
**`any`** (the one declared-leaf opening, shipped in v0.5.0), with
per-field `[min,max]` cardinality; records are closed. These sets of
building blocks are stable; neither model grows a new value kind, an
array value type, a union, or an open-record construct without a
deprecation cycle.

### The OSD and OML grammars

Existing OSD and OML syntax keeps parsing, with the same meaning, across
the beta series. The normative grammars are
[the OML-Core grammar](design/oml-grammar.md) and
[the OSD grammar](design/schema-osd-grammar.md), both verified against the
parsers.

Grammar changes are **additive only**: new syntax may be introduced, but
text that parses today keeps parsing to the same Document or Schema. The
precedent is already on the record — `#` comments and `[...]` arrays were
both added to OML this way (see the [Comments](formats/oml.md#comments) and
[Arrays](formats/oml.md#arrays) sections), as pure additions that left every
older file's meaning untouched. Both are documented one-way sugar
(comments are discarded and never re-emitted; `[...]` is parse-time sugar
for repeated edges, not a value) — a shape this policy preserves but does
not re-describe here.

### The public API

Every name exported from the `omnist` package — its `__all__`, documented
name by name with signatures in [the API reference](api.md) — is stable:
the names remain importable, their signatures remain call-compatible, and
their documented behavior holds. This is the surface you import against.

Behavior that the docs describe is part of the promise; behavior they leave
unspecified is not (see [May-change surfaces](#may-change-surfaces)).

### Exception types

The exception **types** raised by the public API — the hierarchy in
[`omnist/errors.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/errors.py)
(`OmnistError` and its subclasses `SchemaError`, `ParseError`,
`WriteError`, `DocumentError`, `DetachedNode`), all exported from `omnist`
— are stable, as is **which kind of operation raises which** (a parse
outside the supported profile raises `ParseError`; a lossy write under
`strict=True` raises `WriteError`; an illegal Document value or operation
raises `DocumentError`; and so on, as documented in [the API
reference](api.md)). You can catch these types and branch on them.

The **text** of an error message is not stable — see below.

## May-change surfaces

These carry no stability promise and may change in any release, without a
deprecation cycle. Do not build parsing or control flow on them.

- **Error message text.** The exception *types* are stable (above); the
  human-readable message string is not. Match on the type, and — for the
  CLI — on the machine-readable `code` (below), never on message wording.
- **CLI human-readable output formatting.** The default, text-mode layout
  of the `omnist` command is for humans and may be reformatted. The
  **machine-readable output is stable where documented**: the global
  [`--json` mode](cli.md#machine-mode---json), its stable `code` values,
  and the [exit codes](cli.md#machine-mode---json) (identical with and
  without `--json`) are the contract for scripts and CI. Drive automation
  off `--json` and the exit code.
- **Everything under `docs/design/`.** These are design records and
  formal-derivation notes — the *why*, and internal reasoning. The
  normative grammars they contain are stable as grammars (above), but the
  surrounding design commentary, private-helper names, and internal
  algorithm descriptions are not an API.
- **Performance characteristics.** Timings, memory use, and algorithmic
  constants may change between releases. Published
  [numbers](why-omnist.md#performance) describe a point in time, not a
  floor.
- **Anything explicitly marked experimental.** If a feature's own docs
  call it experimental or provisional, this policy does not cover it until
  that marking is removed.

Format-specific lossiness is not a change surface at all — it is documented
per format (for example XML attribute and namespace non-support; see [the
non-goals](why-omnist.md) and each format page). Those are existing,
documented limits, governed by the same additive/deprecation discipline as
everything else.

## Deprecation policy

When a stable surface must change, the change is staged, not abrupt:

1. **Deprecate in one minor release.** The old behavior keeps working. A
   runtime `DeprecationWarning` is emitted where feasible, and the
   deprecation is recorded in
   [`CHANGELOG.md`](https://github.com/omnist-dev/omnist/blob/master/CHANGELOG.md)
   with the
   replacement to move to.
2. **Remove no earlier than the following minor release.** Removal never
   happens in the same minor release that announced the deprecation; there
   is always at least one minor release in which both the warning and the
   old behavior are present, so a pin to that release is a safe place to
   migrate from.

"Where feasible" is honest: a pure grammar or type-shape change cannot
always carry a runtime warning. Every deprecation gets the CHANGELOG entry
regardless; the runtime warning is added wherever the code path allows one.

## Beta is not 1.0

Beta says the surfaces above are worth building on. It does **not** claim
the model is final.

v1.0 remains gated on the openness decision — specifically the `any` type
recorded in [the openness design record](design/openness.md). `any` shipped
in v0.5.0 and is a stable part of the model *as it stands*, but the
project's 1.0 commitment is a stronger, once-and-for-all statement about
the whole model, and that statement is not one this project is ready to
make while the openness question's consequences (chiefly that
`compatible_with` is locally vacuous inside `any`) are still being lived
with in practice.

So, plainly:

- **Beta claims:** the stable surfaces change only through the deprecation
  cycle for the duration of the 0.x beta series.
- **Beta does not claim:** that no stable surface will ever be deprecated,
  or that the model is frozen. 1.0 is where "frozen" gets promised, and 1.0
  is deliberately still ahead.

## Reporting a stability break

If a release changes a stable surface without going through the deprecation
cycle above — existing valid OSD/OML stops parsing or changes meaning, an
`__all__` name disappears or changes signature, an operation starts raising
a different exception type — that is a bug in this policy's terms, not an
expected change. Please report it:

<https://github.com/omnist-dev/omnist/issues>

Include the version you moved from and to, and a minimal snippet that
behaved differently.
