"""Bounded, deterministic CI version of the brute-force semantic oracle
(``tools/semantic_oracle.py``, issue #158).

Runs the exact same five checks against the exact same set-theoretic
ground-truth definition (``L(s) = {d in U : s.validate(Doc(d)).ok}``) as
the full tool, just over a much smaller universe and schema family so it
fits comfortably inside the normal test suite -- see the module-level
timing note below for the measured runtime. This is a *third* independent
correctness check on the schema algebra, alongside ``compatible_with``
(Algorithm 4, ``omnist/ops/subschema.py``) and the minimize+isomorphism
Theorem-4 oracle (``omnist/ops/isomorphic.py``, cross-checked in
``tests/test_fuzz.py``) -- see ``docs/testing.md``, "the triple-checked
algebra".

No pytest marker infrastructure is used: at well under a second, this
belongs in the normal test run, not a slow/opt-in lane.
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

# tools/ is repo-root-relative, not an installed package; bare `pytest -q`
# (as CI runs it) does not put the repo root on sys.path the way
# `python -m pytest` does, so add it explicitly before the import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.semantic_oracle as semantic_oracle  # noqa: E402
from omnist.schema import Field, Record, Ref, Schema, t  # noqa: E402
from tools.semantic_oracle import (  # noqa: E402
    OracleResult,
    _seeded_random_family,
    build_universe,
    check_compatible_with,
    check_extract,
    check_is_empty,
    check_normalize_prune_preserve_language,
    ground_truth,
    main,
    run,
    schema_family,
    to_doc,
)

# A deliberately small but still representative universe/family:
# base_max=1 keeps the base universe (root edges over {a,b}, 0-1 per label,
# leaf-or-depth-1 children) at 121 documents; extended_max=(2, 3) adds
# cardinality-2/3 witnesses on top for 337 total -- proportionally the same
# construction as the full tool's (base_max=2, extended_max=(3, 4)), just
# one cardinality notch down at every level. random_count=15 (plus the
# fixed 42 systematic + 3 structural + 14 nullable schemas = 74 total)
# keeps the O(n^2) compatible_with sweep (74^2 = 5,476 pairs) and the
# ground-truth computation (74 * 121 = 8,954 validations) small. The 14
# nullable-vs-non-nullable schemas (schema_family()'s nullable_family())
# are always included regardless of random_count -- they're what the
# mutation self-check in the PR body exercises (dropping the nullable
# check in ops/subschema.py's _scalar_sub), so this bounded test must
# always include them too, not just the full-size tool.
_BASE_MAX = 1
_EXTENDED_MAX = (2, 3)
_RANDOM_COUNT = 15
_SEED = 158


def _run_bounded() -> OracleResult:
    base_nodes, ext_nodes = build_universe(base_max=_BASE_MAX, extended_max=_EXTENDED_MAX)
    base_docs = [to_doc(n) for n in base_nodes]
    ext_docs = [to_doc(n) for n in ext_nodes]
    schemas = schema_family(random_count=_RANDOM_COUNT, seed=_SEED)

    truth = ground_truth(schemas, base_docs)
    ext_truth = ground_truth(schemas, ext_docs)
    doc_labels = [
        frozenset(lbl for lbl, _ in d.edges()) if not d.is_leaf else frozenset()
        for d in base_docs
    ]

    result = OracleResult()
    check_compatible_with(schemas, truth, ext_docs, ext_truth, result)
    check_is_empty(schemas, truth, result)
    check_normalize_prune_preserve_language(schemas, truth, base_docs, result)
    check_extract(schemas, base_docs, truth, doc_labels, result)
    result.counts["base_docs"] = len(base_docs)
    result.counts["extended_docs"] = len(ext_docs)
    result.counts["schemas"] = len(schemas)
    return result


def test_semantic_oracle_bounded_run_finds_zero_definite_bugs():
    """The schema algebra, checked against brute-force enumerated ground
    truth over a small but structurally representative universe: zero
    definite bugs is the only acceptable outcome -- a failure here means
    ``compatible_with``, ``is_empty``, ``normalize``, ``prune``, or
    ``extract`` disagrees with ``validate()`` itself, the strongest kind of
    regression this suite can catch (see ``tools/semantic_oracle.py``'s
    module docstring for why this check is independent of the other two
    algebra oracles)."""
    result = _run_bounded()
    assert result.definite_bugs == [], (
        f"semantic oracle found {len(result.definite_bugs)} definite bug(s): "
        + "; ".join(result.definite_bugs[:5])
    )
    # Sanity on the check actually having run over a non-trivial universe --
    # a regression that made the universe/family accidentally empty would
    # otherwise "pass" this test vacuously.
    assert result.counts["base_docs"] > 50
    assert result.counts["schemas"] >= 60
    assert result.counts["pairs_checked"] == result.counts["schemas"] ** 2
    assert result.counts["is_empty_checked"] == result.counts["schemas"]
    assert result.counts["extract_cases_checked"] > 0


def test_semantic_oracle_bounded_needs_review_is_small():
    """``compatible_with`` False answers that neither the base universe,
    the extended universe, nor any targeted witness can vindicate are
    reported as needs-manual-review, not failures (a bounded-universe
    artifact -- see ``tools/semantic_oracle.py``'s ``check_compatible_with``
    docstring). At this bounded size that set should be empty or very
    small; a large jump would signal the witness heuristics regressed, so
    this is a soft ceiling, not a strict zero requirement."""
    result = _run_bounded()
    assert len(result.needs_review) <= 5


# ---------------------------------------------------------------------------
# to_doc: top-level leaf branch
# ---------------------------------------------------------------------------

def test_to_doc_leaf_at_top_level():
    """``to_doc`` is documented to build a ``Doc`` from a (possibly nested)
    tuple-edge-list ``Node``, converting nested edge-list tuples to lists so
    ``Doc`` reads them as internal nodes rather than scalar leaves. But a
    bare scalar handed to ``to_doc`` directly -- not wrapped in any edge-list
    tuple -- doesn't match the edge-list shape test at all, and must fall
    through to the plain ``Doc(node)`` construction, i.e. a genuine leaf
    Doc. This is exercised by ``targeted_witnesses``' per-field values
    internally, but never with a bare top-level scalar until now."""
    for leaf in (1, "x", None):
        d = to_doc(leaf)
        assert d.is_leaf
        assert d.value == leaf


# ---------------------------------------------------------------------------
# _seeded_random_family: duplicate-label skip branch
# ---------------------------------------------------------------------------

def test_seeded_random_family_skips_duplicate_labels():
    """The per-record field-building loops in ``_seeded_random_family`` draw
    a label at random for each of ``n_fields`` slots and skip (``continue``)
    any repeat so no record ends up with two fields of the same label.
    Seed 1 with a single generated schema is a concrete, deterministic case
    where record B's second field slot redraws a label already used by its
    first field (verified against the underlying PRNG sequence): B ends up
    with exactly one field even though ``n_fields_b`` requested two,
    proving the ``lbl in used_b: continue`` branch actually fired rather
    than merely being reachable in principle."""
    schemas = _seeded_random_family(seed=1, count=1)
    assert len(schemas) == 1
    b_fields = schemas[0].env["B"].fields
    labels = [f.label for f in b_fields]
    # No duplicate labels -- the whole point of the skip-on-repeat branch.
    assert len(labels) == len(set(labels))
    # And the dedup actually did something observable: fewer fields ended
    # up in B than the two slots requested, because one slot's draw was a
    # repeat and got skipped.
    assert len(b_fields) == 1


# ---------------------------------------------------------------------------
# check_compatible_with: the two branches only a real algebra bug (or, here,
# a deliberately fabricated stand-in for one) can reach.
#
# Both tests below use two *language-equivalent* schemas (same field, same
# scalar, same cardinality) so that the real, unmodified `targeted_witnesses`
# search can never find a witness distinguishing them -- any such witness
# would itself be proof of a genuine `validate` inconsistency, which isn't
# what's under test here. `compatible_with` itself is patched only for the
# duration of the test, to force the answer the branch under test needs;
# nothing about the oracle's logic changes, and the patch never touches
# omnist package code.
# ---------------------------------------------------------------------------

def _equivalent_schema_pair():
    a = Schema(Ref("R"), {"R": Record([Field("a", t.integer, 1, 1)])})
    b = Schema(Ref("R"), {"R": Record([Field("a", t.integer, 1, 1)])})
    return a, b


def test_check_compatible_with_reports_definite_bug_on_true_not_subset():
    """If ``compatible_with(a, b)`` ever answered True while ``L(a)`` is
    demonstrably not a subset of ``L(b)`` over the base universe, that is an
    unconditional algebra bug (a True answer is an unconditional claim) --
    this is the oracle's primary bug-detection branch, and it must actually
    fire and record the bug when the premise holds. Real ``compatible_with``
    never returns True here (these two schemas are genuinely compatible,
    so a False test setup would be vacuous); ``compatible_with`` is patched
    to force the True answer while ``truth`` is deliberately fabricated so
    schema 0 accepts a base-universe document schema 1 rejects, isolating
    the branch instead of trying to provoke a real algebra bug."""
    a, b = _equivalent_schema_pair()
    _, ext_nodes = build_universe(base_max=1, extended_max=(2,))
    ext_docs = [to_doc(n) for n in ext_nodes]
    fake_truth = [frozenset({0}), frozenset()]  # a accepts doc 0, b accepts nothing
    fake_ext_truth = [frozenset(), frozenset()]
    result = OracleResult()
    with patch.object(semantic_oracle, "compatible_with", return_value=True):
        check_compatible_with([a, b], fake_truth, ext_docs, fake_ext_truth, result)
    assert len(result.definite_bugs) == 1
    assert "says True but" in result.definite_bugs[0]
    assert "doc index [0]" in result.definite_bugs[0]


def test_check_compatible_with_reports_needs_review_when_unvindicated():
    """A False ``compatible_with`` answer that the base universe, extended
    universe, and every targeted witness all fail to vindicate is reported
    as needs-manual-review, not a failure (see the module docstring: this
    is a bounded-universe artifact, not proof of a bug). Using two
    language-equivalent schemas guarantees no witness can ever exist (their
    languages are identical), so with ``compatible_with`` patched to answer
    False and real, correct ``truth``/``ext_truth`` (both genuinely show
    ``la`` subset ``lb``, since the schemas are equivalent), the check must
    fall through every vindication attempt and land in needs-review."""
    a, b = _equivalent_schema_pair()
    base_nodes, ext_nodes = build_universe(base_max=1, extended_max=(2,))
    base_docs = [to_doc(n) for n in base_nodes]
    ext_docs = [to_doc(n) for n in ext_nodes]
    schemas = [a, b]
    truth = ground_truth(schemas, base_docs)
    ext_truth = ground_truth(schemas, ext_docs)
    result = OracleResult()
    with patch.object(semantic_oracle, "compatible_with", return_value=False):
        check_compatible_with(schemas, truth, ext_docs, ext_truth, result)
    assert result.counts["needs_review_pairs"] == 4  # all 2x2 ordered pairs
    assert len(result.needs_review) == 4
    assert all("needs manual review" in msg for msg in result.needs_review)
    assert result.definite_bugs == []


# ---------------------------------------------------------------------------
# check_is_empty / check_normalize_prune_preserve_language / check_extract:
# same fabricated-truth technique as above, isolating each definite-bug
# branch without needing a real algebra bug to exist.
# ---------------------------------------------------------------------------

def test_check_is_empty_reports_definite_bug_on_true_nonempty_language():
    """``is_empty(s)`` True must mean ``L(s)`` is empty over the base
    universe -- feeding a genuinely-unsatisfiable schema (a mandatory
    self-cycle, real ``is_empty`` answer True) alongside a fabricated
    ``truth`` entry that lies about the language being non-empty isolates
    the bug-detection branch itself."""
    cyclic = Schema(Ref("R"), {"R": Record([Field("self", Ref("R"), 1, 1)])})
    fake_truth = [frozenset({0, 1})]
    result = OracleResult()
    check_is_empty([cyclic], fake_truth, result)
    assert len(result.definite_bugs) == 1
    assert "L(s) is non-empty" in result.definite_bugs[0]
    assert result.counts["is_empty_checked"] == 1


def test_check_normalize_prune_reports_definite_bug_on_language_change():
    """``L(normalize(s))`` and ``L(prune(s))`` must equal ``L(s)`` exactly.
    A fabricated ``truth`` (claiming the schema's language is empty, when
    real ``normalize``/``prune`` output actually validates some base-
    universe documents) isolates the mismatch-detection branch for both
    operations without needing either operation to actually be buggy."""
    s = Schema(Ref("R"), {"R": Record([Field("a", t.integer, 1, 1)])})
    base_nodes, _ = build_universe(base_max=1, extended_max=(2,))
    base_docs = [to_doc(n) for n in base_nodes]
    fake_truth = [frozenset()]  # lie: claim s accepts nothing
    result = OracleResult()
    check_normalize_prune_preserve_language([s], fake_truth, base_docs, result)
    # Both normalize and prune are checked per schema, and both should
    # disagree with the (fabricated) empty-language claim identically.
    assert len(result.definite_bugs) == 2
    assert all("changes the language" in msg for msg in result.definite_bugs)
    assert any(msg.startswith("normalize(") for msg in result.definite_bugs)
    assert any(msg.startswith("prune(") for msg in result.definite_bugs)
    assert result.counts["normalize_prune_checked"] == 1


def test_check_extract_reports_definite_bug_on_mismatch():
    """``L(extract(s, keep))`` must equal ``{d in L(s) : labels(d) subset
    keep}`` exactly. A fabricated ``truth`` (claiming ``s`` accepts nothing,
    when it really accepts some base-universe documents) makes the expected
    vs. actual comparison disagree, isolating ``check_extract``'s mismatch-
    reporting branch."""
    s = Schema(Ref("R"), {"R": Record([Field("a", t.integer, 1, 1)])})
    base_nodes, _ = build_universe(base_max=1, extended_max=(2,))
    base_docs = [to_doc(n) for n in base_nodes]
    doc_labels = [
        frozenset(lbl for lbl, _ in d.edges()) if not d.is_leaf else frozenset()
        for d in base_docs
    ]
    fake_truth = [frozenset()]  # lie: claim s accepts nothing
    result = OracleResult()
    check_extract([s], base_docs, fake_truth, doc_labels, result)
    assert len(result.definite_bugs) > 0
    assert all("disagrees with ground truth" in msg for msg in result.definite_bugs)
    assert result.counts["extract_cases_checked"] > 0


# ---------------------------------------------------------------------------
# run() / main(): the driver functions. `build_universe` is patched to a
# much smaller universe so the full `run()` pipeline (all five checks, over
# the full-size `schema_family()`) completes in well under a second instead
# of the ~110s the tool's default sizing takes (see the module docstring) --
# this exercises every line of `run()` and `main()` for real, just over a
# smaller universe than the standalone CLI invocation uses.
# ---------------------------------------------------------------------------

def _small_build_universe(base_max=2, extended_max=(3, 4)):
    # Ignores the (full-size) args `run()` passes and substitutes a small,
    # fast universe -- calls the real, unpatched `build_universe` (captured
    # before patching) so this has zero effect on the function under test's
    # own logic, only on how large a universe it's asked to build.
    return build_universe(base_max=1, extended_max=(2,))


def test_run_verbose_prints_summary_and_returns_zero_bugs():
    """``run(verbose=True)`` should print the progress/summary lines and
    return an ``OracleResult`` with populated counts and zero definite bugs
    when run over a (patched-small, for test speed) but otherwise-real
    universe and the full schema family -- exercising the driver's timing
    prints, summary section, and needs-review/bug-count reporting lines."""
    with patch.object(semantic_oracle, "build_universe", side_effect=_small_build_universe):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run(random_count=3, verbose=True)
    out = buf.getvalue()
    assert "universe:" in out
    assert "schema family:" in out
    assert "ground truth computed" in out
    assert "checks run" in out
    assert "=== Summary ===" in out
    assert "DEFINITE BUGS: 0" in out
    assert result.definite_bugs == []
    # run()'s default random_count=3 (test override) plus the fixed 42
    # systematic + 3 structural + 14 nullable schemas = 62; pairs_checked
    # is the full n^2 sweep over that family.
    assert result.counts["pairs_checked"] == 62 ** 2
    assert result.counts["is_empty_checked"] == 62


def test_run_verbose_prints_each_definite_bug_when_found():
    """When ``result.definite_bugs`` is non-empty, ``run(verbose=True)``
    must print a ``BUG:`` line for each one (up to 20) -- the summary's bug-
    listing loop, otherwise never exercised by a genuinely bug-free run (see
    the zero-bugs test above). ``check_extract`` -- one of the four checks
    ``run`` calls in sequence -- is patched to additionally append one
    fabricated bug to ``result``, isolating this print loop without
    depending on (or claiming to find) a real algebra bug."""
    real_check_extract = semantic_oracle.check_extract

    def _check_extract_with_fabricated_bug(*args, **kwargs):
        result = args[-1]
        real_check_extract(*args, **kwargs)
        result.definite_bugs.append("fabricated bug for print-loop coverage")

    with patch.object(semantic_oracle, "build_universe", side_effect=_small_build_universe), \
            patch.object(semantic_oracle, "check_extract",
                          side_effect=_check_extract_with_fabricated_bug):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run(random_count=3, verbose=True)
    out = buf.getvalue()
    assert "DEFINITE BUGS: 1" in out
    assert "  BUG: fabricated bug for print-loop coverage" in out
    assert result.definite_bugs == ["fabricated bug for print-loop coverage"]


def test_run_quiet_suppresses_output():
    """``run(verbose=False)`` must not print anything -- the CI-bounded test
    (``_run_bounded`` above) relies on this to keep pytest output clean, and
    it exercises the ``if verbose:`` guards' False branch at every one of
    the four print sites in ``run``."""
    with patch.object(semantic_oracle, "build_universe", side_effect=_small_build_universe):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run(random_count=3, verbose=False)
    assert buf.getvalue() == ""
    assert result.counts["is_empty_checked"] > 0


def test_main_returns_zero_and_prints_passed_when_no_bugs():
    """``main()`` returns 0 and prints a PASSED line when ``run()`` finds no
    definite bugs. ``run`` is patched directly (rather than re-running the
    full pipeline) since this test's only concern is ``main()``'s own
    branching on ``result.definite_bugs``, already covered independently by
    the ``run()`` tests above."""
    with patch.object(semantic_oracle, "run", return_value=OracleResult()):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main()
    assert code == 0
    assert "PASSED: zero definite bugs." in buf.getvalue()


def test_main_returns_one_and_prints_failed_when_bugs_found():
    """``main()`` returns 1 and prints a FAILED line (with the bug count)
    when ``run()``'s result has any definite bugs -- the oracle's actual
    pass/fail contract for CLI/CI use. A fabricated ``OracleResult`` with
    one bug isolates this branch without needing a real algebra bug."""
    bad_result = OracleResult()
    bad_result.definite_bugs.append("fabricated bug for branch coverage")
    with patch.object(semantic_oracle, "run", return_value=bad_result):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main()
    assert code == 1
    assert "FAILED: 1 definite bug(s) found." in buf.getvalue()
