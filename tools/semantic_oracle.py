#!/usr/bin/env python3
"""Brute-force semantic oracle for the schema algebra (issue #158, PR-4 of
the #154 review's execution plan).

Checks every schema-algebra operation against **set-theoretic ground
truth** -- the actual language ``L(s) = {d in U : s.validate(Doc(d)).ok}``
of a schema ``s`` over a finite, enumerated universe ``U`` of documents --
rather than against another algorithm. This is a *third*, independent
check: ``compatible_with`` (paper Algorithm 4, ``omnist/ops/subschema.py``)
and the minimize+isomorphism Theorem-4 oracle (``omnist/ops/isomorphic.py``,
cross-checked in ``tests/test_fuzz.py``) are two algorithms that could both
share the same conceptual bug; brute-force enumeration against ``validate()``
itself cannot, since ``validate()`` is the ground truth definition of a
schema's language in the first place.

Originates from the full-codebase review in issue #154 (D2): "the review's
strongest tool should live in the repo."

Usage::

    python3 tools/semantic_oracle.py

Exits 1 (and prints every definite bug found) if any check fails in a way
that proves a real algebra bug; exits 0 otherwise, having printed the
summary counts (universe size, schema count, pairs checked, vindication
breakdown, extract cases).

**Deliberate universe-sizing deviation from the #154 review.** The
review's own run enumerated 8,557 (base) / 13,093 (extended) documents.
This script's universe -- built from the same description (root edge-lists
over labels ``{a, b}``, leaves ``{1, "x", None}``, children leaf or
depth-1, extended shapes witnessing cardinality up to 4) -- lands at
different exact counts (see ``build_universe()``\\'s docstring) because the
review's own enumeration code was not available to reproduce verbatim;
this is a fresh, independently-derived construction from the review's
prose. Both land in the same order of magnitude and exercise the same
shape space; see the PR description for the actual counts and wall time
from a run of this script (measured around ~110s on a modest dev machine
-- somewhat over the review's original "~1-2 min" framing but still in the
same ballpark; the dominant cost is ``normalize``/``prune``/``extract``
each re-validating the full document universe per schema, which is
inherent to brute-force ground-truth checking at this universe size).
"""

from __future__ import annotations

import datetime as _dt
import itertools
import os
import sys
import time
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# Allow running as `python3 tools/semantic_oracle.py` (repo root not on
# sys.path in that case) without requiring the package to be installed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omnist.document import Doc  # noqa: E402
from omnist.errors import SchemaError  # noqa: E402
from omnist.ops import compatible_with, extract, is_empty, normalize, prune  # noqa: E402
from omnist.schema import AnyType, Field, Record, Ref, Scalar, Schema, t  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Universe construction
# ---------------------------------------------------------------------------

LEAVES: Tuple[object, ...] = (1, "x", None)
LABELS: Tuple[str, ...] = ("a", "b")

Node = Tuple[Tuple[str, object], ...]  # our own tuple-edge-list shape


def to_doc(node: object) -> Doc:
    """Build a :class:`Doc` from a (possibly nested) tuple-edge-list
    ``Node``. ``Doc``'s internal-node check is ``isinstance(x, list)``
    (see ``document.py``'s ``Doc.is_leaf``) -- a *tuple* edge list, which
    is what this module builds throughout (tuples are hashable, so
    universe/witness shapes can live in ``set``s), reads as a scalar leaf
    if handed to ``Doc`` directly. This recursively converts every nested
    edge-list tuple to a list so ``Doc`` sees the shape correctly at every
    depth, not just the root.
    """
    if isinstance(node, tuple) and (len(node) == 0 or (
            len(node) > 0 and isinstance(node[0], tuple) and len(node[0]) == 2
            and isinstance(node[0][0], str))):
        return Doc([(label, _to_node(child)) for label, child in node])
    return Doc(node)


