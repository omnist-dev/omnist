"""Property-based fuzzing of the Document model, codecs, and the OSD parser.

Two angles (see issue #64 and the prior fuzzing effort noted in
CHANGELOG.md, "test: add property-based fuzzing with hypothesis; fix 3 bugs
it found" -- this file follows that one's structure and conventions, updated
for the current canonical edge-list Document model):

1. **Round-trip fuzzing** -- randomized canonical Document nodes (the
   ``[(label, child), ...]`` edge-list / scalar-leaf shape from
   :mod:`omnist.document`) round-tripped through every codec:

   * ``write_oml``/``read_oml`` must be *exactly* lossless for every shape
     (``docs/formats/oml.md``).
   * ``write_json``/``write_yaml``/``write_toml``/``write_xml`` and their
     readers must round-trip *modulo documented adjustments* -- we use
     ``check_*``/``WriteReport`` to know exactly which adjustments are
     allowed (date/time stringified, ``null`` dropped by TOML, ambiguous
     strings re-typed by XML, ...) rather than guessing, so an *undocumented*
     mismatch fails the test.
   * ``doc(...)``/``build_node`` from the equivalent plain Python value
     round-trips to the same node (a second, simpler "plain value" generator
     is used here, since a Python dict can't express same-level repeated/
     interleaved labels the way a canonical node can).

2. **Crash-freedom fuzzing** -- arbitrary (not necessarily valid) text fed
   into ``read_oml`` and ``parse_schema`` must raise only ``ParseError``/
   ``SchemaError`` (or a subclass) -- any other exception escaping is a
   hardening bug (the digit-count and nesting-depth limits in
   ``docs/formats/oml.md`` exist precisely to prevent this).

Found bugs (real round-trip mismatches or unhandled-exception crashes) are
not fixed here -- see the project's standing bug workflow (open a separate
issue, fix in its own PR). A flaw in this file's own lossiness assumptions
is fixed here instead.
"""

from __future__ import annotations

import datetime as _dt
import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from omnist import (
    DocumentError,
    ParseError,
    SchemaError,
    check_json,
    check_oml,
    check_toml,
    check_xml,
    check_yaml,
    doc,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    write_json,
    write_oml,
    write_toml,
    write_xml,
    write_yaml,
)
from omnist.document import _grouped, build_node

_SUPPRESS = settings(
    deadline=None,  # CI runners are slower/noisier than a dev machine
    suppress_health_check=[HealthCheck.too_slow],
    max_examples=150,
)

_MAX_DEPTH = 5  # bounded nesting -- a correctness net, not an exhaustive search

# ---------------------------------------------------------------------------
# Scalars -- all seven kinds + null, with edge-case values
# ---------------------------------------------------------------------------

# Strings: empty, unicode, control-adjacent-but-valid (omnist's OML scanner
# rejects raw control chars in source but the *value* -- after escaping -- can
# be any string, since write_oml always escapes).
_strings = st.text(max_size=20)

# Integers: include values near the digit-count guard's neighborhood without
# actually tripping it (that's exercised by the crash-freedom text fuzzing
# below, not by values that must round-trip).
#
# NOTE (issue #156, B2): 2**64 is ~20 digits, nowhere near the 4300-digit
# construction cap that document.py now enforces in build_node/Doc.add/
# Doc.set -- this strategy cannot generate a huge int, so it never exercises
# that guard (or its DocumentError) on its own. That's intentional here: this
# generator's job is round-trip values, not boundary/error values, and a
# 4300+-digit int would also make every generated document far more
# expensive to shrink/print for very little added coverage. The boundary
# itself (4300 digits OK, 4301 raises) is covered directly by targeted tests
# in tests/test_canonical.py (TestDocumentRobustness) and tests/test_oml.py,
# not by widening this strategy.
_integers = st.one_of(
    st.integers(min_value=-(2 ** 64), max_value=2 ** 64),
    st.just(0),
    st.just(-0),
)

