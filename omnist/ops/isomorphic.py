"""Schema isomorphism -- the paper's Algorithm 3, step 3.

Theorem 4 (the paper): two schemas are equivalent iff their minimized
(normalized) forms are isomorphic. That gives a second, algorithm-
independent decision procedure for ``equivalent`` -- structurally unrelated
to bidirectional ``compatible_with`` (``ops/subschema.py``), so the two can
be cross-checked against each other in tests (see ``docs/testing.md``,
"the dual-algorithm oracle").

``_isomorphic`` stays private to this module -- ``Schema.equivalent()``
remains the public API's canonical definition of schema equality,
unchanged (issue #279). This module now has two legitimate consumers of
the same underlying check: the independent property-test oracle described
above, and the public ``Schema.isomorphic_to()`` (``omnist/schema.py``), a
deliberately narrower, additional operation for callers who need to
detect structural differences that ``equivalent()``'s document-language-
only definition cannot see -- e.g. two schemas that accept the same
documents only because a bug merged what should have been two distinct
records (the exact false-negative ``equivalent()`` misses, and
``_isomorphic`` catches, that motivated exposing this publicly).

Algorithm: parallel traversal from both roots, building a bijection
``name_a -> name_b`` (and its inverse) between env record names as the
traversal discovers pairs. At each visited record pair, ``local_signature``
must match (same target-blind shape); since ``local_signature`` sorts
fields by label and ref/scalar shape is part of the key, fields on the two
sides line up one-to-one by label once the signatures agree. For each
ref-typed field, the two targets are recursively required to be
isomorphic, with the bijection enforced consistently in both directions:
if a name has already been mapped, revisiting it must reach the same
partner every time (and vice versa) -- exactly the DFA-isomorphism check
partition refinement's minimal form is built to make trivial: after
``normalize()``, any structural match between two records has to be a
consistent renaming, not a coincidence, since minimize has already merged
every pair of records that could otherwise masquerade as "the same
record under a different name."

Both inputs are assumed already normalized (pruned + minimized) by the
caller -- this module does not call ``normalize`` itself, matching the
paper's Algorithm 3, which runs isomorphism testing as a step *after*
MinimizeSA, not as a self-contained schema comparison.
"""

from __future__ import annotations

from typing import Dict

from ..schema import Ref, Schema
from .prune import is_empty
from .signature import local_signature


def _isomorphic(a: Schema, b: Schema) -> bool:
    """True iff normalized schemas ``a`` and ``b`` are isomorphic: there is
    a bijection between their env record names under which the two root
    records (and everything reachable from them) match exactly.

    **Empty-schema convention.** If both ``a`` and ``b`` are unsatisfiable
    (``is_empty()`` True for both), they're treated as isomorphic --
    both accept the empty language, and Theorem 4's equivalence claim
    (``equivalent(a, b) == _isomorphic(normalize(a), normalize(b))``) only
    holds if this case says True, since two unsatisfiable schemas are
    always ``equivalent`` (vacuously, both directions of
    ``compatible_with`` hold) regardless of how different their
    (necessarily still-unpruned-at-the-root -- see ``prune()``'s
    docstring) record shapes look. If exactly one is empty, they are
    *not* isomorphic: one accepts no documents, the other accepts at
    least one, so they can't be equivalent and must not be reported as
    isomorphic either.
    """
    empty_a, empty_b = is_empty(a), is_empty(b)
    if empty_a or empty_b:
        return empty_a and empty_b

    map_ab: Dict[str, str] = {}
    map_ba: Dict[str, str] = {}
    return _walk(a, a.root.name, b, b.root.name, map_ab, map_ba)


def _walk(a: Schema, na: str, b: Schema, nb: str,
          map_ab: Dict[str, str], map_ba: Dict[str, str]) -> bool:
    if na in map_ab or nb in map_ba:
        # Already visited on at least one side: the bijection must agree
        # both ways, or the schemas aren't isomorphic.
        return map_ab.get(na) == nb and map_ba.get(nb) == na

    map_ab[na] = nb
    map_ba[nb] = na

    ra, rb = a.env[na], b.env[nb]
    if local_signature(ra) != local_signature(rb):
        return False

    # local_signature sorts fields by label and includes the label in its
    # key, so two records with equal signatures declare exactly the same
    # set of labels -- fields on the two sides line up one-to-one by label.
    fields_b = {f.label: f for f in rb.fields}
    for fa in ra.fields:
        fb = fields_b[fa.label]
        if isinstance(fa.type, Ref) and isinstance(fb.type, Ref):
            # signature equality guarantees fb.type is a Ref too (the
            # shape key distinguishes scalar vs ref) -- the isinstance check
            # on fb.type here is for mypy's narrowing, not runtime logic.
            if not _walk(a, fa.type.name, b, fb.type.name, map_ab, map_ba):
                return False
    return True