def _to_node(v: object) -> object:
    """The recursive half of :func:`to_doc`: convert a possibly-nested
    edge-list tuple to the list-of-edges shape ``Doc``/``document.py``
    expect, leaving genuine leaf values untouched."""
    if isinstance(v, tuple) and (len(v) == 0 or (
            isinstance(v[0], tuple) and len(v[0]) == 2 and isinstance(v[0][0], str))):
        return [(label, _to_node(child)) for label, child in v]
    return v


def _edge_runs(child_pool: Tuple[object, ...], max_count: int) -> List[Tuple[object, ...]]:
    """Every ordered tuple of length ``0..max_count`` drawn (with
    repetition) from ``child_pool`` -- the possible edges for *one* label."""
    runs: List[Tuple[object, ...]] = []
    for c in range(max_count + 1):
        runs.extend(itertools.product(child_pool, repeat=c))
    return runs


def _label_pair_shapes(child_pool: Tuple[object, ...], max_count: int) -> List[Node]:
    """Every root-shaped edge list over ``LABELS``, each label independently
    getting ``0..max_count`` edges from ``child_pool``."""
    runs = _edge_runs(child_pool, max_count)
    shapes: List[Node] = []
    for a_run in runs:
        for b_run in runs:
            edges = tuple([("a", v) for v in a_run] + [("b", v) for v in b_run])
            shapes.append(edges)
    return shapes


def build_universe(base_max: int = 2, extended_max: Tuple[int, ...] = (3, 4)
                    ) -> Tuple[List[Node], List[Node]]:
    """Build ``(base, extended)`` document universes as lists of raw edge-
    list nodes (``Doc`` is constructed lazily by the caller).

    * **Base**: root edge-lists over ``{a, b}``, ``0..base_max`` edges per
      label; each edge's child is either a leaf (``1``, ``"x"``, ``None``)
      or a depth-1 edge list (itself over ``{a, b}``, leaf-valued, at most
      one edge total -- kept small so the child pool stays tractable; see
      the module docstring re: sizing).
    * **Extended**: base, plus (a) roots with 3-4 edges under a single
      label (cardinality witnesses beyond the base cap) and (b) 1-edge
      roots whose single child is itself a nested list with 3-4 edges
      (witnessing cardinality one level down) -- exactly the two shapes
      the issue names.
    """
    depth1 = tuple(s for s in _label_pair_shapes(LEAVES, base_max) if len(s) <= 1)
    child_pool = LEAVES + depth1
    base = _label_pair_shapes(child_pool, base_max)

    extra: Set[Node] = set()
    # (a) roots of 3-4 leaf edges under one label.
    for lbl in LABELS:
        for count in extended_max:
            for combo in itertools.product(LEAVES, repeat=count):
                extra.add(tuple((lbl, v) for v in combo))
    # (b) 1-edge roots with a 3-4-edge nested list child.
    nested: List[Node] = []
    for lbl2 in LABELS:
        for count in extended_max:
            for combo in itertools.product(LEAVES, repeat=count):
                nested.append(tuple((lbl2, v) for v in combo))
    for lbl in LABELS:
        for n in nested:
            extra.add(((lbl, n),))

    base_set = set(base)
    extended = base + [s for s in extra if s not in base_set]
    return base, extended


# ---------------------------------------------------------------------------
# 2. Schema family: systematic + structural + seeded-random
# ---------------------------------------------------------------------------

_SCALARS: Tuple[Scalar, ...] = (
    t.string, t.integer, t.number, t.boolean, t.date, t.time, t.datetime,
)
_CARDS: Tuple[Tuple[int, Optional[int]], ...] = (
    (1, 1), (0, 1), (0, 2), (1, None), (0, 0), (2, 2),
)


def systematic_family() -> List[Schema]:
    """One single-record, single-field schema per (scalar x cardinality)
    combination: ``7 scalars * 6 cardinalities = 42`` schemas."""
    out = []
    for sc in _SCALARS:
        for mn, mx in _CARDS:
            out.append(Schema(Ref("R"), {"R": Record([Field("a", sc, mn, mx)])}))
    return out