# Floats: very large/small magnitudes, signed zero, nan/inf (handled specially
# in equality below since NaN isn't self-equal).
_floats = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True),
    st.just(0.0),
    st.just(-0.0),
    st.floats(min_value=1e300, max_value=1.7e308),
    st.floats(min_value=-1.7e308, max_value=-1e300),
    st.floats(min_value=1e-300, max_value=1e-10),
)

_dates = st.dates(min_value=_dt.date(1, 1, 1), max_value=_dt.date(9999, 12, 31))
_times = st.one_of(
    st.times(),
    st.just(_dt.time(0, 0, 0)),
    st.just(_dt.time(23, 59, 59, 999999)),
)
_datetimes = st.one_of(
    st.datetimes(min_value=_dt.datetime(1, 1, 1), max_value=_dt.datetime(9999, 12, 31)),
    st.just(_dt.datetime(1, 1, 1, 0, 0, 0)),
    st.just(_dt.datetime(9999, 12, 31, 23, 59, 59, 999999)),
    st.just(_dt.datetime(2000, 2, 29, 0, 0, 0)),    # leap day
    st.just(_dt.datetime(2024, 2, 29, 12, 0, 0)),   # leap year, not div-by-400
)

scalars = st.one_of(
    st.none(),
    st.booleans(),
    _integers,
    _floats,
    _strings,
    _dates,
    _times,
    _datetimes,
)

# "inf"/"nan"/"-inf" excluded: write_oml emits them as bare identifiers but
# the OML scanner tokenizes them as NUMBER, not IDENT, so read_oml can't
# parse them back as a label at all -- a real, separately-filed bug (#71),
# not a flaw in this generator's assumptions.
_labels = st.text(min_size=1, max_size=10).filter(lambda s: s not in ("inf", "nan", "-inf"))


def _nodes(depth: int):
    """A canonical Document node: a scalar leaf, or an ordered edge list with
    possibly-repeated, possibly-interleaved labels."""
    if depth >= _MAX_DEPTH:
        return scalars
    return st.one_of(
        scalars,
        st.lists(
            st.tuples(_labels, st.deferred(lambda: _nodes(depth + 1))),
            max_size=5,
        ),
    )


nodes = st.deferred(lambda: _nodes(0))


# ---------------------------------------------------------------------------
# Equality that treats NaN as self-equal (OML/JSON both round-trip NaN as a
# float value, but NaN != NaN, so plain == would wrongly fail a correct
# round-trip).
# ---------------------------------------------------------------------------

