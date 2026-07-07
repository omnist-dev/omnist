# `any`: technical design specification

> **Status:** normative design specification, 2026-07-06.
> **Implementation approved by the maintainer, 2026-07-07** — execution
> follows §8 exactly.
> **`Map` is refused, final** (maintainer decision, 2026-07-06). The rationale
> lives in [openness.md](openness.md); this spec does not revisit it.
> Until `any` lands, [model.md](model.md) remains the authoritative
> description of the shipped model.
>
> **Audience:** implementing agents (sonnet/haiku tier) and their verifiers.
> Every design judgment is made *here*; an implementer following this spec
> should never have to decide anything — only translate. If a situation
> arises that this spec does not cover, the implementer must stop and
> report, not improvise.

## 1. Scope and non-goals

**In scope:** one new schema-side type, `any`, whose value is completely
unconstrained, integrated into every schema operation with the exact rules
of §3, proven sound in §4, tested per §5, and delivered per the plan in §8.

**Non-goals, explicitly:** no `Map` (refused, final); no unions, enums, or
multi-shape nullability (settled during original design); no change of any
kind to the Document model (§2.1 makes this an invariant, not an
observation); no change to `root` grammar; no change to OML; no inference
of `any` ever (§3, row I-19).

## 2. Model, grammar, and semantics

### 2.1 The Document model is untouched — invariant D-1

`any` is a *schema-side* construct only. The Document model — an ordered
list of labeled edges, values drawn from the seven scalar kinds plus
`null` plus nested edge-lists, `_MAX_DEPTH`-bounded, reader-enforced —
does not change in any way. No Document is representable after this
change that was not representable before, and vice versa. **Every PR in
§8 must leave `omnist/document.py` with a zero-line diff**; a verifier
finding any change there fails the PR.

### 2.2 The type lattice

Today a field's type is exactly one `Scalar` (one of seven kinds,
optionally nullable) or one `Ref` (naming a `Record`). `any` joins as the
**top element** ⊤ of the value lattice: it denotes the set of *all* legal
Document values.