def structural_family() -> List[Schema]:
    """A handful of schemas exercising shapes the systematic family can't:
    an empty record, a known-empty mandatory self-cycle, and optional
    self-recursion."""
    empty_record = Schema(Ref("R"), {"R": Record([])})

    mandatory_cycle = Schema(Ref("R"), {
        "R": Record([Field("self", Ref("R"), 1, 1)]),
    })  # every document must contain itself forever -- unsatisfiable

    optional_self_recursion = Schema(Ref("R"), {
        "R": Record([
            Field("child", Ref("R"), 0, None),
            Field("v", t.integer, 0, 1),
        ]),
    })

    return [empty_record, mandatory_cycle, optional_self_recursion]


def nullable_family() -> List[Schema]:
    """One nullable/non-nullable pair per scalar at a fixed cardinality
    (``[1, 1]``): ``compatible_with``'s ``_scalar_sub`` treats "nullable A
    vs non-nullable B" as a definite mismatch (a nullable field can emit
    ``null``, which a non-nullable one must reject), so a schema whose
    field is ``string?`` must never be ``compatible_with`` one whose same-
    label field is plain ``string``. Kept separate from
    :func:`systematic_family`, which is deliberately non-nullable-only, so
    this nullable-vs-non-nullable contrast is guaranteed present in the
    schema family regardless of what the seeded-random family happens to
    generate -- this is exactly the code path issue #158's mutation
    self-check (dropping ``_scalar_sub``'s nullable check) breaks, and it
    should not depend on random-seed luck to be exercised.
    """
    out = []
    for sc in _SCALARS:
        out.append(Schema(Ref("R"), {"R": Record([Field("a", sc, 1, 1)])}))
        out.append(Schema(Ref("R"), {"R": Record([Field("a", Scalar(sc.name, True), 1, 1)])}))
    return out


def _seeded_random_family(seed: int, count: int) -> List[Schema]:
    """``count`` two-record schemas built from a small deterministic PRNG
    (stdlib ``random``, fixed seed -- no new test dependency, fully
    reproducible across runs)."""
    import random
    rng = random.Random(seed)
    out = []
    labels = ["p", "q", "r"]
    for i in range(count):
        # Record A has 1-3 fields; some scalar, at most one a Ref to B.
        n_fields_a = rng.randint(1, 3)
        fields_a = []
        used_labels: Set[str] = set()
        has_ref = False
        for _ in range(n_fields_a):
            lbl = rng.choice(labels)
            if lbl in used_labels:
                continue
            used_labels.add(lbl)
            mn, mx = rng.choice(_CARDS)
            if not has_ref and rng.random() < 0.5:
                fields_a.append(Field(lbl, Ref("B"), mn, mx))
                has_ref = True
            else:
                sc = rng.choice(_SCALARS)
                if rng.random() < 0.3:
                    sc = Scalar(sc.name, True)
                fields_a.append(Field(lbl, sc, mn, mx))
        if not fields_a:  # pragma: no cover -- defensive fallback that is
            # actually unreachable: n_fields_a = rng.randint(1, 3) is always
            # >= 1, and the loop's *first* iteration can never hit the
            # `lbl in used_labels` skip (used_labels starts empty), so at
            # least one field is always appended. Kept as a guard in case
            # the loop bounds above ever change.
            fields_a = [Field("p", t.string, 0, 1)]

        n_fields_b = rng.randint(1, 2)
        fields_b = []
        used_b: Set[str] = set()
        for _ in range(n_fields_b):
            lbl = rng.choice(labels)
            if lbl in used_b:
                continue
            used_b.add(lbl)
            mn, mx = rng.choice(_CARDS)
            sc = rng.choice(_SCALARS)
            fields_b.append(Field(lbl, sc, mn, mx))
        if not fields_b:  # pragma: no cover -- same reasoning as the
            # `fields_a` fallback above: n_fields_b = rng.randint(1, 2) is
            # always >= 1 and the first loop iteration can never skip, so
            # fields_b can never end up empty. Kept as a guard in case the
            # loop bounds above ever change.
            fields_b = [Field("q", t.integer, 0, 1)]

        out.append(Schema(Ref("A"), {"A": Record(fields_a), "B": Record(fields_b)}))
    return out