def nan_safe_equal(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        # an edge list `[(label, child), ...]` or a plain list of children
        return all(
            (nan_safe_equal(x, y) if not (isinstance(x, tuple) and isinstance(y, tuple))
             else x[0] == y[0] and nan_safe_equal(x[1], y[1]))
            for x, y in zip(a, b)
        )
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(nan_safe_equal(a[k], b[k]) for k in a)
    return a == b


def nan_safe_equal_grouped(a, b) -> bool:
    """Equality modulo the documented, intentional cross-label-interleaving
    loss of the JSON-shaped grouping (`docs/design/model.md` Sec.10,
    Doc.to_grouped): same-label edges are grouped into one list, so
    [(m,A),(x,X),(m,B)] and [(m,A),(m,B),(x,X)] are equivalent once grouped.
    JSON/YAML/TOML all go through this projection; only XML preserves
    interleaving natively."""
    return nan_safe_equal(_grouped(a), _grouped(b))


# ---------------------------------------------------------------------------
# 1. OML round-trip -- exact equality, no adjustments possible
# ---------------------------------------------------------------------------

@_SUPPRESS
@given(node=nodes)
def test_oml_round_trip_is_exact(node):
    assert check_oml(node).adjustments == []
    text = write_oml(node)
    back = read_oml(text)
    assert nan_safe_equal(back, node), f"OML round-trip mismatch: {node!r} -> {back!r}"


# ---------------------------------------------------------------------------
# 2. Lossy-format round-trip -- exact modulo documented adjustments
# ---------------------------------------------------------------------------

_ALLOWED_CODES = {
    "json": {"temporal.stringified", "float.special"},
    "yaml": {"temporal.stringified"},
    "toml": {"null.omitted"},
    "xml": {"null.omitted", "temporal.stringified", "string.ambiguous",
            "key.sanitized", "shape.empty_ambiguous"},
}


@_SUPPRESS
@given(node=nodes)
def test_json_round_trip_modulo_documented_adjustments(node):
    rep = check_json(node)
    assert {a.code for a in rep} <= _ALLOWED_CODES["json"], rep
    text = write_json(node)
    back = read_json(text)
    # temporal values come back as strings (date/time -> str) -- a documented
    # adjustment, safe to compare through the grouped projection (which also
    # accepts the temporal stringification since str != date is expected for
    # those leaves only). float.special (NaN/Infinity) is *not* identity
    # either, as of #157/S1: lenient write_json now substitutes `null` at
    # those leaves (rather than emitting the non-standard `NaN`/`Infinity`
    # tokens Python's own json.loads used to read back as the same float), so
    # a document containing one no longer round-trips to an equal value --
    # skip the comparison for it too, same as temporal.stringified.
    codes = {a.code for a in rep}
    if not (codes & {"temporal.stringified", "float.special"}):
        assert nan_safe_equal_grouped(back, node), \
            f"JSON round-trip mismatch: {node!r} -> {back!r}"


def _has_nel(node) -> bool:
    """True if `node` contains U+0085 (NEL) in any label or string value --
    see #69 (a real bug filed separately, not fixed in this test): PyYAML
    mangles U+0085 to a plain space on this round trip, undetected by
    check_yaml. Excluded here so this test exercises the *documented*
    adjustments only, until #69 lands."""
    if isinstance(node, list):
        return any("\x85" in label or _has_nel(child) for label, child in node)
    return isinstance(node, str) and "\x85" in node


@_SUPPRESS
@given(node=nodes)
def test_yaml_round_trip_modulo_documented_adjustments(node):
    if _has_nel(node):
        return  # see #69
    rep = check_yaml(node)
    assert {a.code for a in rep} <= _ALLOWED_CODES["yaml"], rep
    text = write_yaml(node)
    back = read_yaml(text)
    if not rep.adjustments:
        assert nan_safe_equal_grouped(back, node), \
            f"YAML round-trip mismatch: {node!r} -> {back!r}"


@_SUPPRESS
@given(node=nodes)
def test_toml_round_trip_modulo_documented_adjustments(node):
    rep = check_toml(node)
    assert {a.code for a in rep} <= _ALLOWED_CODES["toml"], rep
    if not isinstance(node, list):
        return  # TOML requires a top-level table; non-object roots are out of scope
    try:
        text = write_toml(node)
    except Exception:
        if rep.adjustments:
            return  # a documented adjustment can still leave an unwritable shape
        raise
    back = read_toml(text)
    if not rep.adjustments:
        assert nan_safe_equal_grouped(back, node), \
            f"TOML round-trip mismatch: {node!r} -> {back!r}"


def _xml_safe_node(node):
    """True if `node` avoids two known, undocumented-by-check_xml XML
    round-trip gaps (both filed separately, not fixed in this test):

    * #67 -- a string leaf containing a C0 control character other than
      tab/LF crashes write_xml's own output on read_xml (XML 1.0 forbids
      them outright), and CR is silently normalized to LF by the XML
      parser (lossy).
    * #68 -- an internal node with zero edges (`[]`) is indistinguishable
      on the wire from an empty-string leaf (`''`); read_xml always
      reconstructs the leaf form.

    Excluded here so this test exercises the *documented* adjustments
    only, until #67/#68 land."""
    if isinstance(node, list):
        if node == []:
            return False  # #68
        return all(_xml_safe_node(child) for _label, child in node)
    if isinstance(node, str):
        return not any((ord(ch) < 0x20 and ch not in "\t\n") for ch in node)
    return True


@_SUPPRESS
@given(label=_labels, node=nodes)
def test_xml_round_trip_modulo_documented_adjustments(label, node):
    if not _xml_safe_node(node):
        return  # see #67
    # XML needs exactly one top-level document element -- wrap every
    # generated node under a single synthetic root label.
    rooted = [(label, node)]
    rep = check_xml(rooted)
    assert {a.code for a in rep} <= _ALLOWED_CODES["xml"], rep
    text = write_xml(rooted)
    back = read_xml(text)
    if not rep.adjustments:
        assert nan_safe_equal(back, rooted), f"XML round-trip mismatch: {rooted!r} -> {back!r}"


# ---------------------------------------------------------------------------
# 3. doc(...)/build_node round-trip from the equivalent plain Python value
# ---------------------------------------------------------------------------

def _plain_values(depth: int):
    """A plain JSON-shaped Python value: dict/list/scalar, no repeated keys at
    the same level (that's exactly what build_node/doc accept)."""
    if depth >= _MAX_DEPTH:
        return scalars
    children = st.deferred(lambda: _plain_values(depth + 1))
    return st.one_of(
        scalars,
        st.dictionaries(_labels, children, max_size=5),
        st.dictionaries(
            _labels,
            st.lists(st.deferred(lambda: _plain_values(depth + 1)), max_size=4),
            max_size=3,
        ),
    )


plain_values = st.deferred(lambda: _plain_values(0))


@_SUPPRESS
@given(value=plain_values)
def test_doc_and_build_node_round_trip_from_plain_python_value(value):
    try:
        expected = build_node(value)
    except DocumentError:
        return  # a legal rejection (e.g. a bare list nested in a list)
    assert nan_safe_equal(doc(value).to_data(), expected)
    # and the resulting node round-trips through OML exactly, same as any node
    back = read_oml(write_oml(expected))
    assert nan_safe_equal(back, expected)


# ---------------------------------------------------------------------------
# 4. Crash-freedom: arbitrary text into read_oml / parse_schema
# ---------------------------------------------------------------------------

@_SUPPRESS
@given(text=st.text(max_size=200))
def test_read_oml_never_raises_unexpectedly(text):
    try:
        read_oml(text)
    except ParseError:
        pass  # malformed input is expected to be rejected this way
    except Exception as exc:  # pragma: no cover -- a crash-freedom bug, not expected
        raise AssertionError(
            f"read_oml raised {type(exc).__name__} instead of ParseError "
            f"on input {text!r}"
        ) from exc


@_SUPPRESS
@given(text=st.text(max_size=200))
def test_parse_schema_never_raises_unexpectedly(text):
    try:
        parse_schema(text)
    except SchemaError:
        pass  # malformed input is expected to be rejected this way
    except Exception as exc:  # pragma: no cover -- a crash-freedom bug, not expected
        raise AssertionError(
            f"parse_schema raised {type(exc).__name__} instead of SchemaError "
            f"on input {text!r}"
        ) from exc


# Also fuzz text drawn from a alphabet biased toward OML/OSD syntax
# characters, which is far more likely to reach deep parser states than pure
# random unicode text.
_SYNTAX_ALPHABET = st.sampled_from(
    list(' \t\n\r;:{}[]",\'#-+.0123456789eEtTzZabcdefghijklmnopqrstuvwxyz_?nullruefalseinfa')
)
_syntax_like_text = st.text(alphabet=_SYNTAX_ALPHABET, max_size=200)


@_SUPPRESS
@given(text=_syntax_like_text)
def test_read_oml_never_raises_unexpectedly_on_syntax_like_text(text):
    try:
        read_oml(text)
    except ParseError:
        pass
    except Exception as exc:  # pragma: no cover
        raise AssertionError(
            f"read_oml raised {type(exc).__name__} instead of ParseError "
            f"on input {text!r}"
        ) from exc


@_SUPPRESS
@given(text=_syntax_like_text)
def test_parse_schema_never_raises_unexpectedly_on_syntax_like_text(text):
    try:
        parse_schema(text)
    except SchemaError:
        pass
    except Exception as exc:  # pragma: no cover
        raise AssertionError(
            f"parse_schema raised {type(exc).__name__} instead of SchemaError "
            f"on input {text!r}"
        ) from exc


# ---------------------------------------------------------------------------
# 5. Schema fuzzing (issue #139) -- generated env of records, deliberately
# including mandatory ([1,1] / [1,]) ref fields so the strategy CAN produce
# a mandatory-only ref cycle (an unsatisfiable, empty-language schema).
# Before #139 no schema-generation strategy existed in this file at all, so
# the empty-schema bug (compatible_with/equivalent wrong for such schemas)
# went unfound by property testing -- this section closes that gap with the
# property the paper's Theorem 1 analog guarantees: an unsatisfiable schema
# is vacuously compatible_with everything.
# ---------------------------------------------------------------------------

from omnist import INTEGER, STRING, Field, Record, Ref, Schema  # noqa: E402
from omnist.schema import ANY as _ANY  # noqa: E402

_RECORD_NAMES = ("A", "B", "C")

# [1,1] and [1,None] are mandatory; [0,1] and [0,None] are optional. Both
# kinds must appear with real probability -- an all-optional generator could
# never produce a mandatory ref cycle, which is exactly the shape #139's bug
# lived in.
_cardinalities = st.sampled_from([(1, 1), (0, 1), (1, None), (0, None)])

# Spec any-type-spec.md Sec.5.2: a generated field's type is `any` with
# probability ~0.15, instead of a scalar/ref. `st.one_of` doesn't expose
# per-branch weighting directly, so this draws a float in [0, 1) first and
# dispatches -- the cleanest way to pin an exact probability rather than an
# approximate one from repeating elements in a `sampled_from` pool.
_ANY_FIELD_PROBABILITY = 0.15
_non_any_field_types = st.one_of(st.just(STRING), st.just(INTEGER),
                                  st.sampled_from([Ref(n) for n in _RECORD_NAMES]))


@st.composite
def _field_types(draw):
    if draw(st.floats(min_value=0.0, max_value=1.0, exclude_max=True)) < _ANY_FIELD_PROBABILITY:
        return _ANY
    return draw(_non_any_field_types)


@st.composite
def _fields(draw):
    n = draw(st.integers(min_value=0, max_value=2))
    fields = []
    for i in range(n):
        ftype = draw(_field_types())
        lo, hi = draw(_cardinalities)
        fields.append(Field(f"f{i}", ftype, lo, hi))
    return fields


@st.composite
def schemas(draw):
    """A Schema over a small, fixed-name env (``A``/``B``/``C``) -- small
    enough that Hypothesis reliably explores both satisfiable and
    unsatisfiable (mandatory ref cycle) shapes within a bounded number of
    examples, since every record can reference every other record
    (including itself)."""
    env = {name: Record(draw(_fields())) for name in _RECORD_NAMES}
    root_name = draw(st.sampled_from(_RECORD_NAMES))
    return Schema(Ref(root_name), env)


@_SUPPRESS
@given(s=schemas(), t=schemas())
def test_is_empty_implies_compatible_with_anything(s, t):
    """The vacuity property (paper Theorem 1 analog): an unsatisfiable
    schema's language is empty, so it's trivially a subschema of any other
    schema, no matter what ``t`` looks like."""
    if s.is_empty():
        assert s.compatible_with(t)


# ---------------------------------------------------------------------------
# 5b. extract() (issue #142, paper Algorithm 5) -- for random schemas over
# the same small fixed-name env as `schemas()` above, and random label
# subsets drawn from the labels that generator can actually produce
# (`f0`/`f1` -- see `_fields()`), whenever extraction succeeds it must
# produce a subschema: every document the extract accepts, the original
# schema accepts too.
# ---------------------------------------------------------------------------

_extract_labels = st.frozensets(st.sampled_from(["f0", "f1"]))


@_SUPPRESS
@given(s=schemas(), keep=_extract_labels)
def test_extract_result_is_compatible_with_original(s, keep):
    try:
        extracted = s.extract(*keep)
    except SchemaError:
        return  # "no valid subschema" for this keep set -- not this property's concern
    assert extracted.compatible_with(s)


# ---------------------------------------------------------------------------
# 6. Equivalence oracle (issue #141) -- the paper's Theorem 4: two schemas
# are equivalent iff their minimized (normalized) forms are isomorphic. That
# gives two structurally independent decision procedures for schema
# equality -- bidirectional ``compatible_with`` (``ops/subschema.py``,
# Algorithm 4) vs minimize-then-isomorphism-test (``ops/minimize.py``
# Algorithm 2 + ``ops/isomorphic.py`` Algorithm 3 step 3) -- and this
# section asserts they never disagree. See ``docs/testing.md``, "the
# dual-algorithm oracle", for why this is the strongest correctness check
# in the suite: it isn't testing behavior against examples, it's testing
# one implementation against an independently-derived second one.
# ---------------------------------------------------------------------------

from omnist.ops.isomorphic import _isomorphic  # noqa: E402
from omnist.ops.signature import local_signature  # noqa: E402


@_SUPPRESS
@given(s=schemas(), t=schemas())
def test_equivalent_agrees_with_normalize_and_isomorphic(s, t):
    """Theorem 4, directly: ``equivalent`` (bidirectional subschema
    inclusion) and ``_isomorphic(normalize(s), normalize(t))`` (an
    unrelated algorithm) must always agree, for arbitrary random pairs --
    including the common case where they're simply not equivalent at all."""
    assert s.equivalent(t) == _isomorphic(s.normalize(), t.normalize())


@_SUPPRESS
@given(s=schemas())
def test_normalize_is_equivalent_to_original(s):
    """``normalize`` must never change a schema's language."""
    assert s.normalize().equivalent(s)


@_SUPPRESS
@given(s=schemas())
def test_normalize_is_idempotent(s):
    """Normalizing an already-normalized schema changes nothing further --
    the fixpoint of partition refinement is reached in one call."""
    once = s.normalize()
    twice = once.normalize()
    assert set(once.env) == set(twice.env)
    assert once.root.name == twice.root.name
    for name, rec in once.env.items():
        other = twice.env[name]
        assert local_signature(rec) == local_signature(other)


# -- biased-toward-equivalent pair generation --------------------------------
#
# Two independently-random schemas are almost always inequivalent (the state
# space is far too large for `s == t` structurally, let alone semantically),
# so the oracle property above would rarely exercise the "True" branch of
# either algorithm without help. These strategies build a *second* schema
# that's deliberately equivalent to the first by construction, so both
# procedures are also exercised on the interesting (and harder to get
# right) case.

_RENAME_POOL = ("A", "B", "C", "X", "Y", "Z")


@st.composite
def _renamed(draw, s: Schema) -> Schema:
    """A copy of ``s`` with every env record given a fresh name (a pure
    rename never changes a schema's language)."""
    names = list(s.env)
    pool = [n for n in _RENAME_POOL]
    draw(st.permutations(pool))  # just to consume some entropy for variety
    new_names = draw(st.permutations(pool[: len(names)])) if names else []
    rename = dict(zip(names, new_names))
    new_env = {
        rename[n]: Record([
            Field(f.label,
                  Ref(rename[f.type.name]) if isinstance(f.type, Ref) else f.type,
                  f.min, f.max)
            for f in rec.fields
        ])
        for n, rec in s.env.items()
    }
    return Schema(Ref(rename[s.root.name]), new_env)


@st.composite
def _reordered(draw, s: Schema) -> Schema:
    """A copy of ``s`` with each record's fields declared in a shuffled
    order -- validation ignores field order, so this never changes the
    schema's language (see ``ops/signature.py``'s docstring)."""
    new_env = {}
    for name, rec in s.env.items():
        order = draw(st.permutations(list(range(len(rec.fields))))) if rec.fields else []
        new_env[name] = Record([rec.fields[i] for i in order])
    return Schema(Ref(s.root.name), new_env)


@st.composite
def _with_unreachable_record(draw, s: Schema) -> Schema:
    """A copy of ``s`` plus one extra env record no field ever points to --
    unreachable records are dropped by ``prune()`` and so never affect the
    language."""
    extra_name = next(n for n in ("U1", "U2", "U3") if n not in s.env)
    extra = Record(draw(_fields()))
    new_env = dict(s.env)
    new_env[extra_name] = extra
    return Schema(Ref(s.root.name), new_env)


@st.composite
def _with_max_zero_field(draw, s: Schema) -> Schema:
    """A copy of ``s`` with one extra never-emittable (``max == 0``) field
    added to some record -- such a field is dropped by ``prune()`` and so
    never affects the language."""
    if not s.env:
        return s
    name = draw(st.sampled_from(sorted(s.env)))
    rec = s.env[name]
    extra_label = next(
        lbl for lbl in ("z0", "z1", "z2") if rec.field(lbl) is None
    )
    ftype = draw(_field_types())
    extra = Field(extra_label, ftype, 0, 0)
    new_env = dict(s.env)
    new_env[name] = Record(list(rec.fields) + [extra])
    return Schema(s.root, new_env)


_equivalent_transform = st.sampled_from(
    ["rename", "reorder", "unreachable", "max_zero"]
)


@st.composite
def _equivalent_pair(draw):
    """``(s, t)`` where ``t`` is built from ``s`` by a language-preserving
    transform -- both decision procedures must say True for every one of
    these, which is the harder direction of Theorem 4 to get right (it's
    easy to accidentally break either algorithm in a way that only shows up
    on cases designed to actually be equivalent)."""
    s = draw(schemas())
    kind = draw(_equivalent_transform)
    if kind == "rename":
        t = draw(_renamed(s))
    elif kind == "reorder":
        t = draw(_reordered(s))
    elif kind == "unreachable":
        t = draw(_with_unreachable_record(s))
    else:
        t = draw(_with_max_zero_field(s))
    return s, t


@_SUPPRESS
@given(pair=_equivalent_pair())
def test_equivalent_pairs_agree_as_isomorphic(pair):
    """Pairs built to be equivalent by construction: both the
    ``equivalent`` oracle and ``_isomorphic`` must say True, and they must
    still agree with each other (Theorem 4 on the case that actually
    exercises the "True" branch)."""
    s, t = pair
    assert s.equivalent(t)
    assert _isomorphic(s.normalize(), t.normalize())


def test_isomorphic_false_on_mismatch_found_only_by_recursing_into_a_ref():
    """A regression/coverage case the property generators above are
    unlikely to hit reliably: two schemas whose *root* records have equal
    ``local_signature`` (so the top-level check alone can't distinguish
    them), but whose ref-typed field targets diverge once the traversal
    recurses into them. ``_isomorphic`` must walk into refs, not just
    compare the root pair, to catch this."""
    a = parse_schema('record R { "x": B }\nrecord B { "y": integer }\nroot R')
    b = parse_schema('record R2 { "x": B2 }\nrecord B2 { "y": string }\nroot R2')
    assert not _isomorphic(a.normalize(), b.normalize())
    assert not a.equivalent(b)