<svg viewBox="0 0 640 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Type lattice with any at top">
  <style>
    .nd { fill:#f5f5f7; stroke:#999; rx:8; }
    .top { fill:#ede9fe; stroke:#7c3aed; stroke-width:2; }
    .bot { fill:#fde2e2; stroke:#c66; }
    .lb { font: 13px sans-serif; fill:#1a1a1a; text-anchor:middle; }
    .lbs { font: 11px sans-serif; fill:#555; text-anchor:middle; }
    .edge { stroke:#bbb; stroke-width:1.5; }
  </style>
  <rect class="top" x="270" y="15" width="100" height="34" rx="8"/>
  <text class="lb" x="320" y="37">any  (⊤)</text>
  <rect class="nd" x="30" y="110" width="90" height="30"/>
  <text class="lb" x="75" y="130">string</text>
  <rect class="nd" x="130" y="110" width="90" height="30"/>
  <text class="lb" x="175" y="130">integer</text>
  <rect class="nd" x="230" y="110" width="80" height="30"/>
  <text class="lb" x="270" y="130">… ×7</text>
  <rect class="nd" x="330" y="110" width="120" height="30"/>
  <text class="lb" x="390" y="130">Record R₁</text>
  <rect class="nd" x="460" y="110" width="120" height="30"/>
  <text class="lb" x="520" y="130">Record R₂ …</text>
  <rect class="bot" x="255" y="230" width="130" height="34" rx="8"/>
  <text class="lb" x="320" y="252">empty schema (⊥)</text>
  <line class="edge" x1="75"  y1="110" x2="300" y2="49"/>
  <line class="edge" x1="175" y1="110" x2="308" y2="49"/>
  <line class="edge" x1="270" y1="110" x2="316" y2="49"/>
  <line class="edge" x1="390" y1="110" x2="330" y2="49"/>
  <line class="edge" x1="520" y1="110" x2="345" y2="49"/>
  <line class="edge" x1="75"  y1="140" x2="300" y2="230"/>
  <line class="edge" x1="175" y1="140" x2="306" y2="230"/>
  <line class="edge" x1="270" y1="140" x2="313" y2="230"/>
  <line class="edge" x1="390" y1="140" x2="330" y2="230"/>
  <line class="edge" x1="520" y1="140" x2="345" y2="230"/>
  <text class="lbs" x="320" y="290">Every type T satisfies T ⊑ any. Containment between siblings is unchanged.</text>
</svg>

**Denotational semantics.** Let `V` be the set of all legal Document
values (the seven scalar kinds' values, `null`, and every legal
edge-list, recursively, depth-bounded by the Document model itself). The
language function `L` extends by exactly one clause:

- `L(Scalar s)` — unchanged (the kind's value set, plus `null` iff nullable).
- `L(Ref R)` — unchanged (the record's accepted edge-lists).
- **`L(any) = V`** — everything. In particular `null ∈ L(any)` and every
  edge-list of any shape ∈ `L(any)`.

**Field semantics unchanged.** A field `(label, any, [m,n])` constrains
the *count* of `label` occurrences to `[m,n]` exactly as today; each
occurrence's value is unconstrained. Cardinality logic lives in the
record layer, above the type dispatch — it is untouched.

**Why `any` is safe where `Map` was not** (rationale in openness.md §4;
restated here because implementers must internalize it): `Map` opens the
schema's *label alphabet*, which every algorithm reasons over. `any`
opens only the *value domain* at a declared leaf whose label stays fixed,
finite, and counted:

<svg viewBox="0 0 660 240" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Map opens labels, any opens a leaf value">
  <style>
    .pn { font: 600 13px sans-serif; fill:#1a1a1a; }
    .lb2 { font: 12px sans-serif; fill:#1a1a1a; }
    .bad { fill:#fde2e2; stroke:#c66; }
    .ok { fill:#dcfce7; stroke:#3a9; }
    .box { fill:#f5f5f7; stroke:#999; }
    .cap { font: 11px sans-serif; fill:#555; }
  </style>
  <text class="pn" x="40" y="26">Map (refused): open LABELS</text>
  <rect class="box" x="40" y="40" width="240" height="150" rx="8"/>
  <text class="lb2" x="55" y="65">record C {</text>
  <rect class="bad" x="70" y="76" width="130" height="22" rx="4"/>
  <text class="lb2" x="78" y="92">?anyKey?: string</text>
  <rect class="bad" x="70" y="104" width="130" height="22" rx="4"/>
  <text class="lb2" x="78" y="120">?anyKey?: string</text>
  <text class="lb2" x="78" y="146">… infinite labels …</text>
  <text class="lb2" x="55" y="172">}</text>
  <text class="cap" x="40" y="215">Infinite label alphabet — every algorithm's</text>
  <text class="cap" x="40" y="230">finite-alphabet assumption breaks.</text>
  <text class="pn" x="380" y="26">any (this spec): open VALUE at a leaf</text>
  <rect class="box" x="380" y="40" width="240" height="150" rx="8"/>
  <text class="lb2" x="395" y="65">record E {</text>
  <text class="lb2" x="410" y="90">"id": string</text>
  <text class="lb2" x="410" y="115">"data":</text>
  <rect class="ok" x="470" y="100" width="130" height="22" rx="4"/>
  <text class="lb2" x="478" y="116">any  ← value only</text>
  <text class="lb2" x="395" y="172">}</text>
  <text class="cap" x="380" y="215">Label "data" is fixed, declared, counted.</text>
  <text class="cap" x="380" y="230">Alphabet stays finite; algebra untouched.</text>
</svg>

### 2.3 The Python model object — normative

A new class in `omnist/schema.py`, **`AnyType`**, with a module-level
singleton. Exact requirements:

```python
class AnyType:
    """The `any` type: accepts every legal Document value. Singleton;
    use ``t.any``. Not a Scalar (it has no kind and no nullable flag —
    null is already included) and not a Ref (it names nothing)."""
    __slots__ = ()
    def __eq__(self, other: object) -> bool: return isinstance(other, AnyType)
    def __hash__(self) -> int: return hash(AnyType)
    def __repr__(self) -> str: return "t.any"

ANY = AnyType()
```

- The `Type` alias in `schema.py` becomes `Union[Ref, Scalar, AnyType]`.
- `Schema.resolve()` return type becomes `Union[Record, Scalar, AnyType]`;
  an `AnyType` resolves to itself (like a bare `Scalar`).
- Builder surface: `t.any` (a property on the `_Types` namespace returning
  `ANY`). `field("data", t.any)` and `field("x", t.any, min=0, max=None)`
  are legal.
- `nullable(t.any)` raises
  `SchemaError("any already includes null; 'any?' is redundant")`.
- Public exports: add `AnyType` to `omnist/__init__.py`'s imports and
  `__all__` (so users can `isinstance` against it). The singleton is
  reached via `t.any`; the bare name `ANY` is *not* exported.
- `AnyType` has **no** `.name` and **no** `.nullable` attribute — any code
  path that reaches for either on an `any` is a bug this spec's inventory
  (§3) exists to prevent.

### 2.4 Grammar — normative OSD delta

The OSD grammar's type production (docs/design/schema-osd-grammar.md)
changes from

```
type = scalar-name ["?"] / record-name
```

to

```
type = scalar-name ["?"] / "any" / record-name
```

with three hard rules:

1. **`any` is a reserved word.** A record named `any` is rejected at
   parse time with `SchemaError("'any' is a reserved type name and
   cannot be used as a record name at <pos>")`. Implementation: the
   existing record-name-vs-scalar-name check in `osd.py` (the
   `name in SCALAR_NAMES` guard near line 107) extends to a
   `RESERVED_TYPE_NAMES = SCALAR_NAMES | {"any"}` set. Rationale: field
   types resolve NAME → scalar-keyword-else-Ref, so an `any`-named
   record would be silently unreferenceable — reject loudly instead.
2. **`any?` is rejected** with `SchemaError("'any' already includes
   null; 'any?' is redundant at <pos>")`. Implementation: in the parser's
   `_type()` (osd.py ~line 171), the `any` branch checks for a following
   `?` token exactly the way scalar parsing does, and raises instead of
   accepting.
3. **The writer emits `any`.** `to_osd` of a schema containing `ANY`
   prints the bare keyword, pretty and compact modes alike. Round-trip
   `parse_schema(to_osd(s))` must be `equivalent` for schemas containing
   `any` (test obligation T-RT).

The `root` production is unchanged (`root NAME`, a record reference).
OML is unchanged (documents carry no types). The builder API and OSD are
the only two ways to construct an `any`-typed field.

## 3. Operation semantics and the dichotomy-site inventory

This is the spec's core. The current codebase dispatches on a
Scalar/Record (and Ref/not-Ref) dichotomy at 25 sites; Python will not
warn when a third kind slips through — it will misbehave silently.
Implementers work through this table as a checklist; verifiers audit
against it and additionally run
`grep -rn "isinstance.*Scalar\|isinstance.*Record\|isinstance.*Ref" omnist/ tools/`
to confirm no site exists outside the table.

Line numbers are as of `master` = `d48453f` (v0.4.3); re-locate by
pattern if drifted.

| ID | Site | Current behavior | Required change | Test obligation |
|---|---|---|---|---|
| I-1 | `schema.py` `Field.__init__` (~146): `isinstance(type, (Ref, Scalar))` | rejects other types | accept `AnyType`: `(Ref, Scalar, AnyType)`; update the error message to mention `t.any` | T-1: `field("x", t.any)` constructs; `field("x", "junk")` still raises |
| I-2 | `schema.py` `Type` alias | `Union[Ref, Scalar]` | add `AnyType` | mypy --strict green (gate) |
| I-3 | `schema.py` `Schema.resolve` (~244) | Scalar → itself; Ref → env lookup | `AnyType` → itself (new first branch); widen return annotation | T-3: `s.resolve(ANY) is ANY` |
| I-4 | `schema.py` `check_refs` (~257): walks field types, checks `isinstance(t, Ref)` | ignores non-Refs | **no change** — verify `AnyType` is skipped naturally | T-4: schema with `any` field passes `check_refs` |
| I-5 | `schema.py` `_conform` (~281): `if Scalar → _conform_scalar else _conform_record` | binary dispatch | new **first** branch: `if isinstance(d, AnyType): return` — accept, no descent, no errors added | T-5: `validate` accepts scalar/null/record/deep-nested at an `any` field; cardinality violations on the label still reported |
| I-6 | `schema.py` `nullable()` (~112) | wraps a Scalar | raise `SchemaError` on `AnyType` (message in §2.3) | T-6: `nullable(t.any)` raises |
| I-7 | `schema.py` `_Types` (~89) | seven scalar properties | add `any` property returning `ANY` | T-7: `t.any is t.any` (singleton) |
| I-8 | `osd.py` parser `_type` (~171-183): `text in SCALAR_NAMES → Scalar else Ref` | `any` would become `Ref("any")` → later "unknown type" | new branch before the Ref fallback: `"any"` → return `ANY`; reject following `?` (§2.4 rule 2) | T-8: parse `"data": any`; `any?` raises with specified message |
| I-9 | `osd.py` record-name guard (~107) | rejects scalar-named records | extend to `RESERVED_TYPE_NAMES` incl. `"any"` (§2.4 rule 1) | T-9: `record any { ... }` raises with specified message |
| I-10 | `osd.py` writer `_type` (~242): `isinstance(t, Ref) → name else scalar+"?"` | would hit `.name`/`.nullable` on `AnyType` → AttributeError | new branch: `AnyType` → `"any"` | T-10 / T-RT: write+reparse round-trip `equivalent` |
| I-11 | `deserialize.py` `_materialize_type` (~58): Scalar → scalar path else record path | binary dispatch | new **first** branch: `if isinstance(d, AnyType): return node` — pass-through, no upgrades, no errors | T-11: inside `any`, ISO date strings stay strings while sibling `datetime` fields upgrade; YAML-native dates pass through as dates |
| I-12 | `subschema.py` `_sub` (~48-53): Scalar/Scalar → `_scalar_sub`; Record/Record → `_record_sub`; else False | mixed kinds → False | two new clauses **before** the existing ones, in this order: `if isinstance(db, AnyType): result = True` ; `elif isinstance(da, AnyType): result = False` | T-12: `T ⊑ any` True for every T incl. records and nullable scalars; `any ⊑ T` False for every non-any T; `any ⊑ any` True |
| I-13 | `subschema.py` vacuous-A-side check (~40): `isinstance(ta, Ref) and not sat` | Ref-only | **no change** — `AnyType` is always satisfiable, never vacuous | covered by T-12 |
| I-14 | `signature.py` `local_signature` (~46): Ref → one tag shape, Scalar → kind/nullable tag | binary | `AnyType` → its own distinct tag, e.g. `("any",)` — distinct from all seven scalar tags, from nullable variants, and from the Ref tag | T-14: two records differing only string-vs-any have different signatures |
| I-15 | `minimize.py` refinement key (~106): `block_of[name] if Ref else None` | AnyType → falls to `None`, same key as scalars | **no code change, but the correctness argument is subtle and must be tested**: `None` is safe *only because* I-14 already separates any-fields from scalar-fields in the initial partition (partition refinement never merges blocks split at initialization) | T-15: `normalize` never merges a record with `field: any` into one with `field: <scalar>`; records identical incl. `any` fields do merge |
| I-16 | `minimize.py` rebuild (~120): Ref → remap, else keep | keeps type as-is | **no change** — verify `ANY` passes through by identity | covered by T-15 round-trip |
| I-17 | `prune.py` satisfiability seed (~50): `isinstance(f.type, Scalar)` → satisfiable | `any` field would not seed satisfiability → record wrongly unsatisfiable | extend: `isinstance(f.type, (Scalar, AnyType))` | T-17: `record R { "x": any }` is satisfiable; `is_empty` False; `prune` keeps it |
| I-18 | `prune.py` optional-dead-ref drops (~117, ~129) / `extract.py` Ref checks (~89, ~118) | Ref-only logic | **no change** — `any` behaves as a leaf exactly like a scalar; verify | T-18: `extract` keeps an `any` field when its label is requested, drops it when not (subject to existing min-cardinality rules) |
| I-19 | `infer.py` | never constructs `AnyType` (imports don't include it) | **no change**; add the guard as a *test*, not code | T-19: property test — for arbitrary generated documents, the inferred schema contains no `AnyType` anywhere |
| I-20 | `isomorphic.py` `_walk` (~93): Ref → recurse, else leaf | signature equality (I-14) already distinguishes | **no change** — verify | T-20: iso oracle agrees with `equivalent` on schema pairs containing `any` |
| I-21 | `tools/semantic_oracle.py` `_minimal_value` (~331): Scalar → leaf, Ref → record | AttributeError on `AnyType` | new branch: `AnyType` → `None` (null is a legal minimal witness: `null ∈ L(any)`) | T-21: oracle unit test |
| I-22 | `tools/semantic_oracle.py` universe/truth machinery | enumerates finite truth | see §5.3 — behavior analysis, plus generator extension | T-22 |
| I-23 | `omnist/__init__.py` | — | export `AnyType` (imports + `__all__`). **Lands in PR-2, not PR-1** (release-safety: the public surface must not expose `any` before the parser can read it back — see §8) | T-23: `from omnist import AnyType` works; api.md documents it |
| I-24 | `omnist/cli.py` | schema-transparent | **no change** | T-24: integration — `omnist validate --schema <any-schema>` and `omnist schema format/normalize` work end-to-end |
| I-25 | writers / `check_*` (`formats.py`) | operate on Documents only | **no change** — an `any` subtree is an ordinary Document subtree; existing writer adjustment rules apply unchanged | covered by existing suites + T-11 |

**Placement rule for all new branches:** the `AnyType` clause always goes
**first** in each dispatch (before Scalar/Record checks). This is a
consistency convention so verifiers can audit by pattern, and it
guarantees no pre-existing branch can shadow the new kind.

### 3.1 `validate` — descent stops at `any`

<svg viewBox="0 0 640 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="validate descends the tree and stops at any">
  <style>
    .n3 { fill:#f5f5f7; stroke:#999; }
    .anyn { fill:#ede9fe; stroke:#7c3aed; stroke-width:2; }
    .skip { fill:#fafafa; stroke:#ccc; stroke-dasharray:4 3; }
    .t3 { font: 12px sans-serif; fill:#1a1a1a; text-anchor:middle; }
    .t3m { font: 11px sans-serif; fill:#777; text-anchor:middle; }
    .ar { stroke:#3a9; stroke-width:2; marker-end:url(#ah); }
    .arx { stroke:#ccc; stroke-width:1.5; stroke-dasharray:4 3; }
  </style>
  <defs><marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#3a9"/></marker></defs>
  <rect class="n3" x="270" y="12" width="110" height="30" rx="6"/><text class="t3" x="325" y="32">Event (root)</text>
  <rect class="n3" x="60" y="90" width="90" height="30" rx="6"/><text class="t3" x="105" y="110">id: string ✓</text>
  <rect class="n3" x="170" y="90" width="100" height="30" rx="6"/><text class="t3" x="220" y="110">type: string ✓</text>
  <rect class="n3" x="290" y="90" width="130" height="30" rx="6"/><text class="t3" x="355" y="110">created: datetime ✓</text>
  <rect class="anyn" x="440" y="90" width="100" height="30" rx="6"/><text class="t3" x="490" y="110">data: any ✓</text>
  <line class="ar" x1="300" y1="42" x2="115" y2="88"/>
  <line class="ar" x1="315" y1="42" x2="225" y2="88"/>
  <line class="ar" x1="335" y1="42" x2="355" y2="88"/>
  <line class="ar" x1="360" y1="42" x2="480" y2="88"/>
  <rect class="skip" x="400" y="170" width="200" height="60" rx="6"/>
  <text class="t3m" x="500" y="192">subtree of any shape</text>
  <text class="t3m" x="500" y="210">never visited — accepted as-is,</text>
  <text class="t3m" x="500" y="224">no descent, no conversions</text>
  <line class="arx" x1="490" y1="120" x2="495" y2="168"/>
  <text class="t3m" x="140" y="200">Cardinality of the "data" label is still counted</text>
  <text class="t3m" x="140" y="216">by the record layer — only the VALUE is skipped.</text>
</svg>

### 3.2 `compatible_with` — the two new clauses

<svg viewBox="0 0 660 280" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="containment decision flow with any clauses">
  <style>
    .dc { fill:#fffbeb; stroke:#d97706; }
    .rs { fill:#dcfce7; stroke:#3a9; }
    .rf { fill:#fde2e2; stroke:#c66; }
    .old { fill:#f5f5f7; stroke:#999; }
    .t4 { font: 12px sans-serif; fill:#1a1a1a; text-anchor:middle; }
    .t4s { font: 11px sans-serif; fill:#555; text-anchor:middle; }
    .fl { stroke:#888; stroke-width:1.5; marker-end:url(#ah2); }
  </style>
  <defs><marker id="ah2" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#888"/></marker></defs>
  <rect class="dc" x="230" y="10" width="200" height="34" rx="8"/><text class="t4" x="330" y="32">_sub(A-side da, B-side db)</text>
  <rect class="dc" x="80" y="80" width="180" height="34" rx="8"/><text class="t4" x="170" y="102">db is any?  (NEW #1)</text>
  <rect class="rs" x="80" y="140" width="180" height="30" rx="8"/><text class="t4" x="170" y="160">True — any absorbs all</text>
  <rect class="dc" x="300" y="80" width="180" height="34" rx="8"/><text class="t4" x="390" y="102">da is any?  (NEW #2)</text>
  <rect class="rf" x="300" y="140" width="180" height="30" rx="8"/><text class="t4" x="390" y="160">False — only any holds any</text>
  <rect class="old" x="510" y="80" width="140" height="90" rx="8"/>
  <text class="t4" x="580" y="110">existing logic</text>
  <text class="t4s" x="580" y="130">Scalar/Scalar,</text>
  <text class="t4s" x="580" y="146">Record/Record,</text>
  <text class="t4s" x="580" y="162">else False</text>
  <line class="fl" x1="290" y1="44" x2="185" y2="78"/>
  <line class="fl" x1="330" y1="44" x2="385" y2="78"/>
  <line class="fl" x1="370" y1="44" x2="565" y2="78"/>
  <line class="fl" x1="170" y1="114" x2="170" y2="138"/>
  <line class="fl" x1="390" y1="114" x2="390" y2="138"/>
  <text class="t4s" x="120" y="76">yes</text>
  <text class="t4s" x="345" y="76">yes (db not any)</text>
  <text class="t4s" x="480" y="66">neither is any</text>
  <text class="t4s" x="330" y="230">Order matters: check db first. Both any → first clause fires → True (correct: any ≡ any).</text>
  <text class="t4s" x="330" y="250">Memoization, coinduction, and the vacuous-A-side rule are untouched.</text>
</svg>

### 3.3 `materialize` (schema-directed deserialization) — upgrade/degrade rules

At an `any` position, `materialize` returns the node **exactly as the
reader produced it** — the `schema=None` behavior, scoped to the subtree:

- No upgrades: an ISO date *string* inside `any` stays a string (while a
  sibling `datetime`-typed field converts as today).
- No degrades either: a YAML/TOML-native `date` object inside `any` stays
  a `date` object — pass-through means *identity*, not normalization.
- No validation errors can originate inside `any`; the conformance
  guarantee (`materialize`'s output conforms to the schema) holds
  trivially there since `L(any) = V`.
- Writers are unaffected (I-25): writing an `any` subtree applies the
  same per-format adjustment rules (`WriteReport`) any Document gets.

## 4. Soundness: `any` is unambiguous and every operation stays decidable

**4.1 Single-candidate principle (no union ambiguity).** The historical
refusals (unions, multi-shape nulls, open records, `Map`) all failed one
test: a value matching *more than one candidate* with no principled
winner. `any` passes it: a field's declared type is still exactly one of
{one Scalar, one Ref, `any`} — validation at any node consults exactly
one candidate and never chooses. `infer` never emits `any` (I-19), so no
Record-vs-any inference ambiguity exists either — that rule is not a
carve-out but a consequence of `infer`'s "most specific schema" contract,
since `any` is never most-specific.

**4.2 Containment is decidable and the lattice is bounded.** The `⊑`
relation gains exactly the rules of I-12. Termination of the coinductive
`_sub` is preserved: its memo table is keyed by pairs of resolved
definitions, of which there remain finitely many (the environments are
finite; `ANY` adds one element). Completeness of the two clauses follows
from `L(any) = V`: `L(T) ⊆ V` always (so `db = any` → True is sound and
complete), and `V ⊆ L(T)` iff `L(T) = V` iff `T = any` (no Scalar or
satisfiable Record accepts *every* value — e.g. no Record accepts scalar
leaves, no Scalar accepts edge-lists). With ⊤ = the `any`-accepting
schema and ⊥ = the empty schema, `⊑` is a bounded preorder.

**4.3 Normalization stays canonical.** `normalize` is partition
refinement over local signatures. I-14 makes `any` an eighth atomic kind
in the signature; the initial partition therefore never co-locates an
any-field record with a scalar-field record, and refinement only ever
*splits* blocks — so the `None` refinement key at I-15 can never cause a
wrong merge. Minimality and canonicality arguments are otherwise
untouched, because `any` participates as an atomic, non-referencing leaf
— exactly the role scalars already play in the proof.

**4.4 Interaction matrix.** Each cell is the normative answer an
implementer can test against:

| interaction | rule |
|---|---|
| `any` vs `null` value | accepted (`null ∈ L(any)`); no `any?` exists |
| `any` vs cardinality `[m,n]` | count enforced on the label as today; `[0,]`, `[1,]`, `[2,5]` all legal |
| `any` vs `Ref` cycles | `any` names nothing and cannot participate in a cycle; `check_refs` unaffected |
| `any` field vs unsatisfiable sibling | record satisfiability = all mandatory fields satisfiable; `any` is always satisfiable (I-17) and never rescues an unsatisfiable sibling |
| `Scalar s ⊑ any` / `Record R ⊑ any` | True / True |
| `any ⊑ Scalar s` / `any ⊑ Record R` | False / False |
| `any ⊑ any` / `any ≡ any` | True / True; `any ≡ T` for non-any T: False |
| `extract` at `any` | leaf: kept/dropped wholesale by its own label |
| `materialize` inside `any` | identity pass-through (§3.3) |
| `infer` | never produces `any` under any input |

## 5. Testing and correctness strategy

**5.1 Unit obligations.** Every inventory row I-1…I-25 carries a named
test obligation (T-1…T-24, T-RT); the implementation PRs (§8) enumerate
which they discharge. Project bar applies throughout: full suite green,
`ruff`, `mypy --strict`, **100% line coverage** on every touched file,
and every new doc example executed as a test.

**5.2 Property-based fuzzing.** Extend the hypothesis schema-generation
strategy in `tests/test_fuzz.py`: with probability ~0.15 a generated
field's type is `ANY` (instead of a scalar/ref). Document generators, at
`any` positions, draw from a "chaos" strategy producing arbitrary legal
Document values (all seven scalar kinds, `null`, and nested edge-lists to
bounded depth). Existing round-trip and metamorphic properties then
exercise `any` automatically: OSD round-trip (`T-RT`), validate/accepts
agreement, `normalize` preserving `equivalent`, `prune` preserving the
language, and `compatible_with` reflexivity/transitivity samples.

**5.3 The semantic oracle — analysis and required treatment.** The
oracle brute-force-compares algebra answers against set-theoretic truth
over a finite document universe `U`. With `any`:

- **`db = any` direction:** truth over `U` says every `L(A)∩U ⊆ U` —
  agrees with the algebra's True. No change needed.
- **`da = any` direction (the subtle one):** the algebra answers False,
  but over a small `U`, `B` might accept everything in `U` — finite truth
  cannot *witness* the False. This is exactly the situation the oracle's
  existing **vindication / needs-review machinery** was built for: an
  unvindicated False is reported `needs_review`, not `definite_bug`.
  Required treatment: (a) ensure `U` always contains at least one value
  per scalar kind plus one edge-list — then any `B` that is a Scalar or
  Record fails to accept *something* in `U`, vindicating the False
  concretely (a Record accepts no scalar leaf; a Scalar accepts no
  edge-list); with that guarantee, `da = any` cases are always vindicated
  and never even reach needs_review; (b) add an oracle unit test pinning
  this (T-22).
- **Generators:** the oracle's seeded random schema family optionally
  emits `any` fields (small fixed probability), and `_minimal_value`
  returns `None` for `AnyType` (I-21).

**5.4 Executable documentation.** The worked examples in openness.md §8
(envelope schema, compatibility blind spot, pass-through) move from
"illustrative" to executable doc-tests in `tests/test_docs.py` when the
feature lands, per the project's docs-as-tests convention.

## 6. Impact on the model's philosophy — and the claims audit

**The honest headline change:** "closed by construction" becomes
**"closed by default; open only where explicitly marked."** The
weakening is real and deliberately purchased; what keeps it principled is
that openness is *demarcated* — every hole is a literal `any` token,
grep-visible and code-reviewable — and the tool never introduces one
(`infer` never emits it). The differentiator claim survives precisely:
it was never "no escape hatch"; it was a *decidable algebra*, which §4
shows is preserved. The sharpest practical cost stays what openness.md
§9.2 says: `compatible_with` is locally vacuous inside `any` — checking
ends exactly where `any` begins — and the docs must say so loudly at
every mention.

**Claims audit — enumerated rewrite sites** (the docs PR works through
this list, then runs
`grep -rn "closed by construction\|escape hatch\|no unions" README.md docs/`
to catch stragglers):

| Site | Required change |
|---|---|
| `docs/design/model.md` §1, headline idea 4 | The clause "no structureless escape hatches (`Any`, open objects, maps)" **splits**: open objects and maps remain refused; `any` becomes the model's one deliberate, contained opening, cross-referencing this spec and openness.md |
| `README.md` | Re-word any "closed by construction" phrasing; one sentence introducing `any` with its cost |
| `docs/why-omnist.md` | Same re-wording; the decidability differentiator stays, stated precisely |
| `docs/schema.md` | Document `any` as the eighth type keyword: semantics, `any?` rejection, reserved-word rule, the §3.3 pass-through, and the vacuous-compatibility warning |
| `docs/deserialization.md` | Add the pass-through subsection (§3.3 content, with a runnable example) |
| `docs/api.md` | `t.any`, `AnyType` export, `nullable(t.any)` error; types table row |
| `docs/glossary.md` | New `any` entry |
| `docs/design/schema-osd-grammar.md` | Type production + reserved words + worked example row (backed by `test_grammar_docs.py`) |
| `docs/testing.md` | Oracle witness note (§5.3) |
| `docs/design/openness.md` | Status header flips `any` from "decision deferred" to "adopted, spec at any-type-spec.md" — **only in the PR that ships the feature** |
| `CHANGELOG.md` | v0.5.0 entry: new capability, minor bump, the §6 headline change stated honestly |

## 7. Remaining perspectives

- **Security.** No new surface: readers enforce Document legality and
  `_MAX_DEPTH` *before* any schema logic runs; an `any` subtree is parsed
  by exactly the same reader code as today. `any` never causes parsing,
  evaluation, or resource use that `schema=None` doesn't already.
- **Performance.** Strictly favorable: `validate`/`materialize` skip
  entire subtrees at `any` positions; algebra operations add O(1)
  branches. No benchmark gate needed, but the existing perf-measurement
  habit (before/after timing on the standard corpus) applies to PR-1.
- **Error-message quality.** Two new, specified error messages (§2.4);
  a schema author typo like `"x": Any` (capitalized) is a `Ref("Any")` →
  existing "unknown type 'Any'" error — acceptable, no special case.
- **Interop (future, not this change).** A JSON-Schema importer, if ever
  built, gains a lossless target: `additionalProperties: true`/`{}` and
  `xs:any` map to `any`. Noted so the importer design doesn't rediscover it.
- **Governance.** The lint dial (count/flag `any` usage per schema)
  remains deliberately out of scope (openness.md §10.5), noted for later.
- **The unserved gap, restated.** Natively-validated open-key data with
  per-value typing is served by neither `any` nor the entry-list
  encoding. `any` does not close it and must not be advertised as doing
  so. If that need ever becomes pressing, the debate restarts from
  openness.md — not from a fifth disguise of the same question.

## 8. Implementation plan

Four PRs, strictly sequenced — master remains sound after every merge
because **grammar exposure lands only in PR-2**, after every operation
already handles the new kind; until then `any` in OSD text still fails
with today's "unknown type" error and the only construction path is the
builder, which PR-1 fully supports and tests.

<svg viewBox="0 0 660 210" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PR sequence">
  <style>
    .pr { fill:#ede9fe; stroke:#7c3aed; stroke-width:1.5; }
    .pr2 { fill:#f5f5f7; stroke:#999; }
    .t5 { font: 600 12px sans-serif; fill:#1a1a1a; text-anchor:middle; }
    .t5s { font: 11px sans-serif; fill:#444; text-anchor:middle; }
    .fl2 { stroke:#7c3aed; stroke-width:2; marker-end:url(#ah3); }
  </style>
  <defs><marker id="ah3" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#7c3aed"/></marker></defs>
  <rect class="pr" x="15" y="50" width="140" height="80" rx="10"/>
  <text class="t5" x="85" y="75">PR-1 · sonnet</text>
  <text class="t5s" x="85" y="93">model + all ops</text>
  <text class="t5s" x="85" y="108">+ writer + builder</text>
  <text class="t5s" x="85" y="123">I-1..7, 10..21, 23</text>
  <rect class="pr" x="185" y="50" width="140" height="80" rx="10"/>
  <text class="t5" x="255" y="75">PR-2 · sonnet</text>
  <text class="t5s" x="255" y="93">parser + reserved</text>
  <text class="t5s" x="255" y="108">words + round-trips</text>
  <text class="t5s" x="255" y="123">I-8, I-9, grammar doc</text>
  <rect class="pr" x="355" y="50" width="140" height="80" rx="10"/>
  <text class="t5" x="425" y="75">PR-3 · sonnet</text>
  <text class="t5s" x="425" y="93">oracle witness +</text>
  <text class="t5s" x="425" y="108">fuzz strategies</text>
  <text class="t5s" x="425" y="123">I-22, §5.2–5.3</text>
  <rect class="pr2" x="525" y="50" width="120" height="80" rx="10"/>
  <text class="t5" x="585" y="75">PR-4 · haiku</text>
  <text class="t5s" x="585" y="93">docs sweep (§6)</text>
  <text class="t5s" x="585" y="108">CHANGELOG, bump</text>
  <text class="t5s" x="585" y="123">0.5.0 + release</text>
  <line class="fl2" x1="155" y1="90" x2="183" y2="90"/>
  <line class="fl2" x1="325" y1="90" x2="353" y2="90"/>
  <line class="fl2" x1="495" y1="90" x2="523" y2="90"/>
  <text class="t5s" x="330" y="170">Each PR: issue-first (spec §-references in the body) → implement → suite/ruff/mypy/coverage →</text>
  <text class="t5s" x="330" y="188">independent verifier (fresh agent, checks against the §3 inventory) → merge → sync clones.</text>
</svg>

**PR-1 — core model and algebra (sonnet; the critical one).**
Files: `omnist/schema.py`, `omnist/deserialize.py`, `omnist/osd.py`
(writer only), `omnist/ops/{subschema,signature,prune}.py` (code),
`omnist/ops/{minimize,extract,isomorphic}.py` + `omnist/infer.py`
(verification-only rows), `tools/semantic_oracle.py` (I-21 only), new
tests. Discharges I-1..I-7, I-10..I-21 with tests T-1..T-7, T-10..T-21.
**No public export in this PR** (I-23 lands in PR-2): `AnyType`/`ANY`
stay reachable only via `omnist.schema` internally, and PR-1's tests
import them from there. Release-safety invariant: if master had to be
released between PR-1 and PR-2, the feature would be publicly invisible. Acceptance: all inventory rows
marked code-change are implemented with the `AnyType`-clause-first
convention; all rows marked no-change have the specified regression test
proving it; the verifier greps for dichotomy sites and finds none outside
the table; suite/ruff/mypy/coverage green; before/after timing on the
standard corpus shows no regression. *The one intentional gap:* OSD
*parsing* of `any` still fails ("unknown type") — a test pins this
interim behavior and is removed in PR-2.

**PR-2 — grammar exposure (sonnet).** Files: `omnist/osd.py` (parser),
`docs/design/schema-osd-grammar.md`, `tests/test_grammar_docs.py`,
round-trip tests, plus the public export (I-23: `omnist/__init__.py`,
moved here from PR-1 for release-safety). Discharges I-8, I-9, I-23,
T-8, T-9, T-23, T-RT; removes PR-1's interim-behavior test. Acceptance:
both specified error messages byte-match §2.4; round-trip `equivalent`
property holds under fuzz; after this PR the feature is functionally
complete and safe to release even undocumented.

**PR-3 — verification infrastructure (sonnet).** Files:
`tools/semantic_oracle.py` (universe guarantee + generator emission of
`any`), `tests/test_fuzz.py`, `tests/test_semantic_oracle.py`.
Discharges I-22, T-22, §5.2. Acceptance: oracle run over the standard
budget reports zero definite bugs and zero needs-review attributable to
`any` (per §5.3's vindication argument); fuzz suite green at full budget.

**PR-4 — docs, claims audit, release (haiku — fully mechanical given
§6's table).** Files: every row of the §6 table, version bump to
**0.5.0** in the usual four files, CHANGELOG. Acceptance: every table row
done; the §6 grep returns no unreviewed hits; `test_docs.py` executes the
new examples (added here, mirroring the docs); tag `v0.5.0` after merge;
release verified on the PyPI **Simple index**; both clones synced.

**Verification protocol (all PRs):** the implementing agent never merges;
an independent fresh-context verifier checks the diff against this spec's
inventory (§3) and rules (§2, §4), re-runs all gates, and — for PR-1 —
re-derives at least the I-12 and I-15 correctness arguments against the
actual code. Controller merges only on a clean verdict.

**Risk register.**

| Risk | Mitigation |
|---|---|
| A dichotomy site missed by the inventory | Verifier's mandatory grep (§3 preamble) + clause-first convention makes new-kind handling visually auditable |
| Silent wrong-merge in `normalize` (I-15's subtlety) | T-15 regression pair + §4.3 argument re-derived by PR-1's verifier |
| Oracle false comfort at `any` positions | §5.3(a) universe guarantee makes `da = any` Falses concretely vindicated, not waved through |
| Docs claim drift ("closed by construction" survives somewhere) | §6 enumerated table + closing grep gate in PR-4 |
| Scope creep toward `Map`/unions during implementation | §1 non-goals; implementers stop-and-report on anything not covered by this spec |

## 9. Decision record

- **`Map`: refused, final** (maintainer, 2026-07-06). openness.md is the
  rationale of record; §3 of that document answers all future
  label-alphabet-opening proposals.
- **`any`: fully specified by this document; implementation approved by
  the maintainer 2026-07-07.** The §8 issues are filed and executed in
  sequence, shipping as v0.5.0.