def schema_family(random_count: int = 82, seed: int = 158) -> List[Schema]:
    """The full family: systematic (42) + structural (3) + nullable (14) +
    seeded-random (default 82) = 141 schemas, matching the review's
    reported count."""
    return (systematic_family() + structural_family() + nullable_family()
            + _seeded_random_family(seed, random_count))


# ---------------------------------------------------------------------------
# 3. Ground truth: L(s) over a universe, as a bitset-friendly index
# ---------------------------------------------------------------------------

def ground_truth(schema_list: List[Schema], docs: List[Doc]) -> List[FrozenSet[int]]:
    """For each schema, the set of doc-indices it accepts (``L(s)`` as
    indices into ``docs``)."""
    out = []
    for s in schema_list:
        accepted = frozenset(i for i, d in enumerate(docs) if s.validate(d).ok)
        out.append(accepted)
    return out


# ---------------------------------------------------------------------------
# 4. Targeted minimal witness construction (for vindicating False answers)
# ---------------------------------------------------------------------------

_MINIMAL_LEAF: Dict[str, object] = {
    "string": "x",
    "integer": 1,
    # A float, not an int: `number` accepts both, but `integer` accepts
    # only ints (`_scalar_sub` in ops/subschema.py makes integer a subtype
    # of number, never the reverse) -- an int leaf would satisfy `integer`
    # too and fail to distinguish "number" from "integer" as a witness.
    "number": 1.5,
    "boolean": True,
    "date": _dt.date(2000, 1, 1),
    "time": _dt.time(0, 0),
    "datetime": _dt.datetime(2000, 1, 1, 0, 0),
}


def _minimal_value(schema: Schema, ty, depth: int, building: FrozenSet[str]) -> object:
    """A minimal Document value for field type ``ty`` -- a leaf for a
    Scalar, or an edge-list built from that record's own mandatory fields
    for a Ref. ``building`` guards against infinite recursion through a
    mandatory cycle (returns an empty edge-list if hit -- deliberately
    "wrong" for a cyclic mandatory record, but such a record is
    unsatisfiable anyway, so no minimal witness exists for it)."""
    if isinstance(ty, AnyType):
        return None  # null is a legal minimal witness: null in L(any)
    if isinstance(ty, Scalar):
        return _MINIMAL_LEAF[ty.name]
    if ty.name in building or depth > 50:
        return ()  # cycle guard -- unsatisfiable record, no real witness exists
    rec = schema.env[ty.name]
    edges = []
    for f in rec.fields:
        if f.min < 1:
            continue
        v = _minimal_value(schema, f.type, depth + 1, building | {ty.name})
        for _ in range(f.min):
            edges.append((f.label, v))
    return tuple(edges)


def minimal_witness(schema: Schema) -> Node:
    """The smallest document ``schema``'s root record *requires*: ``min``
    copies of a minimal value per mandatory field, recursively. If the
    root has no mandatory fields, this is the empty edge list (``()``)."""
    root_ty = schema.root
    node = _minimal_value(schema, root_ty, 0, frozenset())
    return node if isinstance(node, tuple) else ()


def targeted_witnesses(schema: Schema) -> List[Node]:
    """A small family of candidate witnesses for ``schema``, not just the
    single mandatory-fields-only skeleton: the base :func:`minimal_witness`
    alone often can't distinguish two schemas that agree on every
    mandatory field but differ on an *optional* field's type, or that
    differ only at a cardinality boundary -- the all-mandatory skeleton
    never populates an optional field at all, and always uses exactly
    ``min`` copies of a mandatory one, so it can't expose a mismatch that
    only shows up above the minimum count. For each field of the root
    record (mandatory or optional), this adds variants of the base witness
    with that field forced to appear ``min`` (already covered by the base
    witness itself when ``min >= 1``), ``max(min, 1)``, ``max(min, 1) + 1``,
    (when bounded) exactly ``max`` and ``max + 1`` times, and -- when
    *unbounded* (``max is None``) -- a handful of counts up to 5, since an
    unbounded field on ``a``'s side is exactly the shape that trips up a
    tighter bounded ``max`` on ``b``'s side, and only a large-enough count
    exposes that (a fixed small ceiling here is a deliberate, documented
    bound: the schema family's own bounded cardinalities top out at 2, so
    5 comfortably covers every ``max`` any schema in the family declares).
    """
    base = minimal_witness(schema)
    root_rec = schema.env[schema.root.name]
    out = [base]
    for f in root_rec.fields:
        v = _minimal_value(schema, f.type, 1, frozenset({schema.root.name}))
        rest = tuple(e for e in base if e[0] != f.label)
        counts = {max(f.min, 1), max(f.min, 1) + 1}
        if f.max is not None:
            counts.add(f.max)
            counts.add(f.max + 1)
        else:
            counts.update({3, 4, 5})
        for n in sorted(c for c in counts if c >= 0):
            out.append(rest + tuple((f.label, v) for _ in range(n)))
    return out


# ---------------------------------------------------------------------------
# 5. The five checks
# ---------------------------------------------------------------------------

class OracleResult:
    def __init__(self) -> None:
        self.definite_bugs: List[str] = []
        self.needs_review: List[str] = []
        self.counts: Dict[str, int] = {}


def check_compatible_with(schemas: List[Schema], truth: List[FrozenSet[int]],
                           ext_docs: List[Doc], ext_truth: List[FrozenSet[int]],
                           result: OracleResult) -> None:
    """(1) Definite-bug direction: ``compatible_with(a, b)`` True must mean
    ``L(a) subset L(b)`` over the BASE universe -- any counterexample here
    is an unambiguous algebra bug (the base universe is what ``truth`` was
    computed over, and a True answer is an unconditional claim).

    (2) False answers get *vindicated*: first check the extended universe
    for a doc where ``a`` accepts but ``b`` doesn't (a witness the base
    universe was simply too small to contain); if the extended universe
    also fails to distinguish them, fall back to a targeted minimal
    witness built from ``a``'s cardinality/type requirements. A witness
    accepted by both ``a`` and ``b`` is reported as needs-manual-review
    (a bounded-universe artifact, not a failure); a witness rejected by
    ``a`` itself means the witness-construction heuristic didn't apply
    here (also needs-manual-review, not an algebra bug) -- it never marks
    ``compatible_with`` wrong in this branch, since a False answer can
    only be a *definite* bug in the other direction (case 1).
    """
    n = len(schemas)
    checked_pairs = 0
    false_total = 0
    vindicated_by_base_subset = 0
    vindicated_by_extended = 0
    vindicated_by_witness = 0
    needs_review_pairs = 0

    for i in range(n):
        for j in range(n):
            checked_pairs += 1
            a, b = schemas[i], schemas[j]
            answer = compatible_with(a, b)
            la, lb = truth[i], truth[j]
            if answer:
                if not la.issubset(lb):
                    bad = sorted(la - lb)[:1]
                    result.definite_bugs.append(
                        f"compatible_with(schema[{i}], schema[{j}]) says True but "
                        f"L(a) is not subset of L(b): base-universe doc index "
                        f"{bad} is accepted by a, rejected by b")
                continue
            # answer is False -- already vindicated if base truth shows a
            # counterexample (the common, expected case).
            false_total += 1
            if not la.issubset(lb):
                vindicated_by_base_subset += 1
                continue
            # Base universe agrees with both (la subset lb) even though
            # compatible_with said False -- try the extended universe.
            ela, elb = ext_truth[i], ext_truth[j]
            if not ela.issubset(elb):
                vindicated_by_extended += 1
                continue
            # Still no witness -- try a small family of targeted witnesses:
            # the mandatory-only skeleton, plus one variant per field with
            # that field forced present (and, when bounded, repeated to its
            # max) -- see targeted_witnesses()'s docstring for why a single
            # all-mandatory witness misses mismatches on optional fields.
            found = False
            for witness in targeted_witnesses(a):
                wd = to_doc(witness)
                wa = a.validate(wd).ok
                wb = b.validate(wd).ok
                if wa and not wb:
                    vindicated_by_witness += 1
                    found = True
                    break
            if not found:
                needs_review_pairs += 1
                result.needs_review.append(
                    f"compatible_with(schema[{i}], schema[{j}]) says False; no "
                    f"witness found in base/extended universes or any "
                    f"targeted witness -- needs manual review, not treated "
                    f"as a failure")

    result.counts["pairs_checked"] = checked_pairs
    result.counts["false_answers"] = false_total
    result.counts["vindicated_by_base_subset"] = vindicated_by_base_subset
    result.counts["vindicated_by_extended"] = vindicated_by_extended
    result.counts["vindicated_by_witness"] = vindicated_by_witness
    result.counts["needs_review_pairs"] = needs_review_pairs


def check_is_empty(schemas: List[Schema], truth: List[FrozenSet[int]],
                    result: OracleResult) -> None:
    """(3) ``is_empty(s)`` True must mean ``L(s)`` is empty over the base
    universe. (The converse -- ``L(s)`` empty over our *finite* universe
    but ``is_empty`` False -- is not a bug: the universe might simply lack
    a witness for a genuinely-satisfiable schema, e.g. one needing a
    document shape outside what we enumerated. So only the True direction
    is checked here, matching check (1)'s asymmetry.)"""
    checked = 0
    for i, s in enumerate(schemas):
        checked += 1
        if is_empty(s) and truth[i]:
            result.definite_bugs.append(
                f"is_empty(schema[{i}]) says True but L(s) is non-empty over "
                f"the base universe (doc index {sorted(truth[i])[:1]})")
    result.counts["is_empty_checked"] = checked


def check_normalize_prune_preserve_language(
        schemas: List[Schema], truth: List[FrozenSet[int]], docs: List[Doc],
        result: OracleResult) -> None:
    """(4) ``L(normalize(s)) == L(s)`` and ``L(prune(s)) == L(s)`` EXACTLY
    (both directions) over the base universe."""
    checked = 0
    for i, s in enumerate(schemas):
        checked += 1
        la = truth[i]
        for name, op in (("normalize", normalize), ("prune", prune)):
            s2 = op(s)
            l2 = frozenset(k for k, d in enumerate(docs) if s2.validate(d).ok)
            if l2 != la:
                extra = sorted(l2 - la)[:1]
                missing = sorted(la - l2)[:1]
                result.definite_bugs.append(
                    f"{name}(schema[{i}]) changes the language over the base "
                    f"universe: extra={extra} missing={missing}")
    result.counts["normalize_prune_checked"] = checked


_EXTRACT_LABEL_SETS: List[FrozenSet[str]] = [
    frozenset(), frozenset({"a"}), frozenset({"b"}), frozenset({"a", "b"}),
    frozenset({"p"}), frozenset({"q"}), frozenset({"p", "q"}),
    frozenset({"p", "q", "r"}),
]


def check_extract(schemas: List[Schema], docs: List[Doc], truth: List[FrozenSet[int]],
                   doc_labels: List[FrozenSet[str]], result: OracleResult) -> None:
    """(5) ``L(extract(s, keep)) == {d in L(s) : labels(d) subset keep}``,
    both directions, over the base universe -- skipping cases where
    ``extract`` raises ``SchemaError`` (no valid subschema for that
    ``keep`` set; not this oracle's concern, per the issue).

    Reuses ``truth`` (``s``'s own ground-truth ``L(s)``, already computed
    once per schema by :func:`ground_truth`) and precomputed top-level
    ``doc_labels`` instead of re-validating ``s`` and re-walking each doc's
    edges per ``(schema, keep)`` pair -- this check used to dominate the
    tool's runtime (``extract``-side validation of the *extracted* schema
    is unavoidable and still happens once per doc per case, but the
    ground-truth side is now a set lookup).
    """
    checked = 0
    skipped = 0
    for i, s in enumerate(schemas):
        la = truth[i]
        for keep in _EXTRACT_LABEL_SETS:
            try:
                extracted = extract(s, keep)
            except SchemaError:
                skipped += 1
                continue
            checked += 1
            for k, d in enumerate(docs):
                expected = (k in la) and doc_labels[k].issubset(keep)
                actual = extracted.validate(d).ok
                if expected != actual:
                    result.definite_bugs.append(
                        f"extract(schema[{i}], {sorted(keep)}) disagrees with "
                        f"ground truth on base-universe doc index {k}: "
                        f"expected={expected} actual={actual}")
                    break  # one counterexample per (schema, keep) is enough
    result.counts["extract_cases_checked"] = checked
    result.counts["extract_cases_skipped"] = skipped


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(random_count: int = 96, verbose: bool = True) -> OracleResult:
    t0 = time.time()
    base_nodes, ext_nodes = build_universe()
    base_docs = [to_doc(n) for n in base_nodes]
    ext_docs = [to_doc(n) for n in ext_nodes]
    if verbose:
        print(f"universe: base={len(base_docs)} docs, extended={len(ext_docs)} docs "
              f"({time.time() - t0:.2f}s)")

    t1 = time.time()
    schemas = schema_family(random_count=random_count)
    if verbose:
        print(f"schema family: {len(schemas)} schemas ({time.time() - t1:.2f}s)")

    t2 = time.time()
    truth = ground_truth(schemas, base_docs)
    ext_truth = ground_truth(schemas, ext_docs)
    if verbose:
        print(f"ground truth computed over base+extended universes "
              f"({time.time() - t2:.2f}s)")

    doc_labels = [frozenset(lbl for lbl, _ in d.edges()) if not d.is_leaf else frozenset()
                  for d in base_docs]

    result = OracleResult()
    t3 = time.time()
    check_compatible_with(schemas, truth, ext_docs, ext_truth, result)
    check_is_empty(schemas, truth, result)
    check_normalize_prune_preserve_language(schemas, truth, base_docs, result)
    check_extract(schemas, base_docs, truth, doc_labels, result)
    if verbose:
        print(f"checks run ({time.time() - t3:.2f}s)")
        print(f"total wall time: {time.time() - t0:.2f}s")

    if verbose:
        print()
        print("=== Summary ===")
        print(f"documents: base={len(base_docs)}, extended={len(ext_docs)}")
        print(f"schemas: {len(schemas)}")
        for k, v in result.counts.items():
            print(f"  {k}: {v}")
        print(f"needs-manual-review pairs: {len(result.needs_review)} "
              "(not a failure -- bounded-universe artifact, per issue #158)")
        print(f"DEFINITE BUGS: {len(result.definite_bugs)}")
        for msg in result.definite_bugs[:20]:
            print(f"  BUG: {msg}")

    return result


def main() -> int:
    result = run(verbose=True)
    if result.definite_bugs:
        print(f"\nFAILED: {len(result.definite_bugs)} definite bug(s) found.")
        return 1
    print("\nPASSED: zero definite bugs.")
    return 0


if __name__ == "__main__":  # pragma: no cover -- process-entry scaffolding.
    # `main()` itself is fully exercised (via mocking `run`, see
    # tests/test_semantic_oracle.py's test_main_* tests), but this guard
    # only runs
    # when the file is executed as `python3 tools/semantic_oracle.py`, never
    # on import -- and main()'s real (unmocked) `run()` call takes ~110s
    # (see the module docstring), too slow to invoke as a subprocess from
    # the normal test suite just to cover this one line.
    sys.exit(main())
