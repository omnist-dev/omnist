"""Tests for the canonical (redesigned) Document and Schema models.

Covers the design in docs/design/model.md: edge-list Document, record/Ref
schema with exactly seven scalars, field cardinality, conformance, OSD,
operations, and codecs.
"""
import datetime

import pytest

from omnist import (
    Doc,
    Field,
    Format,
    Record,
    Ref,
    Scalar,
    Schema,
    ValidationResult,
    WriteReport,
    check_json,
    check_toml,
    check_xml,
    check_yaml,
    doc,
    field,
    formats,
    get_format,
    infer,
    materialize,
    nullable,
    parse_schema,
    read_json,
    read_toml,
    read_xml,
    read_yaml,
    record,
    ref,
    register_format,
    schema,
    t,
    to_osd,
    write_json,
    write_toml,
    write_xml,
    write_yaml,
)
from omnist.errors import DocumentError, ParseError, SchemaError, WriteError
from omnist.oml import check_oml, write_oml
from omnist.ops import compatible_with, equivalent, is_empty, normalize, prune
from omnist.schema import matches_kind, value_kind

yaml = pytest.importorskip("yaml")


# ----------------------------------------------------------- public API
class TestPublicApi:
    """The `import omnist` surface: schema operations as methods, the `t`
    builder namespace, validation, codecs."""

    def test_methods_and_t_namespace(self):
        import omnist as ds

        s = ds.parse_schema('record R { "n": integer, "s": string? }\nroot R')
        assert ds.__version__ == "0.8.5"
        # operations are Schema methods
        assert s.validate(ds.doc({"n": 1, "s": None})).ok
        assert s.equivalent(ds.parse_schema(ds.to_osd(s)))
        wide = ds.parse_schema('record R { "n": number, "s": string? }\nroot R')
        assert s.compatible_with(wide)
        assert s.normalize().equivalent(s)
        # the t namespace, used directly as a field's type -- no wrapping
        b = ds.schema(ds.ref("R"), R=ds.record(ds.field("v", ds.nullable(ds.t.integer))))
        assert b.validate(ds.doc({"v": 7})).ok
        assert b.validate(ds.doc({"v": None})).ok
        assert not b.validate(ds.doc({"v": "other"})).ok

    def test_old_names_are_gone(self):
        import omnist as ds
        for name in ("obj", "arr", "ObjectType", "ArrayType", "ScalarType", "mapping",
                     "Union", "union"):
            assert not hasattr(ds, name), f"{name} should be removed (clean break)"


# ----------------------------------------------------------- Document
class TestDocument:
    def test_build_and_navigate(self):
        d = doc({"name": "Ann", "age": 30})
        assert not d.is_leaf
        assert d.labels() == ["name", "age"]
        assert d.get_one("name").value == "Ann"
        assert d.get_one("age").value == 30

    def test_repeated_label_is_an_array(self):
        d = doc({"member": [{"n": 1}, {"n": 2}]})
        assert d.count("member") == 2
        members = d.get("member")
        assert members[0].get_one("n").value == 1
        assert members[1].get_one("n").value == 2

    def test_to_data_is_edge_list(self):
        d = doc({"a": 1, "xs": [1, 2]})
        assert d.to_data() == [("a", 1), ("xs", 1), ("xs", 2)]

    def test_to_grouped_projects_back(self):
        d = doc({"a": 1, "xs": [1, 2]})
        assert d.to_grouped() == {"a": 1, "xs": [1, 2]}

    def test_bare_array_rejected(self):
        with pytest.raises(DocumentError):
            doc([1, 2, 3])

    def test_array_of_arrays_rejected(self):
        with pytest.raises(DocumentError):
            doc({"m": [[1, 2], [3, 4]]})

    def test_non_string_key_rejected(self):
        with pytest.raises(DocumentError):
            doc({1: "a"})

    def test_editing(self):
        d = doc({"name": "Ann"})
        d.add("tag", "x").add("tag", "y")            # repeated label = array
        assert d.count("tag") == 2
        d.set("name", "Bob")
        assert d.get_one("name").value == "Bob"
        d.set("age", 30)                             # set() on an absent label adds it
        assert d.get_one("age").value == 30
        d.remove("tag")
        assert d.count("tag") == 0
        # nested editing through a cursor shares the underlying structure
        d2 = doc({"addr": {"city": "X"}})
        d2.child("addr").set("city", "Y")
        assert d2.to_grouped() == {"addr": {"city": "Y"}}

    # -- set() replace-all semantics (issue #156, B4) --------------------
    def test_set_on_absent_label_appends(self):
        d = doc({"a": 1})
        d.set("b", 2)
        assert d.to_data() == [("a", 1), ("b", 2)]

    def test_set_on_single_label_unchanged_behavior(self):
        d = doc({"a": 1, "b": 2})
        d.set("a", 99)
        assert d.to_data() == [("a", 99), ("b", 2)]
        assert d.count("a") == 1
        assert d.get_one("a").value == 99

    def test_set_on_repeated_label_collapses_to_one_at_first_position(self):
        d = doc({"a": 1})
        d.add("a", 2)
        d.add("b", 9)
        d.set("a", 99)
        assert d.to_data() == [("a", 99), ("b", 9)]
        assert d.count("a") == 1
        assert d.get_one("a").value == 99

    def test_set_preserves_first_occurrence_position_among_other_labels(self):
        # 'a' first occurs before 'b'; after set(), the single surviving
        # 'a' edge must still sit at that same (first-occurrence) slot.
        d = doc({"a": 1, "b": 2})
        d.add("a", 3)
        d.set("a", 99)
        assert d.to_data() == [("a", 99), ("b", 2)]

    def test_set_after_remove_appends(self):
        d = doc({"a": 1})
        d.add("a", 2)
        d.remove("a")
        assert d.count("a") == 0
        d.set("a", 7)
        assert d.to_data() == [("a", 7)]

    def test_set_replace_all_matches_remove_then_add_docstring_contract(self):
        # "set = remove + add" -- construct the same document both ways.
        d1 = doc({"a": 1})
        d1.add("a", 2).add("b", 9)
        d1.set("a", 99)

        d2 = doc({"a": 1})
        d2.add("a", 2).add("b", 9)
        d2.remove("a").add("a", 99)
        # remove+add appends at the END (after 'b'), unlike set(), which
        # keeps the FIRST occurrence's position -- documenting the one
        # difference between set() and a literal remove()+add().
        assert d1.to_data() == [("a", 99), ("b", 9)]
        assert d2.to_data() == [("b", 9), ("a", 99)]


class TestInfer:
    def test_flat(self):
        from omnist import infer
        s = infer([doc({"name": "Ann", "age": 30}), doc({"name": "Bob"})])
        assert s.validate(doc({"name": "Cy"})).ok           # age optional
        assert not s.validate(doc({"age": 1})).ok           # name required

    def test_array_and_nested(self):
        from omnist import infer
        s = infer([doc({"id": 1, "tags": ["a", "b"], "addr": {"city": "X"}})])
        assert s.validate(doc({"id": 9, "tags": ["c"], "addr": {"city": "Y"}})).ok
        assert not s.validate(doc({"id": 9, "tags": [1], "addr": {"city": "Y"}})).ok

    def test_repeated_label_min_is_zero_not_the_observed_minimum(self):
        # Issue #265 (spec §6.10): a label seen more than once in ANY sample
        # becomes [0,], min=0 -- never inferred from the smallest count
        # seen across samples. Two samples with differing nonzero counts
        # (3 then 1) must not produce min=1.
        from omnist import infer
        s = infer([doc({"tags": ["a", "b", "c"]}), doc({"tags": ["x"]})])
        rec = s.env[s.root.name]
        f = rec.field("tags")
        assert f.min == 0
        assert f.max is None

    def test_accepts_its_own_samples(self):
        from omnist import infer
        samples = [doc({"v": 1}), doc({"v": 2.5})]          # int + float -> number
        s = infer(samples)
        for sm in samples:
            assert s.validate(sm).ok

    def test_conflicting_scalars_raise(self):
        from omnist import infer
        with pytest.raises(SchemaError):
            infer([doc({"v": 1}), doc({"v": "x"})])

    def test_null_only_field_infers_nullable_string(self):
        from omnist import infer
        s = infer([doc({"v": None}), doc({"v": None})])
        assert s.validate(doc({"v": None})).ok
        assert s.validate(doc({"v": "anything"})).ok

    def test_null_alongside_a_kind_is_orthogonal(self):
        from omnist import infer
        s = infer([doc({"v": 1}), doc({"v": None})])
        assert s.validate(doc({"v": 7})).ok
        assert s.validate(doc({"v": None})).ok
        assert not s.validate(doc({"v": "x"})).ok

    def test_optional_field_detection_is_order_independent(self):
        # a field absent from an early sample but present in a later one
        # must still infer as optional, regardless of which sample order
        # it's passed in
        from omnist import infer
        absent_first = infer([doc({"host": "a"}), doc({"host": "b", "port": 80})])
        absent_last = infer([doc({"host": "b", "port": 80}), doc({"host": "a"})])
        assert absent_first.equivalent(absent_last)

        port = absent_first.env["Root"].fields[1]
        assert port.label == "port"
        assert (port.min, port.max) == (0, 1)

        assert absent_first.validate(doc({"host": "x"})).ok
        assert absent_first.validate(doc({"host": "x", "port": 1})).ok


# ----------------------------------------------------------- OSD + validation
def valid(text, data):
    return parse_schema(text).validate(doc(data))


class TestValidation:
    def test_scalar_kinds(self):
        s = 'record R { "n": integer, "s": string }\nroot R'
        assert valid(s, {"n": 1, "s": "x"}).ok
        assert not valid(s, {"n": "x", "s": "x"}).ok

    def test_required_and_optional(self):
        s = 'record R { "name": string, "age" [0,1]: integer }\nroot R'
        assert valid(s, {"name": "a"}).ok
        assert valid(s, {"name": "a", "age": 3}).ok
        assert not valid(s, {"age": 3}).ok               # name required

    def test_closed_rejects_unexpected(self):
        s = 'record R { "a": integer }\nroot R'
        r = valid(s, {"a": 1, "b": 2})
        assert not r.ok
        assert any("unexpected field" in m for _, m, _ in r.errors)

    def test_array_cardinality(self):
        s = 'record R { "xs" [0,]: integer }\nroot R'
        assert valid(s, {"xs": [1, 2, 3]}).ok
        assert valid(s, {}).ok                            # 0 occurrences ok
        s2 = 'record R { "xs" [1,]: integer }\nroot R'
        assert not valid(s2, {}).ok                       # needs at least one
        assert valid(s2, {"xs": [1]}).ok
        s3 = 'record R { "xs" [2]: integer }\nroot R'
        assert valid(s3, {"xs": [1, 2]}).ok
        assert not valid(s3, {"xs": [1]}).ok

    def test_nullable(self):
        s2 = 'record R { "note": string? }\nroot R'
        assert valid(s2, {"note": None}).ok
        assert valid(s2, {"note": "hi"}).ok
        assert not valid(s2, {"note": 1}).ok

    def test_integer_satisfies_number(self):
        s = 'record R { "v": number }\nroot R'
        assert valid(s, {"v": 7}).ok
        assert valid(s, {"v": 7.5}).ok
        assert not valid(s, {"v": "x"}).ok

    def test_ref_and_recursion(self):
        s = ('record Node { "value": integer, "kids" [0,]: Node }\nroot Node')
        assert valid(s, {"value": 1, "kids": [{"value": 2, "kids": []}]}).ok
        assert not valid(s, {"value": 1, "kids": [{"value": "x", "kids": []}]}).ok

    def test_question_mark_on_ref_is_error(self):
        with pytest.raises(SchemaError):
            parse_schema('record A { "x": integer }\nrecord R { "a": A? }\nroot R')

    def test_enum_syntax_is_rejected(self):
        # the '|' character itself isn't in the grammar at all anymore, so
        # this is rejected by the tokenizer, before the parser ever gets to
        # look at what's in type position
        with pytest.raises(SchemaError, match="unexpected character '\\|'"):
            parse_schema('record R { "status": "open" | "closed" }\nroot R')

    def test_literal_valued_field_is_rejected(self):
        # a single literal (no '|') reaches the parser and is rejected by
        # _type() itself, with a more specific message than a bad character
        with pytest.raises(SchemaError, match="enums and literal-valued fields"):
            parse_schema('record R { "status": "open" }\nroot R')
        with pytest.raises(SchemaError, match="enums and literal-valued fields"):
            parse_schema('record R { "n": 5 }\nroot R')

    def test_union_keyword_is_rejected(self):
        with pytest.raises(SchemaError):
            parse_schema('union License { "auto", "manual" }\nrecord R { "a": integer }\nroot R')


# ----------------------------------------------------- OSD parser robustness
class TestOsdRobustness:
    """Regressions for three real defects found by probing the parser
    against its own grammar: a crash, a broken depth guard, and a silent
    name-shadowing footgun."""

    def test_float_cardinality_raises_cleanly(self):
        # used to crash with an uncaught ValueError instead of SchemaError
        with pytest.raises(SchemaError):
            parse_schema('record R { "a" [1.5,3]: integer }\nroot R')

    def test_many_flat_definitions_are_not_rejected(self):
        # the old "depth guard" counted total '{' across the whole file, so
        # 150 unrelated, non-nested records were falsely rejected even
        # though nothing here recurses at all
        flat = "".join(f'record R{i} {{ "a": integer }}\n' for i in range(150))
        s = parse_schema(flat + "root R0")
        assert s.root.name == "R0"

    def test_record_named_a_scalar_keyword_is_rejected(self):
        # used to silently succeed, but the record could never be
        # referenced -- "string" in a type position always meant the
        # builtin scalar, never a Ref to this record
        with pytest.raises(SchemaError):
            parse_schema('record string { "x": integer }\nrecord R { "a": string }\nroot R')

    def test_record_named_a_non_scalar_word_is_fine(self):
        s = parse_schema('record Address { "city": string }\nrecord R { "a": Address }\nroot R')
        assert s.validate(doc({"a": {"city": "X"}})).ok


# --------------------------------------------- date/time/datetime boundary
class TestTemporalBoundary:
    """date / time / datetime are mutually exclusive, including for the
    string form (dates/times arrive as ISO-8601 text from JSON/XML).
    datetime.fromisoformat is lenient -- a bare date-only string parses fine,
    defaulting the missing time to midnight -- so a bare date string must
    NOT satisfy datetime, only date."""

    DATE = 'record R { "v": date }\nroot R'
    TIME = 'record R { "v": time }\nroot R'
    DATETIME = 'record R { "v": datetime }\nroot R'

    def test_bare_date_string_satisfies_only_date(self):
        v = "2024-01-01"
        assert valid(self.DATE, {"v": v}).ok
        assert not valid(self.DATETIME, {"v": v}).ok
        assert not valid(self.TIME, {"v": v}).ok

    def test_bare_time_string_satisfies_only_time(self):
        v = "12:00:00"
        assert valid(self.TIME, {"v": v}).ok
        assert not valid(self.DATE, {"v": v}).ok
        assert not valid(self.DATETIME, {"v": v}).ok

    def test_full_timestamp_string_satisfies_only_datetime(self):
        for v in ("2024-01-01T12:00:00", "2024-01-01T00:00:00"):
            assert valid(self.DATETIME, {"v": v}).ok, v
            assert not valid(self.DATE, {"v": v}).ok, v
            assert not valid(self.TIME, {"v": v}).ok, v

    def test_unparseable_string_satisfies_none(self):
        v = "not-a-date"
        assert not valid(self.DATE, {"v": v}).ok
        assert not valid(self.TIME, {"v": v}).ok
        assert not valid(self.DATETIME, {"v": v}).ok

    def test_real_objects_unaffected(self):
        import datetime as dt
        assert valid(self.DATETIME, {"v": dt.datetime(2024, 1, 1, 12, 0)}).ok
        assert not valid(self.DATETIME, {"v": dt.date(2024, 1, 1)}).ok
        assert valid(self.DATE, {"v": dt.date(2024, 1, 1)}).ok
        assert not valid(self.DATE, {"v": dt.datetime(2024, 1, 1, 12, 0)}).ok


# ----------------------------------------------------------- OSD round-trip
OSD_CASES = [
    'record R { "n": integer }\nroot R',
    'record R { "n": integer, "s": string? }\nroot R',
    'record R { "status": string }\nroot R',
    'record R { "v": number }\nroot R',
    'record R { "xs" [0,]: integer }\nroot R',
    'record R { "xs" [1,5]: string }\nroot R',
    'record R { "xs" [2]: integer }\nroot R',
    'record R { "first name": string }\nroot R',
    'record M { "name": string }\nrecord R { "m" [0,]: M }\nroot R',
    'record Node { "v": integer, "kids" [0,]: Node }\nroot Node',
]


@pytest.mark.parametrize("text", OSD_CASES)
def test_osd_round_trip(text):
    s = parse_schema(text)
    s2 = parse_schema(to_osd(s))
    assert equivalent(s, s2), f"\n{text}\n->\n{to_osd(s)}"


# ------------------------------------------------ OSD compact (indent=None)
@pytest.mark.parametrize("text", OSD_CASES)
def test_osd_compact_round_trip(text):
    s = parse_schema(text)
    s2 = parse_schema(to_osd(s, indent=None))
    assert equivalent(s, s2), f"\n{text}\n->\n{to_osd(s, indent=None)}"


def test_osd_compact_exact_string():
    s = parse_schema(
        'record Member { "name": string, "role": string }\n'
        'record Team { "name": string, "members" [1,]: Member, '
        '"lead" [0,1]: string }\nroot Team')
    assert to_osd(s, indent=None) == (
        'record Member { "name": string, "role": string } '
        'record Team { "name": string, "members" [1,]: Member, '
        '"lead" [0,1]: string } root Team\n')


# ----------------------------------------------------------- operations
class TestOperations:
    def test_added_optional_field_is_compatible(self):
        v1 = parse_schema('record R { "a": integer }\nroot R')
        v2 = parse_schema('record R { "a": integer, "b" [0,1]: integer }\nroot R')
        assert compatible_with(v1, v2)
        assert not compatible_with(v2, v1)

    def test_required_to_optional_is_compatible(self):
        strict = parse_schema('record R { "a": integer, "b": integer }\nroot R')
        loose = parse_schema('record R { "a": integer, "b" [0,1]: integer }\nroot R')
        assert compatible_with(strict, loose)
        assert not compatible_with(loose, strict)

    def test_integer_is_compatible_with_number(self):
        narrow = parse_schema('record R { "v": integer }\nroot R')
        wide = parse_schema('record R { "v": number }\nroot R')
        assert compatible_with(narrow, wide)
        assert not compatible_with(wide, narrow)

    def test_nullable_is_one_directional(self):
        narrow = parse_schema('record R { "v": string }\nroot R')
        wide = parse_schema('record R { "v": string? }\nroot R')
        assert compatible_with(narrow, wide)
        assert not compatible_with(wide, narrow)

    def test_array_bounds(self):
        a = parse_schema('record R { "xs" [2,3]: integer }\nroot R')
        b = parse_schema('record R { "xs" [1,5]: integer }\nroot R')
        assert compatible_with(a, b)
        assert not compatible_with(b, a)

    def test_temporal_date_not_compatible_with_string(self):
        from omnist import DATE, STRING
        a = schema(ref("R"), R=record(field("d", DATE)))
        b = schema(ref("R"), R=record(field("d", STRING)))
        assert not compatible_with(a, b)

    def test_equivalent_reordered(self):
        a = parse_schema('record R { "a": integer, "b": string }\nroot R')
        b = parse_schema('record R { "b": string, "a": integer }\nroot R')
        assert equivalent(a, b)

    def test_normalize_merges_identical(self):
        s = parse_schema('record A { "x": integer }\nrecord B { "x": integer }\n'
                         'record R { "a": A, "b": B }\nroot R')
        n = normalize(s)
        assert len(n.env) < len(s.env)
        assert equivalent(s, n)


class TestExtract:
    """Subschema extraction (issue #142, paper Algorithm 5, ExtractSubschema)."""

    def test_paper_worked_example_quote_order(self):
        # Paper Listings 1-2 / Figs 6-7 translated to OSD: a shared Root
        # that can hold either a Quote (mandatory Line items with desc/
        # price) or an Order (mandatory OrderLine items with a nested
        # mandatory Product plus qty). Extracting the Quote-side labels
        # drops "order" (not kept, optional -> just removed) which makes
        # Order/OrderLine/Product unreachable, so prune() removes them.
        quote_order = parse_schema('''
            record Root { "quote" [0,1]: Quote, "order" [0,1]: Order }
            record Quote { "line" [1,]: Line }
            record Order { "line" [1,]: OrderLine }
            record Line { "desc": string, "price": number }
            record OrderLine { "product" [1,]: Product, "qty": integer }
            record Product { "desc": string, "price": number }
            root Root
        ''')
        ex = quote_order.extract("quote", "line", "desc", "price")
        assert sorted(ex.env) == ["Line", "Quote", "Root"]
        assert ex.compatible_with(quote_order)

    def test_mandatory_deletion_raises_with_label_and_record(self):
        s = parse_schema('record R { "must": integer, "opt" [0,1]: string }\nroot R')
        with pytest.raises(SchemaError) as exc:
            s.extract("opt")
        assert "must" in str(exc.value)
        assert "R" in str(exc.value)

    def test_full_label_extract_equals_normalize(self):
        s = parse_schema(
            'record A { "x": integer }\nrecord B { "x": integer }\n'
            'record Root { "a": A, "b": B }\nroot Root')
        assert len(s.extract("a", "b", "x").env) == len(s.normalize().env)

    def test_extract_free_function_matches_method(self):
        from omnist.ops import extract
        s = parse_schema('record R { "a": integer, "b" [0,1]: string }\nroot R')
        assert extract(s, ["a"]).equivalent(s.extract("a"))

    def test_optional_field_deletion_does_not_invalidate(self):
        s = parse_schema('record R { "must": integer, "opt" [0,1]: string }\nroot R')
        ex = s.extract("must")
        assert ex.env[ex.root.name].field("opt") is None
        assert ex.compatible_with(s)

    def test_propagation_invalidates_transitively(self):
        # C loses its mandatory "z" (not kept) -> C invalidated.
        # B's mandatory field "c" points at C -> B invalidated.
        # A's mandatory field "b" points at B -> A invalidated (root).
        s = parse_schema(
            'record A { "b": B }\nrecord B { "c": C }\nrecord C { "z": integer }\n'
            'root A')
        with pytest.raises(SchemaError) as exc:
            s.extract()
        # Issue #267 (spec §6.9): first_bad MUST be the first offender
        # encountered during step 1's single pass over S.env in declaration
        # order -- not whichever step-3 propagation discovers later. env is
        # a dict (guaranteed insertion order since 3.7), and extract's
        # step-1 loop iterates it in that same order every run, so this is
        # fully deterministic: "b"/"A" every time, not "one of three".
        assert str(exc.value) == (
            "no valid subschema: removing label 'b' deletes a mandatory "
            "field of record 'A'")

    def test_first_offender_is_declaration_order_not_alphabetical(self):
        # A second variant where the offending field sits deeper in
        # declaration order, to confirm the rule really is "first
        # encountered in S.env order" and not e.g. "first alphabetically"
        # (Z would sort after A/B/C but is declared, and offends, first).
        s = parse_schema(
            'record Z { "w": W }\nrecord W { "v": integer }\nroot Z')
        with pytest.raises(SchemaError) as exc:
            s.extract()
        assert str(exc.value) == (
            "no valid subschema: removing label 'w' deletes a mandatory "
            "field of record 'Z'")

    def test_deleted_ref_field_no_longer_in_result(self):
        s = parse_schema(
            'record R { "keep": integer, "drop" [0,1]: Other }\n'
            'record Other { "v": string }\nroot R')
        ex = s.extract("keep")
        assert ex.root.name == "R"
        assert ex.env["R"].field("drop") is None
        assert "Other" not in ex.env


class TestNormalizePartitionRefinement:
    """MinimizeSA (issue #140): normalize is now partition refinement, not
    a single syntactic merge pass -- it produces the canonical *minimum*
    equivalent schema (fewest env records, unique up to naming)."""

    def test_ref_chained_duplicates_merge_in_one_pass(self):
        # Previously: one pass merged C/D but left A/B (now structurally
        # identical) unmerged, requiring a second normalize() call.
        s = parse_schema(
            'record A { "x": C }\nrecord B { "x": D }\n'
            'record C { "y": integer }\nrecord D { "y": integer }\n'
            'record Root { "a": A, "b": B }\nroot Root')
        n = s.normalize()
        assert sorted(n.env) == ["A", "C", "Root"]
        assert n.equivalent(s)

    def test_recursive_twins_merge(self):
        # Mutually-recursive twins are equivalent() but syntactic keying
        # (the old normalize) never merged them, even iterated.
        s = parse_schema(
            'record Root { "p" [0,1]: P, "q" [0,1]: Q }\n'
            'record P { "next" [0,1]: P }\nrecord Q { "next" [0,1]: Q }\n'
            'root Root')
        n = s.normalize()
        assert len(n.env) == 2
        assert n.equivalent(s)

    def test_unreachable_record_dropped(self):
        s = parse_schema('record R { "x": integer }\n'
                         'record Orphan { "y": string }\nroot R')
        assert sorted(s.normalize().env) == ["R"]

    def test_no_over_merge_on_different_scalar_types(self):
        s = parse_schema('record A { "x": integer }\nrecord B { "x": string }\n'
                         'record Root { "a": A, "b": B }\nroot Root')
        assert len(s.normalize().env) == 3

    def test_idempotent(self):
        s = parse_schema(
            'record A { "x": C }\nrecord B { "x": D }\n'
            'record C { "y": integer }\nrecord D { "y": integer }\n'
            'record Root { "a": A, "b": B }\nroot Root')
        once = s.normalize()
        twice = once.normalize()
        assert twice.equivalent(once)
        assert sorted(twice.env) == sorted(once.env)

    def test_field_order_does_not_split_a_block(self):
        # Design decision: validation ignores field order (Record is a set
        # of labeled fields), so local_signature sorts fields by label --
        # two records with the same fields in a different order MUST merge.
        s = parse_schema(
            'record A { "x": integer, "y": string }\n'
            'record B { "y": string, "x": integer }\n'
            'record Root { "a": A, "b": B }\nroot Root')
        n = s.normalize()
        assert sorted(n.env) == ["A", "Root"]
        assert n.equivalent(s)

    def test_tie_break_is_alphabetical_minimum_not_declaration_order(self):
        # Issue #266 (spec §6.7 / divergence ledger §9.2): names MUST be
        # sorted before grouping and the representative MUST be the
        # alphabetical minimum of its block -- NOT the first-declared name.
        # "Zeta" is declared before "Alpha" so the two orders diverge.
        s = parse_schema(
            'record Zeta { "x": integer }\nrecord Alpha { "x": integer }\n'
            'record Root { "a": Zeta, "b": Alpha }\nroot Root')
        n = s.normalize()
        assert sorted(n.env) == ["Alpha", "Root"]
        rec = n.env["Root"]
        assert rec.field("a").type.name == "Alpha"
        assert rec.field("b").type.name == "Alpha"

    def test_empty_schema_returns_pruned_schema_unchanged(self):
        # prune() deliberately keeps an unsatisfiable root's fields intact;
        # partition refinement over that unsatisfiable core isn't
        # meaningful, so normalize just returns the pruned schema.
        s = parse_schema('record A { "x": B }\nrecord B { "y": A }\nroot A')
        assert s.is_empty()
        n = s.normalize()
        assert n.is_empty()
        assert sorted(n.env) == ["A", "B"]
        assert n.root.name == "A"

    def test_multi_round_refinement_needed(self):
        # Initial local_signature partition wrongly starts A/B and P/Q
        # together (same shape, ref targets excluded); P/Q split apart in
        # round one once R/S (differing scalar type) are distinguished,
        # and A/B only split apart in round two as a consequence -- this
        # exercises more than one refinement iteration before the fixpoint.
        s = parse_schema(
            'record Root { "a": A, "b": B }\n'
            'record A { "x": P }\nrecord B { "x": Q }\n'
            'record P { "v": integer, "w": R }\n'
            'record Q { "v": integer, "w": S }\n'
            'record R { "n": integer }\nrecord S { "n": string }\n'
            'root Root')
        n = s.normalize()
        assert sorted(n.env) == ["A", "B", "P", "Q", "R", "Root", "S"]
        assert n.equivalent(s)


# ------------------------------------------------- empty schemas / prune
class TestEmptySchemas:
    """Unsatisfiable (mandatory ref cycle) schemas accept no finite document
    -- the empty language. Verified failure cases from issue #139: such a
    schema must be vacuously compatible_with anything, and any two distinct
    empty schemas must be equivalent."""

    def _mandatory_cycle(self):
        return parse_schema('record A { "x": B }\nrecord B { "y": A }\nroot A')

    def test_empty_schema_is_vacuously_compatible_with_anything(self):
        empty = self._mandatory_cycle()
        other = parse_schema('record C { "z": integer }\nroot C')
        assert compatible_with(empty, other)
        assert not compatible_with(other, empty)

    def test_two_distinct_empty_schemas_are_equivalent(self):
        empty1 = self._mandatory_cycle()
        empty2 = parse_schema('record P { "q": P }\nroot P')
        assert equivalent(empty1, empty2)

    def test_isomorphic_to_tolerates_record_renaming(self):
        # Issue #279: same structure, different record names -- must be
        # isomorphic, unlike exact Schema.__eq__.
        a = parse_schema('record Root { "x": Foo }\nrecord Foo { "n": integer }\nroot Root')
        b = parse_schema('record Root { "x": Bar }\nrecord Bar { "n": integer }\nroot Root')
        assert a.isomorphic_to(b)
        assert a != b   # __eq__ (issue #273) is exact -- Foo != Bar by name

    def test_isomorphic_to_rejects_structural_difference(self):
        a = parse_schema('record Root { "x": Foo }\nrecord Foo { "n": integer }\nroot Root')
        c = parse_schema(
            'record Root { "x": Baz }\n'
            'record Baz { "n": integer, "extra": string }\nroot Root')
        assert not a.isomorphic_to(c)

    def test_isomorphic_to_catches_a_merge_bug_equivalent_misses(self):
        # Issue #279's exact motivating counterexample: infer must never
        # merge structurally-identical generated records (that's
        # normalize's job, not infer's). A buggy implementation that
        # accidentally merges two identical records still accepts the same
        # documents -- equivalent() reports "correct," a false negative.
        # isomorphic_to correctly rejects it: different record-set
        # cardinality, no bijection possible regardless of naming.
        correct = parse_schema(
            'record Root { "a": A, "b": B }\n'
            'record A { "x": string }\nrecord B { "x": string }\nroot Root')
        buggy_merge = parse_schema(
            'record Root { "a": AB, "b": AB }\n'
            'record AB { "x": string }\nroot Root')
        assert correct.equivalent(buggy_merge)          # the false negative
        assert not correct.isomorphic_to(buggy_merge)   # correctly caught

    def test_is_empty_true_for_mandatory_cycle(self):
        assert self._mandatory_cycle().is_empty()

    def test_is_empty_false_when_cycle_broken_by_optional(self):
        s = parse_schema('record A { "x" [0,1]: B }\nrecord B { "y": A }\nroot A')
        assert not s.is_empty()

    def test_is_empty_false_for_scalar_only_schema(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        assert not s.is_empty()

    def test_is_empty_free_function_matches_method(self):
        s = self._mandatory_cycle()
        assert is_empty(s) == s.is_empty()

    def test_optional_dead_field_does_not_block_compatibility(self):
        # R has an optional field of an unsatisfiable type -- it can never
        # actually be emitted, so R itself is satisfiable and compatible
        # with an R2 that simply doesn't declare that field.
        r = parse_schema('record R { "x" [0,1]: Dead }\nrecord Dead { "d": Dead }\n'
                         'root R')
        r2 = parse_schema('record R2 { }\nroot R2')
        assert not r.is_empty()
        assert compatible_with(r, r2)

    def test_prune_drops_unreachable_records(self):
        s = parse_schema('record A { "x": integer }\nrecord Unused { "y": integer }\n'
                         'root A')
        p = s.prune()
        assert "Unused" not in p.env
        assert "A" in p.env

    def test_prune_drops_max_zero_fields(self):
        s = parse_schema('record R { "dead" [0,0]: integer, "live": integer }\nroot R')
        p = s.prune()
        assert p.env["R"].field("dead") is None
        assert p.env["R"].field("live") is not None

    def test_prune_drops_optional_unsatisfiable_fields(self):
        s = parse_schema('record R { "x" [0,1]: Dead }\nrecord Dead { "d": Dead }\n'
                         'root R')
        p = s.prune()
        assert p.env["R"].field("x") is None
        assert "Dead" not in p.env

    def test_prune_is_equivalent(self):
        s = parse_schema('record R { "dead" [0,0]: integer, "live": integer }\n'
                         'record Unused { "z": integer }\nroot R')
        assert s.prune().equivalent(s)

    def test_prune_is_idempotent(self):
        s = parse_schema('record R { "dead" [0,0]: integer, "live": integer }\n'
                         'record Unused { "z": integer }\nroot R')
        once = s.prune()
        twice = once.prune()
        assert once.env.keys() == twice.env.keys()
        for name in once.env:
            assert len(once.env[name].fields) == len(twice.env[name].fields)

    def test_prune_env_order_matches_input_declaration_order(self):
        # Issue #253: new_env used to be built by iterating a `set` of
        # reachable names, so its key order depended on PYTHONHASHSEED and
        # varied across process runs. The surviving records must come out
        # in the *input* schema's declaration order instead -- a dict
        # (env) preserves insertion order deterministically regardless of
        # hash seed, unlike a set.
        s = parse_schema(
            'record A { "x": integer }\n'
            'record B { "y": integer }\n'
            'record C { "z": integer }\n'
            'record R { "a": A, "b": B, "c": C }\n'
            'root R'
        )
        assert list(s.env.keys()) == ["A", "B", "C", "R"]
        assert list(s.prune().env.keys()) == ["A", "B", "C", "R"]

        # Unreachable record dropped -- survivors still follow declaration
        # order, not the order the reachability walk happened to visit them.
        s2 = parse_schema(
            'record A { "x": integer }\n'
            'record Unused { "y": integer }\n'
            'record B { "z": integer }\n'
            'record R { "a": A, "b": B }\n'
            'root R'
        )
        assert list(s2.prune().env.keys()) == ["A", "B", "R"]

    def test_prune_free_function_matches_method(self):
        s = parse_schema('record R { "dead" [0,0]: integer }\nroot R')
        assert prune(s).equivalent(s.prune())

    def test_prune_on_unsatisfiable_root_keeps_it_intact(self):
        # The root's own mandatory cycle is what makes it unsatisfiable --
        # pruning it away would silently produce a different, satisfiable
        # schema. See ops/prune.py's docstring for the design rationale.
        s = self._mandatory_cycle()
        p = s.prune()
        assert p.is_empty()
        assert p.env["A"].field("x") is not None
        assert p.equivalent(s)


# ----------------------------------------------------------- codecs
class TestMalformedInput:
    def test_invalid_json_raises_parse_error(self):
        with pytest.raises(ParseError, match="invalid JSON"):
            read_json("{not json")

    def test_invalid_yaml_raises_parse_error(self):
        with pytest.raises(ParseError, match="invalid YAML"):
            read_yaml("a: [1, 2\n")

    def test_invalid_toml_raises_parse_error(self):
        with pytest.raises(ParseError, match="invalid TOML"):
            read_toml("not [ valid toml")

    def test_invalid_xml_raises_parse_error(self):
        with pytest.raises(ParseError, match="invalid XML"):
            read_xml("<unclosed>")

    def test_check_oml_never_sees_an_unwritable_node(self):
        # Before issue #156 (B2), build_node accepted ints past CPython's
        # str-conversion digit cap, so check_oml's "always an empty report"
        # guarantee and write_oml's "the write always succeeds exactly"
        # guarantee were both silently false for such a node -- the crash
        # only surfaced later, in write_oml/write_json/repr(). Now the cap
        # is enforced at construction, so any node build_node accepts is
        # guaranteed writable: check_oml is empty and write_oml succeeds.
        big_ok = int("9" * 4300)   # at the cap -- the largest build_node accepts
        node = doc({"a": big_ok, "b": [1, 2], "c": {"d": "x"}}).to_data()
        assert list(check_oml(node)) == []
        write_oml(node)   # must not raise


class TestCodecs:
    SCHEMA = ('record Member { "name": string, "role": string }\n'
              'record Team { "name": string, "members" [0,]: Member }\nroot Team')

    def test_json_round_trip(self):
        d = read_json('{"name":"P","members":[{"name":"Ann","role":"dev"},'
                      '{"name":"Bob","role":"pm"}]}')
        s = parse_schema(self.SCHEMA)
        assert s.validate(Doc(d)).ok
        # two members -> a list (count > 1), unambiguous
        assert read_json(write_json(d)) == d

    def test_count_one_serializes_bare_without_a_schema(self):
        # the documented count-1 ambiguity: a single-element array projects to
        # a bare value when no schema is available (schema-less fallback).
        d = read_json('{"members":[{"name":"Ann"}]}')
        assert write_json(d) == '{"members": {"name": "Ann"}}'

    def test_write_json_rejects_unsupported_scalar(self):
        # A node built by hand (bypassing build_node's type check) can carry
        # a leaf value that's neither a JSON-native type nor date/time/
        # datetime -- json.dumps' default= hook then raises TypeError.
        class Unsupported:
            pass
        with pytest.raises(TypeError, match="cannot serialize"):
            write_json([("a", Unsupported())])

    def test_all_formats_same_document(self):
        j = read_json('{"name":"P","members":[{"name":"Ann","role":"dev"},'
                      '{"name":"Bob","role":"pm"}]}')
        y = read_yaml("name: P\nmembers:\n  - name: Ann\n    role: dev\n"
                      "  - name: Bob\n    role: pm\n")
        t = read_toml('name = "P"\n[[members]]\nname = "Ann"\nrole = "dev"\n'
                      '[[members]]\nname = "Bob"\nrole = "pm"\n')
        assert j == y == t

    def test_xml_is_single_rooted(self):
        # XML wraps in one document element -> a single top-level edge.
        d = read_xml("<team><name>P</name><member>x</member><member>y</member></team>")
        assert d == [("team", [("name", "P"), ("member", "x"), ("member", "y")])]
        # round-trips
        assert read_xml(write_xml(d)) == d

    def test_xml_interleaving_preserved_in_document(self):
        # the edge list keeps order, including a label between two repeats
        d = read_xml("<t><m>a</m><x>1</x><m>b</m></t>")
        assert d == [("t", [("m", "a"), ("x", "1"), ("m", "b")])]

    def test_xml_write_needs_single_root(self):
        with pytest.raises(WriteError):
            write_xml([("a", 1), ("b", 2)])      # two top-level edges

    def test_xml_label_sanitized_when_not_a_valid_xml_name(self):
        # a label with spaces/punctuation isn't a valid XML name -- write_xml
        # sanitizes it (and prefixes "_" if sanitizing leaves nothing usable).
        out = write_xml([("a b", "1")])
        assert "<a_b>" in out

    def test_xml_label_starting_with_digit_gets_underscore_prefix(self):
        out = write_xml([("1tag", "x")])
        assert "<_1tag>" in out

    def test_xml_leaf_types_round_trip_as_text(self):
        # bool/None/date leaves all go through _xml_text's special-casing.
        d = [("r", [("flag", True), ("nothing", None),
                    ("d", datetime.date(2024, 1, 1))])]
        out = write_xml(d)
        assert "<flag>true</flag>" in out
        assert "<nothing />" in out or "<nothing/>" in out or "<nothing></nothing>" in out
        assert "<d>2024-01-01</d>" in out

    def test_xml_text_never_infers_scalar_kind_from_shape(self):
        # #288: XML has no native typed literals (unlike YAML's `true` token
        # or TOML's `29.97` literal), so unlike YAML/TOML it stays untyped
        # at stage 1, exactly like JSON/OML -- every leaf is the plain
        # string it looked like in the source, regardless of shape.
        d = read_xml("<r><a></a><b>true</b><c>false</c><n>1</n><f>3.5</f></r>")
        assert d == [("r", [("a", ""), ("b", "true"), ("c", "false"),
                            ("n", "1"), ("f", "3.5")])]

    def test_xml_mixed_content_text_before_children_raises(self):
        # #157/S2: elem.text alongside child elements used to be silently
        # discarded -- the only place data vanished on *read* with no
        # check_* even in principle. Now it's a ParseError naming the
        # element, not a silent drop.
        with pytest.raises(ParseError, match="mixed content"):
            read_xml("<p>Hello <b>w</b></p>")

    def test_xml_mixed_content_tail_after_child_raises(self):
        # a child's .tail (text between a child close-tag and the next
        # sibling/parent close) is the other place mixed content hides.
        with pytest.raises(ParseError, match="mixed content"):
            read_xml("<p><b>w</b> tail</p>")

    def test_xml_mixed_content_error_names_the_element(self):
        with pytest.raises(ParseError) as exc:
            read_xml("<p>Hello <b>w</b></p>")
        assert "$" in str(exc.value)

    def test_xml_whitespace_only_text_and_tail_still_parse(self):
        # pretty-printed XML (the shape write_xml itself produces) has
        # whitespace-only text/tail around child elements -- that must
        # remain accepted, not be mistaken for mixed content.
        assert read_xml("<p>\n  <b>w</b>\n</p>") == [("p", [("b", "w")])]
        assert read_xml("<p>  <b>w</b>  <c>x</c>  </p>") == \
            [("p", [("b", "w"), ("c", "x")])]

    def test_xml_own_write_output_still_reads_back(self):
        # write_xml's pretty-printer inserts exactly this whitespace-only
        # text/tail shape -- the new mixed-content check must not reject
        # omnist's own round trip.
        d = [("team", [("name", "P"), ("member", "x"), ("member", "y")])]
        assert read_xml(write_xml(d)) == d

    def test_xml_parser_uses_defusedxml_when_available(self):
        # The default, expected case in any environment with the xml/all
        # extra installed (including this test suite's own dev env): the
        # actually-secure parser is what read_xml uses, not a coincidence.
        import defusedxml.ElementTree as defused_ET

        from omnist.formats import _xml_parser

        assert _xml_parser() is defused_ET

    def test_xml_parser_raises_when_defusedxml_missing(self):
        # defusedxml is a hard requirement now (issue #173) -- read_xml must
        # fail closed with a clear ImportError, never silently fall back to
        # the unsafe standard-library parser.
        import builtins

        from omnist.formats import _xml_parser

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("defusedxml"):
                raise ImportError("simulated: defusedxml not installed")
            # Only reached if some unrelated import fires during this mock window.
            return real_import(name, *args, **kwargs)  # pragma: no cover

        import unittest.mock
        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="defusedxml is required"):
                _xml_parser()

    def test_xml_parser_raises_consistently_when_only_submodule_import_fails(self):
        # A subtler variant of the above: the top-level defusedxml package
        # itself imports fine, but its ElementTree submodule specifically
        # fails (e.g. a broken/partial install). The error message must
        # still match the standard "X is required" phrasing, not whatever
        # the submodule import happens to raise.
        import builtins

        from omnist.formats import _xml_parser

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "defusedxml.ElementTree":
                raise ImportError("simulated: submodule import failure")
            # Only reached if some unrelated import fires during this mock window.
            return real_import(name, *args, **kwargs)  # pragma: no cover

        import unittest.mock
        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="defusedxml is required"):
                _xml_parser()

    def test_read_xml_raises_when_defusedxml_missing(self):
        # Same as above, but through the public read_xml() entry point --
        # confirms the fail-closed behavior isn't only true of the internal
        # helper in isolation.
        import builtins
        import unittest.mock

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("defusedxml"):
                raise ImportError("simulated: defusedxml not installed")
            # Only reached if some unrelated import fires during this mock window.
            return real_import(name, *args, **kwargs)  # pragma: no cover

        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="defusedxml is required"):
                read_xml("<a/>")


# ----------------------------------------------------- schema-directed deserialization
class TestDeserialize:
    """``materialize`` (and the ``schema=`` kwarg on read_*) upgrades leaf
    values to match what the schema declares, when the conversion is
    value-exact, and raises otherwise."""

    SCHEMA = ('record R { "d": date, "t": time, "dt": datetime, "n": number, '
              '"i": integer, "s": string, "b": boolean }\nroot R')

    def test_iso_strings_become_real_temporal_objects(self):
        s = parse_schema(self.SCHEMA)
        node = read_json(
            '{"d":"2024-01-01","t":"12:00:00","dt":"2024-01-01T10:00:00",'
            '"n":1,"i":1,"s":"x","b":true}', schema=s)
        values = dict(node)
        assert values["d"] == datetime.date(2024, 1, 1)
        assert values["t"] == datetime.time(12, 0)
        assert values["dt"] == datetime.datetime(2024, 1, 1, 10, 0)

    def test_numeric_exactness_both_directions(self):
        s = parse_schema('record R { "n": number, "i": integer }\nroot R')
        node = read_json('{"n": 3, "i": 4.0}', schema=s)
        values = dict(node)
        assert values["n"] == 3.0 and isinstance(values["n"], float)
        assert values["i"] == 4 and isinstance(values["i"], int)

    def test_inexact_numeric_conversion_raises(self):
        s = parse_schema('record R { "i": integer }\nroot R')
        with pytest.raises(ParseError):
            read_json('{"i": 4.5}', schema=s)

    def test_unparseable_value_raises(self):
        s = parse_schema(self.SCHEMA)
        with pytest.raises(ParseError):
            read_json('{"d":1,"t":"12:00:00","dt":"x","n":1,"i":1,"s":"x","b":true}',
                      schema=s)
        with pytest.raises(ParseError):
            read_json('{"d":"2024-01-01","t":"12:00:00","dt":"x","n":1,"i":1,'
                      '"s":"x","b":true}', schema=s)

    def test_already_typed_values_pass_through(self):
        s = parse_schema(self.SCHEMA)
        node = read_json(
            '{"d":"2024-01-01","t":"12:00:00","dt":"2024-01-01T10:00:00",'
            '"n":1,"i":1,"s":"x","b":true}', schema=s)
        again = materialize(node, s)
        assert again == node

    def test_unknown_field_raises(self):
        # a schema is a request for a guaranteed-conforming Document --
        # an unexpected field is a shape problem, and now raises too
        s = parse_schema('record R { "a": integer }\nroot R')
        with pytest.raises(ParseError, match="unexpected field"):
            read_json('{"a": 1, "b": "extra"}', schema=s)
        assert read_json('{"a": 1}') == [("a", 1)]      # no schema -> unchanged

    def test_shape_mismatches_raise(self):
        # a record expected but the node holds a scalar, or vice versa
        s = parse_schema('record R { "a": R2 }\nrecord R2 { "x": integer }\nroot R')
        with pytest.raises(ParseError, match="expected an object"):
            materialize([("a", 5)], s)
        s2 = parse_schema('record R { "a": integer }\nroot R')
        with pytest.raises(ParseError, match="expected a integer value"):
            materialize([("a", [("x", 1)])], s2)

    def test_missing_field_raises(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        with pytest.raises(ParseError, match="expected exactly 1"):
            materialize([], s)

    def test_multiple_problems_all_reported_together(self):
        s = parse_schema('record R { "a": integer, "b": string }\nroot R')
        with pytest.raises(ParseError) as exc:
            materialize([("a", "x"), ("c", 1)], s)
        msg = str(exc.value)
        assert "unexpected field" in msg          # "c"
        assert "cannot be read as integer" in msg  # "a"
        assert "expected exactly 1" in msg          # missing "b"

    def test_structured_errors_exposed_on_parse_error(self):
        # Same failure as above, but checked structurally via .errors instead
        # of parsing the message string -- what a caller (e.g. an API server
        # building a JSON error response) would actually use.
        s = parse_schema('record R { "a": integer, "b": string }\nroot R')
        with pytest.raises(ParseError) as exc:
            materialize([("a", "x"), ("c", 1)], s)
        errors = exc.value.errors
        assert len(errors) == 3
        codes = {e.code for e in errors}
        assert codes == {"type-mismatch", "unexpected-field", "cardinality"}
        assert all(e.path.startswith("$") for e in errors)
        assert all(isinstance(e.message, str) and e.message for e in errors)

    def test_format_syntax_errors_have_empty_structured_errors(self):
        # ParseError raised for a format-syntax problem (not a schema
        # conformance one) has nothing to put in .errors -- confirms the
        # default is empty rather than None or missing entirely.
        with pytest.raises(ParseError) as exc:
            read_json("not valid json")
        assert exc.value.errors == []

    def test_bool_never_satisfies_integer_or_number(self):
        # bool is an int subclass, but a Scalar("integer")/Scalar("number")
        # must reject it explicitly -- "True" is not a value-exact 1
        s = parse_schema('record R { "i": integer, "n": number }\nroot R')
        with pytest.raises(ParseError):
            materialize([("i", True)], s)
        with pytest.raises(ParseError):
            materialize([("n", True)], s)

    def test_materialize_never_upgrades_a_numeric_shaped_string(self):
        # #288: unlike XML (see TestXmlSchemaDirectedNumericAndBooleanRecovery
        # below), materialize() itself must never coerce a string to a
        # number/boolean -- a string in JSON/YAML/TOML/OML is a deliberate
        # choice, not an untyped placeholder the way XML's text always is.
        s = parse_schema('record R { "i": integer, "n": number, "b": boolean }\nroot R')
        with pytest.raises(ParseError):
            materialize([("i", "3")], s)
        with pytest.raises(ParseError):
            materialize([("n", "29.97")], s)
        with pytest.raises(ParseError):
            materialize([("b", "true")], s)

    def test_a_real_datetime_object_never_satisfies_date(self):
        s = parse_schema('record R { "d": date }\nroot R')
        with pytest.raises(ParseError):
            materialize([("d", datetime.datetime(2024, 1, 1, 9, 0))], s)

    def test_bare_date_string_never_satisfies_datetime(self):
        s = parse_schema('record R { "dt": datetime }\nroot R')
        with pytest.raises(ParseError):
            materialize([("dt", "2024-01-01")], s)

    def test_schema_directed_via_doc_from_json(self):
        from omnist import Doc
        s = parse_schema('record R { "d": date }\nroot R')
        d = Doc.from_json('{"d": "2024-01-01"}', schema=s)
        assert d.get_one("d").value == datetime.date(2024, 1, 1)

    def test_schema_directed_via_doc_from_yaml_toml_xml(self):
        s = parse_schema('record R { "d": date }\nroot R')
        assert Doc.from_yaml('d: "2024-01-01"\n', schema=s).get_one("d").value == \
            datetime.date(2024, 1, 1)
        assert Doc.from_toml('d = "2024-01-01"\n', schema=s).get_one("d").value == \
            datetime.date(2024, 1, 1)
        sx = parse_schema('record Root { "d": date }\nroot Root')
        assert Doc.from_xml("<d>2024-01-01</d>", schema=sx).get_one("d").value == \
            datetime.date(2024, 1, 1)

    def test_xml_temporal_round_trip(self):
        # the XML document element's tag is the schema's single top-level
        # field label (here "t"), per the single-rooted Document model
        s = parse_schema('record Item { "d": date }\nrecord Root { "t": Item }\nroot Root')
        node = read_xml("<t><d>2024-01-01</d></t>", schema=s)
        assert dict(dict(node)["t"])["d"] == datetime.date(2024, 1, 1)

    # -- #157/S3: narrowed temporal spellings -----------------------------
    # `datetime.fromisoformat` accepts more than the docs promise (ISO 8601
    # basic format like "20240101"/"120000", week dates like "2024-W01-1").
    # materialize() now shape-checks against the documented hyphenated/colon
    # forms *before* calling fromisoformat, so a numeric-looking string no
    # longer silently becomes a date/time under a temporal schema.

    def test_documented_spellings_still_upgrade(self):
        s = parse_schema('record R { "d": date, "t": time, "dt": datetime }\nroot R')
        node = materialize(
            [("d", "2024-01-01"), ("t", "12:00:00"), ("dt", "2024-01-01T12:00:00")], s)
        values = dict(node)
        assert values["d"] == datetime.date(2024, 1, 1)
        assert values["t"] == datetime.time(12, 0, 0)
        assert values["dt"] == datetime.datetime(2024, 1, 1, 12, 0, 0)

    def test_basic_format_date_rejected(self):
        s = parse_schema('record R { "d": date }\nroot R')
        with pytest.raises(ParseError, match="not a value-exact conversion"):
            materialize([("d", "20240101")], s)

    def test_week_date_rejected(self):
        s = parse_schema('record R { "d": date }\nroot R')
        with pytest.raises(ParseError):
            materialize([("d", "2024-W01-1")], s)

    def test_basic_format_time_rejected(self):
        s = parse_schema('record R { "t": time }\nroot R')
        with pytest.raises(ParseError):
            materialize([("t", "120000")], s)

    def test_basic_format_datetime_rejected(self):
        s = parse_schema('record R { "dt": datetime }\nroot R')
        with pytest.raises(ParseError):
            materialize([("dt", "20240101T120000")], s)

    def test_space_separated_datetime_rejected(self):
        # fromisoformat also accepts a space instead of 'T' as the
        # date/time separator; the documented form requires 'T'.
        s = parse_schema('record R { "dt": datetime }\nroot R')
        with pytest.raises(ParseError):
            materialize([("dt", "2024-01-01 12:00:00")], s)

    def test_materialize_null_scalar_paths(self):
        # non-nullable scalar receiving null -> null-not-allowed (deserialize.py)
        s = parse_schema('record R { "x": string }\nroot R')
        with pytest.raises(ParseError, match="null not allowed"):
            read_json('{"x": null}', schema=s)
        # nullable scalar receiving null -> passes through untouched
        s2 = parse_schema('record R { "x": string? }\nroot R')
        node = read_json('{"x": null}', schema=s2)
        assert node == [("x", None)]

    def test_validation_error_codes_all_reachable(self):
        # Verify all five error codes are reachable via validation

        # unexpected-field: extra field not in schema
        s1 = parse_schema('record R { "a": integer }\nroot R')
        result = s1.validate(doc({"a": 1, "b": 2}))
        assert not result.ok
        assert any(e.code == "unexpected-field" for e in result.errors)

        # cardinality: field count out of range
        s2 = parse_schema('record R { "a" [1,1]: integer }\nroot R')
        result = s2.validate(doc({"a": [1, 2]}))
        assert not result.ok
        assert any(e.code == "cardinality" for e in result.errors)

        # type-mismatch: value doesn't match scalar type
        s3 = parse_schema('record R { "a": integer }\nroot R')
        result = s3.validate(doc({"a": "not an int"}))
        assert not result.ok
        assert any(e.code == "type-mismatch" for e in result.errors)

        # null-not-allowed: null for non-nullable scalar
        s4 = parse_schema('record R { "a": integer }\nroot R')
        result = s4.validate(doc({"a": None}))
        assert not result.ok
        assert any(e.code == "null-not-allowed" for e in result.errors)

        # shape-mismatch: expected object got scalar or vice versa
        s5 = parse_schema('record R { "a": R2 }\nrecord R2 { "x": integer }\nroot R')
        result = s5.validate(doc({"a": 1}))
        assert not result.ok
        assert any(e.code == "shape-mismatch" for e in result.errors)


# ----------------------------------------------------------- adjustment reports
class TestReports:
    def test_toml_drops_null_with_a_warning(self):
        node = doc({"a": 1, "b": None}).to_data()
        rep = check_toml(node)
        assert [a.code for a in rep] == ["null.omitted"]
        assert rep.warnings and not rep.errors
        assert "b" not in write_toml(node)

    def test_toml_strict_raises_on_null(self):
        node = doc({"a": 1, "b": None}).to_data()
        with pytest.raises(WriteError):
            write_toml(node, strict=True)

    def test_toml_clean_write_has_empty_report(self):
        node = doc({"a": 1}).to_data()
        rep = WriteReport()
        write_toml(node, report=rep)
        assert rep.adjustments == []
        assert bool(rep) is True

    def test_json_temporal_and_special_float(self):
        node = doc({"d": datetime.date(2024, 1, 1)}).to_data()
        rep = check_json(node)
        assert [a.code for a in rep] == ["temporal.stringified"]
        assert write_json(node) == '{"d": "2024-01-01"}'   # actually adjusted, not just reported
        node2 = [("x", float("nan"))]
        rep2 = check_json(node2)
        assert [a.code for a in rep2] == ["float.special"]
        assert rep2.errors

    def test_json_lenient_write_substitutes_null_for_special_floats(self):
        # #157/S1: lenient (default) write_json used to emit the literal,
        # non-standard tokens NaN/Infinity/-Infinity -- invalid JSON per the
        # spec, even though check_json already flagged them error-severity.
        # It now substitutes `null` at those leaves, same as XML substitutes
        # U+FFFD for an illegal character: the output stays well-formed and
        # the report still names the problem.
        import json as _json
        for value in (float("inf"), float("-inf"), float("nan")):
            node = [("a", value)]
            text = write_json(node)
            assert text == '{"a": null}'
            _json.loads(text)                     # must be valid under strict stdlib json
            rep = check_json(node)
            assert [a.code for a in rep] == ["float.special"]
            assert rep.errors
            (adj,) = rep.adjustments
            assert "null" in adj.message           # message notes the substitution

    def test_json_strict_still_refuses_special_floats(self):
        # strict=True is unchanged: it raises rather than substituting, and
        # never emits the (invalid) raw Infinity/NaN token either.
        node = [("a", float("inf"))]
        with pytest.raises(WriteError):
            write_json(node, strict=True)

    def test_json_special_float_nested_in_object(self):
        # the substitution walks nested structure, not just top-level leaves
        node = [("r", [("x", float("inf")), ("y", 1)])]
        text = write_json(node)
        assert text == '{"r": {"x": null, "y": 1}}'

    def test_xml_null_omitted(self):
        node = doc({"a": None}).to_data()
        rep = check_xml(node)
        assert [a.code for a in rep] == ["null.omitted"]

    def test_yaml_time_is_stringified(self):
        node = doc({"t": datetime.time(9, 30)}).to_data()
        rep = check_yaml(node)
        assert [a.code for a in rep] == ["temporal.stringified"]
        assert "09:30:00" in write_yaml(node)

    def test_yaml_bare_time_is_a_sexagesimal_int_trap(self):
        # Issue #268 (docs/formats/yaml.md, "sharp edge"): a bare, unquoted
        # 12:00:00 resolves to the INTEGER 43200 (12*3600 + 0*60 + 0) --
        # YAML 1.1's core-schema sexagesimal number resolution, not an
        # omnist choice, and by the time the value reaches omnist it's
        # already an int. This is a real, documented, user-facing surprise
        # (a config value that looks like a time silently becoming an
        # unrelated integer) with no read-side workaround.
        node = read_yaml("start: 12:00:00")
        assert node == [("start", 43200)]
        assert isinstance(dict(node)["start"], int)

    def test_yaml_nel_value_round_trips_and_is_reported(self):
        # U+0085 (NEL) is normalized to a space by YAML's default scalar
        # styles; omnist forces double-quoted style for it so it round-trips.
        node = [("a", "\x85")]
        rep = check_yaml(node)
        assert [a.code for a in rep] == ["string.line-break-char"]
        assert read_yaml(write_yaml(node)) == node

    def test_yaml_nel_label_round_trips_and_is_reported(self):
        node = [("\x85", None)]
        rep = check_yaml(node)
        assert [a.code for a in rep] == ["string.line-break-char"]
        assert read_yaml(write_yaml(node)) == node

    def test_xml_sanitizes_bad_key_and_reports_temporal(self):
        node = doc({"r": {"a b": 1, "d": datetime.date(2024, 1, 1)}}).to_data()
        rep = check_xml(node)
        codes = {a.code for a in rep}
        assert "key.sanitized" in codes
        assert "temporal.stringified" in codes

    def test_report_arg_and_strict_share_events(self):
        node = doc({"a": 1, "b": None}).to_data()
        rep = WriteReport()
        with pytest.raises(WriteError) as ei:
            write_toml(node, strict=True, report=rep)
        assert [a.code for a in rep] == ["null.omitted"]
        assert ei.value.report.errors == [] and ei.value.report.warnings


# ----------------------------------------------------------- format registry
class TestRegistry:
    def test_builtins_registered(self):
        assert set(formats()) >= {"json", "yaml", "toml", "xml"}

    def test_get_format_round_trips(self):
        fmt = get_format("json")
        node = fmt.read('{"a": 1}')
        assert fmt.write(node) == '{"a": 1}'

    def test_unknown_format_raises(self):
        from omnist.errors import OmnistError
        with pytest.raises(OmnistError):
            get_format("nope")

    def test_register_a_plugin(self):
        register_format(Format(
            "lines",
            read=lambda text: [("n", int(x)) for x in text.split()],
            write=lambda node, **o: " ".join(str(c) for _, c in node),
        ))
        assert "lines" in formats()
        d = Doc.from_format("lines", "1 2 3")
        assert d.to_format("lines") == "1 2 3"

    def test_plugin_without_check_raises_on_check_format(self):
        register_format(Format(
            "nocheck",
            read=lambda text: [("n", int(x)) for x in text.split()],
            write=lambda node, **o: " ".join(str(c) for _, c in node),
        ))
        with pytest.raises(DocumentError):
            Doc.from_format("nocheck", "1 2 3").check_format("nocheck")


# ----------------------------------------------------- Doc.check_* parity
class TestDocCheckParity:
    def test_check_methods_match_module_functions(self):
        node = doc({"a": 1, "b": None}).to_data()
        d = Doc(node)
        assert [a.code for a in d.check_toml()] == [a.code for a in check_toml(node)]
        assert [a.code for a in d.check_json()] == [a.code for a in check_json(node)]
        assert [a.code for a in d.check_yaml()] == [a.code for a in check_yaml(node)]

    def test_check_xml_matches(self):
        node = doc({"r": {"a b": 1}}).to_data()
        d = Doc(node)
        assert [a.code for a in d.check_xml()] == [a.code for a in check_xml(node)]

    def test_check_oml_matches(self):
        node = doc({"a": 1, "b": None}).to_data()
        d = Doc(node)
        assert [a.code for a in d.check_oml()] == [a.code for a in check_oml(node)]

    def test_check_format_matches_named_method(self):
        d = doc({"a": 1, "b": None})
        assert [a.code for a in d.check_format("toml")] == [a.code for a in d.check_toml()]


# ----------------------------------------------------------------- WriteReport
class TestWriteReportStr:
    def test_str_with_no_adjustments(self):
        assert str(WriteReport()) == "no adjustments"

    def test_str_with_adjustments(self):
        node = doc({"a": 1, "b": None}).to_data()
        rep = check_toml(node)
        assert str(rep) == "\n".join(
            f"{a.severity}: {a.path}: {a.message}" for a in rep)
        assert "null value dropped" in str(rep)


# ----------------------------------------------------------- OSD error paths
class TestOsdErrors:
    """Every distinct error the parser can raise, found by reading the
    grammar against the implementation -- not just the happy path."""

    def test_missing_colon(self):
        with pytest.raises(SchemaError, match="expected ':'"):
            parse_schema('record R { "a" integer }\nroot R')

    def test_garbage_top_level_token(self):
        with pytest.raises(SchemaError, match="expected 'record' or 'root'"):
            parse_schema('bogus X\nroot R')

    def test_missing_root_declaration(self):
        with pytest.raises(SchemaError, match="must declare a root"):
            parse_schema('record R { "a": integer }')

    def test_duplicate_definition(self):
        with pytest.raises(SchemaError, match="duplicate definition 'A'"):
            parse_schema('record A { "x": integer }\nrecord A { "y": string }\nroot A')

    def test_unquoted_field_label(self):
        with pytest.raises(SchemaError, match="expected a quoted field name"):
            parse_schema('record R { x: integer }\nroot R')

    def test_empty_cardinality(self):
        with pytest.raises(SchemaError, match="empty cardinality"):
            parse_schema('record R { "a" []: integer }\nroot R')

    def test_missing_closing_brace(self):
        with pytest.raises(SchemaError):
            parse_schema('record R { "a": integer\nroot R')

    def test_unknown_referenced_name(self):
        with pytest.raises(SchemaError, match="unknown type 'Missing'"):
            parse_schema('record R { "a": Missing }\nroot R')


# ---------------------------------------- OSD error codes/paths (issue #301)
class TestOsdErrorCodes:
    """SchemaError.code/.path -- unset (None) unless the raiser passed them,
    so this is purely additive over the message-matching tests above. Every
    site osd.py's own raises wire a code to (parse.* for lexical/token-level
    failures, schema.* for well-formedness) gets one test here."""

    def test_unterminated_string(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a: integer }\nroot R')
        assert exc.value.code == "parse.unterminated-string"
        assert exc.value.path == "11"

    def test_unexpected_character(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "status": "open" | "closed" }\nroot R')
        assert exc.value.code == "parse.unexpected-token"
        assert exc.value.path is not None

    def test_expect_mismatch(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a" integer }\nroot R')
        assert exc.value.code == "parse.unexpected-token"

    def test_garbage_top_level_token(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('bogus X\nroot R')
        assert exc.value.code == "parse.unexpected-token"

    def test_missing_root_declaration(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a": integer }')
        assert exc.value.code == "schema.no-root"
        assert exc.value.path is None

    def test_any_as_record_name_is_reserved_name(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record any { "a": integer }\nroot any')
        assert exc.value.code == "schema.reserved-name"
        assert exc.value.path == "any"

    def test_scalar_keyword_as_record_name_is_reserved_name(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record string { "x": integer }\nroot string')
        assert exc.value.code == "schema.reserved-name"
        assert exc.value.path == "string"

    def test_duplicate_definition(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record A { "x": integer }\nrecord A { "y": string }\nroot A')
        assert exc.value.code == "schema.duplicate-record"
        assert exc.value.path == "A"

    def test_unquoted_field_label(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { x: integer }\nroot R')
        assert exc.value.code == "schema.unquoted-label"

    def test_empty_cardinality(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a" []: integer }\nroot R')
        assert exc.value.code == "schema.empty-cardinality"

    def test_non_integer_cardinality(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a" [1.5,3]: integer }\nroot R')
        assert exc.value.code == "schema.non-integer-cardinality"

    def test_quoted_string_in_type_position(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "status": "open" }\nroot R')
        assert exc.value.code == "schema.quoted-type"

    def test_number_in_type_position_is_unexpected_token_not_quoted_type(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "n": 5 }\nroot R')
        assert exc.value.code == "parse.unexpected-token"

    def test_any_question_mark_is_nullable_any(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record R { "a": any? }\nroot R')
        assert exc.value.code == "schema.nullable-any"

    def test_question_mark_on_ref_is_nullable_ref(self):
        with pytest.raises(SchemaError) as exc:
            parse_schema('record A { "x": integer }\nrecord R { "a": A? }\nroot R')
        assert exc.value.code == "schema.nullable-ref"
        assert exc.value.path == "A"

    def test_unstructured_schemaerror_has_no_code_or_path(self):
        # any SchemaError site this issue didn't touch (most of schema.py's
        # builder-API raises) still defaults both to None -- backward
        # compatible, not a silent "code": "" placeholder.
        exc = SchemaError("plain message, no structure")
        assert exc.code is None
        assert exc.path is None


# --------------------------------------------------- Document robustness
class TestDocumentRobustness:
    """The recursion/cycle guards SECURITY.md describes -- verified, not
    just asserted."""

    def test_deeply_nested_input_raises_cleanly(self):
        value = "leaf"
        for _ in range(250):
            value = {"x": value}
        with pytest.raises(DocumentError, match="nesting exceeds the maximum depth"):
            doc(value)

    def test_xml_at_the_depth_boundary_still_parses(self):
        # 200 levels of nesting is the documented limit -- same boundary as
        # build_node's own guard (issue #155, B3).
        s = "<v>1</v>"
        for _ in range(200):
            s = f"<a>{s}</a>"
        read_xml(s)  # must not raise

    def test_xml_one_past_the_depth_boundary_raises_cleanly(self):
        s = "<v>1</v>"
        for _ in range(201):
            s = f"<a>{s}</a>"
        with pytest.raises(DocumentError, match="nesting exceeds the maximum depth"):
            read_xml(s)

    def test_xml_deeply_nested_input_raises_cleanly_not_recursionerror(self):
        # _xml_to_node used to recurse with no depth guard at all, so
        # deeply-nested XML died with a raw RecursionError instead of the
        # clean DocumentError every other reader gives via build_node's
        # _MAX_DEPTH (issue #155, B3).
        s = "<v>1</v>"
        for _ in range(1000):
            s = f"<a>{s}</a>"
        with pytest.raises(DocumentError, match="nesting exceeds the maximum depth"):
            read_xml(s)

    def test_xml_exceeding_the_node_budget_raises_cleanly(self, monkeypatch):
        # Issue #260: read_xml used to have no node-count ceiling at all
        # (only the depth guard above), unlike the other three readers
        # after #259's fix for the YAML alias-amplification hole. XML has
        # no aliasing mechanism to create a DAG the way YAML anchors do
        # (and defusedxml blocks DTDs, closing the classic entity-expansion
        # vector upstream), so this isn't about a known exploit -- it's
        # closing the one reader that didn't share the same size ceiling
        # as the rest.
        #
        # sys.modules, not `import omnist.formats as x`: the omnist package
        # re-exports a *function* also named `formats` (the format-registry
        # listing, from .registry), which shadows the submodule as a plain
        # attribute of the omnist package once omnist/__init__.py has run --
        # sys.modules['omnist.formats'] reliably gets the real module.
        import sys
        formats_module = sys.modules["omnist.formats"]
        monkeypatch.setattr(formats_module, "_MAX_NODES", 3)

        with pytest.raises(DocumentError, match="too many nodes materialized"):
            read_xml("<a><b><c>1</c><d>2</d></b><e>3</e></a>")

    def test_xml_under_the_node_budget_still_parses(self, monkeypatch):
        import sys
        formats_module = sys.modules["omnist.formats"]
        monkeypatch.setattr(formats_module, "_MAX_NODES", 3)

        # Exactly 3 elements (a, b, c) -- at the boundary, must not raise.
        assert read_xml("<a><b><c>1</c></b></a>") == [
            ("a", [("b", [("c", "1")])])]

    def test_add_at_a_deep_cursor_raises_once_combined_depth_exceeds_limit(self):
        # Issue #255: add()/set() used to call build_node with the default
        # depth=0, ignoring how deep the cursor doing the add already was
        # -- so a mutation could silently push the tree past _MAX_DEPTH
        # (200) with no error. A cursor at depth 190 plus a 15-level-deep
        # subtree is 190 + 1 (attach) + 15 = 206, over the limit.
        def nest(levels):
            v = 0
            for _ in range(levels):
                v = {"a": v}
            return v

        d = doc(nest(200))
        cursor = d
        for _ in range(190):
            cursor = cursor.child("a")

        with pytest.raises(DocumentError, match="nesting exceeds the maximum depth"):
            cursor.add("b", nest(15))

    def test_set_at_a_deep_cursor_raises_once_combined_depth_exceeds_limit(self):
        def nest(levels):
            v = 0
            for _ in range(levels):
                v = {"a": v}
            return v

        d = doc(nest(200))
        cursor = d
        for _ in range(190):
            cursor = cursor.child("a")

        with pytest.raises(DocumentError, match="nesting exceeds the maximum depth"):
            cursor.set("b", nest(15))

    def test_add_at_a_shallow_cursor_still_works(self):
        # A modest subtree attached near the root must not be rejected --
        # confirms the fix doesn't over-tighten the guard.
        d = doc({"x": 1})
        d.add("y", {"nested": {"deeper": 1}})
        assert d.get_one("y").get_one("nested").get_one("deeper").value == 1

    def test_add_exactly_at_the_depth_boundary_still_works(self):
        # A cursor at depth 199 attaching a single-level leaf value lands
        # exactly at depth 200 -- the documented boundary, must not raise.
        # nest(200), not nest(199): 199 child() traversals must still land
        # on an internal node (able to add()), not the terminal leaf.
        def nest(levels):
            v = 0
            for _ in range(levels):
                v = {"a": v}
            return v

        d = doc(nest(200))
        cursor = d
        for _ in range(199):
            cursor = cursor.child("a")
        assert not cursor.is_leaf
        cursor.add("b", 1)  # depth 199 + 1 = 200, must not raise
        assert cursor.get_one("b").value == 1

    def test_self_referential_dict_raises_cleanly(self):
        d = {}
        d["self"] = d
        with pytest.raises(DocumentError, match="cycle detected"):
            doc(d)

    def test_yaml_alias_amplification_raises_cleanly(self, monkeypatch):
        # Issue #256: PyYAML resolves *alias references as shared object
        # identity (a DAG), not clones -- so a chain of doubly-referenced
        # anchors ("billion laughs") materializes O(2**n) nodes from an
        # O(n)-sized source text. build_node's cycle guard (`seen`) only
        # catches a literal cycle -- an object that is its own ancestor on
        # the current path -- not a shared DAG node reached via two
        # different, non-ancestor paths, so it doesn't help here.
        # _MAX_DEPTH doesn't help either: this attack is O(n) deep with
        # O(2**n) *breadth*, not deep nesting.
        #
        # Patches _MAX_NODES down so a tiny 10-generation chain exercises
        # the same guard fast, instead of needing to actually materialize
        # toward the real 1,000,000-node production ceiling.
        import omnist.document as document_module
        monkeypatch.setattr(document_module, "_MAX_NODES", 50)

        text = "a0: &a0 {x: 1, y: 2}\n"
        for i in range(1, 10):
            text += f"a{i}: &a{i}\n  p: *a{i-1}\n  q: *a{i-1}\n"

        with pytest.raises(DocumentError, match="too many nodes materialized"):
            read_yaml(text)

    def test_yaml_alias_amplification_bails_fast_not_after_full_expansion(self, monkeypatch):
        # The guard must reject *during* the walk, not after fully
        # expanding the exponential structure and then checking -- confirms
        # the fix also closes the DoS/timing angle, not just eventually
        # raising after the fact. 25 generations is deep enough that a
        # full O(2**25) walk would not complete in any reasonable time;
        # under a 2-second budget it must still be caught.
        import time

        import omnist.document as document_module
        monkeypatch.setattr(document_module, "_MAX_NODES", 1000)

        text = "a0: &a0 {x: 1, y: 2}\n"
        for i in range(1, 25):
            text += f"a{i}: &a{i}\n  p: *a{i-1}\n  q: *a{i-1}\n"

        start = time.time()
        with pytest.raises(DocumentError, match="too many nodes materialized"):
            read_yaml(text)
        assert time.time() - start < 2.0

    def test_large_legitimate_document_is_not_rejected_by_node_budget(self):
        # Non-regression: the exact "100k-edge document" shape docs/
        # why-omnist.md's own performance benchmark measures (33k records
        # of 3 fields each) must still build successfully -- it needs
        # ~132,001 actual build_node calls once every scalar leaf and
        # container is counted individually, comfortably under the real
        # 1,000,000 production ceiling. Confirms the fix didn't
        # over-tighten the guard against real, already-measured usage.
        big = {"items": [{"a": i, "b": i, "c": i} for i in range(33000)]}
        d = doc(big)
        assert len(d.to_data()) == 33000

    def test_unsupported_python_type_raises(self):
        with pytest.raises(DocumentError, match="is not a Document value"):
            doc({"a": {1, 2, 3}})

    def test_value_on_internal_node_raises(self):
        d = doc({"a": 1})
        with pytest.raises(DocumentError, match="not a leaf"):
            d.value

    def test_edges_on_leaf_raises(self):
        d = doc({"a": 1}).get_one("a")
        with pytest.raises(DocumentError, match="a leaf has no edges"):
            d.edges()

    def test_get_one_wrong_count_raises(self):
        d = doc({"a": 1, "b": 2})
        with pytest.raises(DocumentError, match="found 0"):
            d.get_one("missing")
        d2 = doc({"a": 1, "a2": 2})
        d2._node.append(("a", 3))  # force a second "a" via direct node access
        with pytest.raises(DocumentError, match="found 2"):
            d2.get_one("a")

    def test_editing_a_leaf_raises(self):
        leaf = doc({"a": 1}).get_one("a")
        with pytest.raises(DocumentError, match="cannot add on a leaf"):
            leaf.add("x", 1)
        with pytest.raises(DocumentError, match="cannot set on a leaf"):
            leaf.set("x", 1)
        with pytest.raises(DocumentError, match="cannot remove on a leaf"):
            leaf.remove("x")

    # -- 4300-digit int cap at construction (issue #156, B2) --------------
    # A too-big literal can't be spelled with int('9' * 4301) directly --
    # CPython's own guard fires on that str->int conversion first. Build it
    # via arithmetic (int->int, never string) instead, exactly as a
    # legitimately-computed huge int would arrive in practice.
    _BIG_OK = int("9" * 4300)
    _BIG_BAD = _BIG_OK * 10 + 9   # one more digit, no string conversion involved

    def test_int_at_digit_cap_boundary_is_accepted_end_to_end(self):
        d = doc({"a": self._BIG_OK})
        assert d.get_one("a").value == self._BIG_OK
        d.to_oml()          # must not raise
        d.to_json()         # must not raise
        repr(d)              # must not raise

    def test_int_one_past_digit_cap_rejected_by_doc(self):
        with pytest.raises(DocumentError, match="more than 4300 digits"):
            doc({"a": self._BIG_BAD})

    def test_int_one_past_digit_cap_rejected_by_add(self):
        d = doc({})
        with pytest.raises(DocumentError, match="more than 4300 digits"):
            d.add("a", self._BIG_BAD)
        # rejected before mutation -- the edge list is untouched
        assert d.to_data() == []

    def test_int_one_past_digit_cap_rejected_by_set(self):
        d = doc({})
        with pytest.raises(DocumentError, match="more than 4300 digits"):
            d.set("a", self._BIG_BAD)
        assert d.to_data() == []

    def test_negative_int_one_past_digit_cap_rejected(self):
        with pytest.raises(DocumentError, match="more than 4300 digits"):
            doc({"a": -self._BIG_BAD})

    def test_negative_int_at_digit_cap_boundary_accepted(self):
        doc({"a": -self._BIG_OK}).to_oml()   # must not raise

    def test_bools_never_trip_the_digit_cap(self):
        # bool is an int subclass; make sure the guard special-cases it
        # rather than trying (and failing) to compare it against the cap.
        d = doc({"t": True, "f": False})
        d.add("t2", True)
        d.set("t", False)
        assert d.to_data() == [("t", False), ("f", False), ("t2", True)]

    def test_oversized_int_from_read_json_raises_cleanly(self):
        # json.loads converts the integer literal to `int` while parsing --
        # before build_node ever runs -- so this exercises a different code
        # path than doc()/add()/set(). It must not leak CPython's raw
        # ValueError; formats.py translates it to ParseError like any other
        # parse-time failure (the readers' existing convention: syntax/
        # conversion errors during read -> ParseError).
        text = '{"a": ' + ("9" * 4301) + "}"
        with pytest.raises(ParseError):
            read_json(text)

    def test_oversized_int_from_read_yaml_raises_cleanly(self):
        text = "a: " + ("9" * 4301)
        with pytest.raises(ParseError):
            read_yaml(text)

    def test_oversized_int_from_read_toml_raises_cleanly(self):
        text = "a = " + ("9" * 4301)
        with pytest.raises(ParseError):
            read_toml(text)

    def test_eq_against_non_document_value(self):
        assert doc({"a": 1}) != {1, 2, 3}    # a set has no Document form

    def test_repr(self):
        assert repr(doc(1)) == "Doc(leaf: 1)"
        assert "node:" in repr(doc({"a": 1}))

    def test_doc_to_json_yaml_xml_methods(self):
        d = doc({"a": 1})
        assert d.to_json() == '{"a": 1}'
        assert d.to_yaml() == "a: 1\n"
        assert d.to_xml() == "<a>1</a>"

    def test_doc_equals_doc(self):
        assert doc({"a": 1}) == doc({"a": 1})
        assert doc({"a": 1}) != doc({"a": 2})

    def test_doc_validate_delegates_to_schema(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        assert doc({"a": 1}).validate(s).ok


# --------------------------------------------------------- Schema/builder misuse
class TestSchemaConstructionErrors:
    """Defensive validation in the model classes themselves, not just
    OSD -- the Python builder is just as much a public surface."""

    def test_field_type_must_be_ref_or_scalar(self):
        with pytest.raises(SchemaError, match="must be a Ref, Scalar, or t.any"):
            Field("x", "not-a-type")

    def test_field_invalid_cardinality(self):
        with pytest.raises(SchemaError, match="invalid cardinality"):
            Field("x", t.string, min=2, max=1)

    def test_record_duplicate_label(self):
        with pytest.raises(SchemaError, match="duplicate field label"):
            Record([Field("a", t.string), Field("a", t.integer)])

    def test_schema_root_must_be_a_ref(self):
        with pytest.raises(SchemaError, match="root must be a Ref"):
            Schema("R", {})

    def test_schema_env_value_must_be_a_record(self):
        # a loosely-typed caller (the schema()/Schema() constructors don't
        # enforce this at the type level) handing in a bare Scalar used to
        # crash with AttributeError instead of raising SchemaError
        with pytest.raises(SchemaError, match="must be a Record"):
            schema(ref("R"), R=t.string)

    def test_record_name_shadowing_a_scalar_keyword_is_rejected(self):
        # Issue #263 (spec S-3): type position resolves a bare name to a
        # builtin scalar first, so a record literally named "string" could
        # never be referenced -- osd.py's parser already rejects this; the
        # Python builder API used to accept it silently.
        with pytest.raises(SchemaError, match="shadows a scalar keyword"):
            schema(ref("string"), string=record(field("a", t.string)))

    def test_record_name_shadowing_any_is_rejected(self):
        with pytest.raises(SchemaError, match="shadows a scalar keyword"):
            schema(ref("any"), any=record(field("a", t.string)))

    def test_nullable_ref_raises_schema_error(self):
        # Issue #264 (spec S-7): nullable() used to assume its argument was
        # always a Scalar and crashed with a bare AttributeError on a Ref.
        with pytest.raises(SchemaError, match="cannot be applied to a Ref"):
            nullable(ref("R"))


# ----------------------------------------------------------------- dunders
class TestSchemaModelDunders:
    """__repr__/__eq__/__hash__/__str__/__bool__ on the small model classes
    -- not exercised by the OSD/validation-focused tests elsewhere."""

    def test_scalar_unknown_name_raises(self):
        with pytest.raises(SchemaError, match="unknown scalar"):
            Scalar("not-a-real-scalar")

    def test_scalar_eq_and_hash(self):
        assert Scalar("string") == Scalar("string")
        assert Scalar("string") != Scalar("integer")
        assert Scalar("string") != "string"          # not a Scalar at all
        assert hash(Scalar("string")) == hash(Scalar("string"))

    def test_ref_repr_eq_and_hash(self):
        assert repr(Ref("R")) == "ref(R)"
        assert Ref("R") == Ref("R")
        assert Ref("R") != Ref("S")
        assert Ref("R") != "R"
        assert hash(Ref("R")) == hash(Ref("R"))

    def test_field_eq(self):
        # Issue #273 / omnist-spec conformance-harness.md §5
        assert Field("a", t.string, 1, 1) == Field("a", t.string, 1, 1)
        assert Field("a", t.string, 1, 1) != Field("b", t.string, 1, 1)
        assert Field("a", t.string, 1, 1) != Field("a", t.integer, 1, 1)
        assert Field("a", t.string, 0, 1) != Field("a", t.string, 1, 1)
        assert Field("a", t.string, 1, 1) != Field("a", t.string, 1, 2)
        assert Field("a", nullable(t.string), 1, 1) != Field("a", t.string, 1, 1)
        assert Field("a", t.string, 1, 1) != "not a field"

    def test_record_eq_is_order_independent(self):
        # Fields form an unordered set at the model layer -- declaration
        # order must not affect equality.
        a = Record([Field("a", t.string), Field("b", t.integer)])
        b = Record([Field("b", t.integer), Field("a", t.string)])
        assert a == b

    def test_record_eq_differs_by_one_field(self):
        a = Record([Field("a", t.string), Field("b", t.integer)])
        differs_cardinality = Record(
            [Field("a", t.string), Field("b", t.integer, min=0)])
        differs_type = Record(
            [Field("a", t.string), Field("b", t.string)])
        assert a != differs_cardinality
        assert a != differs_type
        assert a != "not a record"

    def test_schema_eq_is_order_independent_across_declaration_order(self):
        # A schema built two different ways -- different field order
        # within a record, different record order in env -- but
        # structurally identical must compare equal.
        s1 = parse_schema(
            'record A { "x": integer, "y": string }\n'
            'record B { "a": A }\nroot B')
        s2 = parse_schema(
            'record B { "a": A }\n'
            'record A { "y": string, "x": integer }\nroot B')
        assert s1 == s2

    def test_schema_eq_differs_by_one_field(self):
        base = parse_schema('record R { "a": integer }\nroot R')
        differs_nullable = parse_schema('record R { "a": integer? }\nroot R')
        differs_root = parse_schema(
            'record R { "a": integer }\nrecord S { "a": integer }\nroot S')
        assert base != differs_nullable
        assert base != differs_root
        assert base != "not a schema"

    def test_types_namespace_repr(self):
        assert "seven scalars" in repr(t)

    def test_field_cardinality_str_zero_or_one(self):
        f = Field("x", t.string, min=0, max=1)
        assert f.cardinality_str() == "0 or 1"

    def test_field_repr(self):
        f = Field("x", t.string, min=0, max=2)
        assert repr(f) == "Field('x'[0,2]: string)"

    def test_record_repr(self):
        rec = Record([Field("a", t.string)])
        assert repr(rec) == "record{Field('a'[1,1]: string)}"

    def test_validation_result_bool_str_repr(self):
        ok = ValidationResult()
        assert bool(ok) is True
        assert str(ok) == "valid"
        assert repr(ok) == "ValidationResult(ok=True, errors=0)"

        bad = ValidationResult()
        bad.add("$.a", "boom", "type-mismatch")
        assert bool(bad) is False
        assert str(bad) == "invalid:\n  at $.a: boom"
        assert repr(bad) == "ValidationResult(ok=False, errors=1)"

    def test_schema_repr(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        assert repr(s) == "Schema(root=ref(R), env=['R'])"

    def test_resolve_unknown_type_raises(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        with pytest.raises(SchemaError, match="unknown type 'Ghost'"):
            s.resolve(ref("Ghost"))

    def test_resolve_single_hop_semantics(self):
        # check_refs() guarantees every env value is a Record, so Ref resolves
        # in exactly one hop; no chaining or cycles are possible.
        s = schema(ref("Point"), Point=record(field("x", t.integer), field("y", t.integer)))
        rec = s.resolve(ref("Point"))
        assert isinstance(rec, Record)
        assert rec is s.env["Point"]
        # unknown-name Ref still raises SchemaError
        with pytest.raises(SchemaError, match="unknown type 'Nope'"):
            s.resolve(ref("Nope"))

    def test_validate_requires_a_doc(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        with pytest.raises(TypeError, match=r"validate\(\) expects a Doc"):
            s.validate({"a": 1})

    def test_accepts_delegates_to_validate(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        assert s.accepts(doc({"a": 1})) is True
        assert s.accepts(doc({"a": "x"})) is False

    def test_conform_scalar_leaf_required_got_object(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        bad = doc({"a": {"nested": 1}})
        res = s.validate(bad)
        assert not res.ok
        assert any("got an object" in e.message for e in res.errors)

    def test_conform_scalar_null_not_allowed(self):
        s = parse_schema('record R { "a": integer }\nroot R')
        bad = doc({"a": None})
        res = s.validate(bad)
        assert not res.ok
        assert any("null not allowed here" in e.message for e in res.errors)

    def test_conform_record_leaf_required_object(self):
        s = parse_schema('record Inner { "x": integer }\nrecord R { "a": Inner }\nroot R')
        bad = doc({"a": 1})
        res = s.validate(bad)
        assert not res.ok
        assert any("expected an object, got a value" in e.message for e in res.errors)


# ------------------------------------------------------- matches_kind / value_kind
class TestMatchesKindAndValueKind:
    def test_matches_kind_time_object(self):
        assert matches_kind(datetime.time(12, 0), "time")

    def test_matches_kind_datetime_not_a_date(self):
        assert not matches_kind(datetime.datetime(2024, 1, 1), "date")

    def test_value_kind_temporal_types(self):
        assert value_kind(datetime.datetime(2024, 1, 1)) == "datetime"
        assert value_kind(datetime.date(2024, 1, 1)) == "date"
        assert value_kind(datetime.time(12, 0)) == "time"

    def test_value_kind_boolean(self):
        assert value_kind(True) == "boolean"

    def test_matches_kind_unknown_name_never_matches(self):
        # matches_kind is only ever called by _conform_scalar with a name
        # taken from a Scalar, and Scalar.__init__ already restricts names
        # to SCALAR_NAMES -- so an unrecognized name can't arrive through
        # the public API. This guards the function's own contract directly.
        assert matches_kind("anything", "not-a-real-scalar-name") is False

    # -- #157/S3: matches_kind narrowed to the documented spellings too ----
    # validate() (via matches_kind/_is_iso) had the same wide-acceptance
    # issue as materialize(): both now reject ISO 8601 basic format and
    # week dates, not just the hyphenated/colon forms.

    def test_matches_kind_rejects_basic_format_date(self):
        assert not matches_kind("20240101", "date")

    def test_matches_kind_rejects_week_date(self):
        assert not matches_kind("2024-W01-1", "date")

    def test_matches_kind_rejects_basic_format_time(self):
        assert not matches_kind("120000", "time")

    def test_matches_kind_rejects_basic_format_datetime(self):
        assert not matches_kind("20240101T120000", "datetime")

    def test_matches_kind_still_accepts_documented_spellings(self):
        assert matches_kind("2024-01-01", "date")
        assert matches_kind("12:00:00", "time")
        assert matches_kind("2024-01-01T12:00:00", "datetime")

    def test_matches_kind_rejects_shape_valid_but_calendar_invalid_strings(self):
        # right shape (matches _DATE_RE/_TIME_RE) but not an actual
        # calendar date/time -- fromisoformat itself raises ValueError for
        # these, exercising _is_iso's except branch, not the regex.
        assert not matches_kind("2024-13-01", "date")     # month 13
        assert not matches_kind("2024-02-30", "date")     # Feb 30 never exists
        assert not matches_kind("25:00:00", "time")       # hour 25


# ------------------------------------- validate()/materialize() agreement
class TestValidateMaterializeAgreement:
    """#157/S3: 'a doc that validates must materialize and vice versa.'

    validate() (Schema._conform_scalar -> matches_kind/_is_iso) and
    materialize() (deserialize._materialize_temporal) used to disagree at
    the ISO-8601-basic-format/week-date boundary: fromisoformat's wider
    acceptance leaked into materialize() but matches_kind already narrowed
    validate() only partially. Both now share the exact same shape check
    (schema.py's _DATE_RE/_TIME_RE/_DATETIME_RE, adapted from oml.py), so
    they must agree on every spelling -- asserted directly here rather than
    just observed to happen to agree."""

    BOUNDARY_SPELLINGS = [
        "2024-01-01",          # documented date -- both accept
        "20240101",            # ISO basic format -- both must reject
        "2024-W01-1",          # ISO week date -- both must reject
        "12:00:00",            # documented time, but not a `date`
        "120000",               # ISO basic format time -- both must reject
        "2024-01-01T12:00:00",  # documented datetime, but not a bare `date`
        "20240101T120000",      # ISO basic format datetime -- both must reject
        "2024-01-01 12:00:00",  # space-separated -- fromisoformat accepts, docs don't
        "not-a-date-at-all",
    ]

    @pytest.mark.parametrize("kind", ["date", "time", "datetime"])
    def test_validate_and_materialize_agree_on_every_boundary_spelling(self, kind):
        s = parse_schema(f'record R {{ "v": {kind} }}\nroot R')
        for spelling in self.BOUNDARY_SPELLINGS:
            validates = s.validate(doc({"v": spelling})).ok
            try:
                materialize([("v", spelling)], s)
                materializes = True
            except ParseError:
                materializes = False
            assert validates == materializes, (
                f"{kind} / {spelling!r}: validate()={validates} but "
                f"materialize()={materializes} -- disagreement")


# ----------------------------------------------------------- infer() errors
class TestInferErrors:
    def test_zero_samples_raises(self):
        with pytest.raises(SchemaError, match="zero samples"):
            infer([])

    def test_non_object_root_raises(self):
        with pytest.raises(SchemaError, match="object .record. samples"):
            infer([doc(5)])

    def test_mixed_object_and_scalar_for_one_label_raises(self):
        with pytest.raises(SchemaError, match="mixes objects and values"):
            infer([doc({"a": {"x": 1}}), doc({"a": 5})])

    def test_generated_record_names_dont_collide(self):
        # "item" and "Item" both capitalize to the generated name "Item"
        s = infer([doc({"item": {"a": 1}, "Item": {"b": 2}})])
        assert {"Item", "Item2"} <= set(s.env)


# ------------------------------------------------ infer --allow-any fallback
class TestInferAllowAny:
    def test_multi_kind_scalar_opens_to_any(self):
        from omnist import AnyType, infer_with_report
        s, fb = infer_with_report(
            [doc({"v": 1}), doc({"v": "x"})], allow_any=True)
        assert isinstance(s.env["Root"].fields[0].type, AnyType)
        assert len(fb) == 1
        assert fb[0].location == "Root.v"
        assert fb[0].reason == "values of more than one scalar kind (integer, string)"

    def test_object_value_mix_opens_to_any(self):
        from omnist import AnyType, infer_with_report
        s, fb = infer_with_report(
            [doc({"a": {"x": 1}}), doc({"a": 5})], allow_any=True)
        assert isinstance(s.env["Root"].fields[0].type, AnyType)
        assert len(fb) == 1
        assert fb[0].location == "Root.a"
        assert fb[0].reason == "mixes objects and values"

    def test_siblings_stay_precise(self):
        from omnist import AnyType, Scalar, infer_with_report
        s, fb = infer_with_report(
            [doc({"v": 1, "name": "Ann"}), doc({"v": "x", "name": "Bob"})],
            allow_any=True)
        rec = s.env["Root"]
        by_label = {f.label: f.type for f in rec.fields}
        assert isinstance(by_label["v"], AnyType)
        assert isinstance(by_label["name"], Scalar)
        assert by_label["name"].name == "string"
        assert [f.location for f in fb] == ["Root.v"]

    def test_nested_all_object_label_still_a_record_not_any(self):
        # narrowest-node scoping: a clean nested object still becomes a record;
        # only the genuinely-conflicting field opens.
        from omnist import AnyType, Ref, infer_with_report
        s, fb = infer_with_report(
            [doc({"addr": {"city": "X"}, "v": 1}),
             doc({"addr": {"city": "Y"}, "v": "s"})],
            allow_any=True)
        by_label = {f.label: f.type for f in s.env["Root"].fields}
        assert isinstance(by_label["addr"], Ref)
        assert isinstance(by_label["v"], AnyType)
        assert [f.location for f in fb] == ["Root.v"]

    def test_fallback_location_uses_nested_record_name(self):
        from omnist import infer_with_report
        _, fb = infer_with_report(
            [doc({"outer": {"v": 1}}), doc({"outer": {"v": "s"}})],
            allow_any=True)
        assert [f.location for f in fb] == ["Outer.v"]

    def test_default_still_raises_at_multi_kind_site(self):
        with pytest.raises(SchemaError, match="more than one scalar"):
            infer([doc({"v": 1}), doc({"v": "x"})])
        with pytest.raises(SchemaError, match="more than one scalar"):
            infer([doc({"v": 1}), doc({"v": "x"})], allow_any=False)

    def test_default_still_raises_at_object_value_mix_site(self):
        with pytest.raises(SchemaError, match="mixes objects and values"):
            infer([doc({"a": {"x": 1}}), doc({"a": 5})])
        with pytest.raises(SchemaError, match="mixes objects and values"):
            infer([doc({"a": {"x": 1}}), doc({"a": 5})], allow_any=False)

    def test_clean_samples_report_empty(self):
        from omnist import infer_with_report
        s, fb = infer_with_report(
            [doc({"name": "Ann", "age": 30})], allow_any=True)
        assert fb == []

    def test_infer_thin_wrapper_returns_just_schema(self):
        from omnist import Schema
        s = infer([doc({"v": 1}), doc({"v": "x"})], allow_any=True)
        assert isinstance(s, Schema)

    def test_report_order_is_deterministic(self):
        from omnist import infer_with_report
        _, fb = infer_with_report(
            [doc({"a": 1, "b": {"x": 1}}), doc({"a": "s", "b": 2})],
            allow_any=True)
        assert [f.location for f in fb] == ["Root.a", "Root.b"]


# --------------------------------------------------- operations edge cases
class TestOperationsEdgeCases:
    def test_scalar_vs_record_never_compatible(self):
        a = parse_schema('record R { "v": integer }\nroot R')
        b = parse_schema('record R { "v": V }\nrecord V { "x": integer }\nroot R')
        assert not compatible_with(a, b)
        assert not compatible_with(b, a)

    def test_a_must_guarantee_every_field_b_requires(self):
        a = parse_schema('record R { "v": integer }\nroot R')
        b = parse_schema('record R { "v": integer, "w": string }\nroot R')
        # b requires "w"; a has no "w" at all (not just insufficient cardinality)
        assert not compatible_with(a, b)

    def test_unbounded_max_not_compatible_with_a_bounded_one(self):
        a = parse_schema('record R { "xs" [1,]: integer }\nroot R')    # unbounded
        b = parse_schema('record R { "xs" [1,5]: integer }\nroot R')   # bounded
        assert not compatible_with(a, b)
        assert compatible_with(b, a)

    def test_extra_field_b_doesnt_know_about_is_not_compatible(self):
        a = parse_schema('record R { "v": integer, "extra": string }\nroot R')
        b = parse_schema('record R { "v": integer }\nroot R')          # closed, no "extra"
        assert not compatible_with(a, b)

    def test_a_field_with_max_zero_is_skipped_even_if_b_lacks_it(self):
        # cardinality [0,0] means the field is declared but never actually
        # emitted -- B doesn't need to know about it at all
        a = parse_schema('record R { "never" [0,0]: integer, "v": integer }\nroot R')
        b = parse_schema('record R { "v": integer }\nroot R')
        assert compatible_with(a, b)


# --------------------------------------------------------- XML adjustment codes
class TestXmlSchemaDirectedNumericAndBooleanRecovery:
    """#288: XML has no boolean/integer/number literals, so schema-directed
    read_xml needs an XML-specific pretype step to recover them from text --
    materialize() itself must never do this generically (see
    test_materialize_never_upgrades_a_numeric_shaped_string above)."""

    def test_upgrades_value_exact(self):
        s = parse_schema('record Inner { "b": boolean, "i": integer, "n": number }\n'
                          'record R { "r": Inner }\nroot R')
        node = read_xml(
            "<r><b>true</b><i>3</i><n>29.97</n></r>", schema=s)
        assert node == [("r", [("b", True), ("i", 3), ("n", 29.97)])]
        node = read_xml(
            "<r><b>false</b><i>-7</i><n>0</n></r>", schema=s)
        assert node == [("r", [("b", False), ("i", -7), ("n", 0.0)])]

    def test_rejects_non_canonical_spelling(self):
        # value-exact means the spelling, not just parseability -- "True"
        # (capitalized), a leading zero, or a leading '+' are all things
        # Python would happily parse but aren't the canonical spelling
        # write_xml itself would ever produce, so they don't upgrade --
        # materialize() then rejects the still-string value as usual.
        s = parse_schema('record Inner { "b": boolean }\nrecord R { "r": Inner }\nroot R')
        with pytest.raises(ParseError):
            read_xml("<r><b>True</b></r>", schema=s)
        s = parse_schema('record Inner { "i": integer }\nrecord R { "r": Inner }\nroot R')
        with pytest.raises(ParseError):
            read_xml("<r><i>007</i></r>", schema=s)
        with pytest.raises(ParseError):
            read_xml("<r><i>+3</i></r>", schema=s)
        with pytest.raises(ParseError):
            read_xml("<r><i>1.5</i></r>", schema=s)
        s = parse_schema('record Inner { "n": number }\nrecord R { "r": Inner }\nroot R')
        with pytest.raises(ParseError):
            read_xml("<r><n>abc</n></r>", schema=s)

    def test_any_typed_field_passes_through_untouched(self):
        s = parse_schema('record Inner { "x": any }\nrecord R { "r": Inner }\nroot R')
        node = read_xml("<r><x>3</x></r>", schema=s)
        assert node == [("r", [("x", "3")])]

    def test_shape_mismatch_left_for_materialize_to_flag(self):
        # schema expects a record where the field is; XML gives a scalar
        # leaf instead -- the pretype pass must not crash iterating it,
        # just pass it through for materialize()'s own shape check to reject.
        s = parse_schema('record Inner { "x": string }\n'
                          'record R { "r": Inner }\nroot R')
        with pytest.raises(ParseError, match="expected an object"):
            read_xml("<r>3</r>", schema=s)

    def test_unexpected_field_left_untouched_for_materialize_to_flag(self):
        s = parse_schema('record Inner { "known": string }\n'
                          'record R { "r": Inner }\nroot R')
        with pytest.raises(ParseError, match="unexpected field"):
            read_xml("<r><known>x</known><extra>3</extra></r>", schema=s)


class TestXmlAdjustmentCodes:
    def test_number_shaped_string_no_longer_flagged_ambiguous(self):
        # #288: read_xml no longer infers scalar kind from text shape, so a
        # string that looks like a number/bool round-trips as that same
        # string -- there's no more ambiguity to flag, and the write is clean.
        node = doc({"a": "123"}).to_data()
        rep = check_xml(node)
        assert list(rep) == []
        assert read_xml(write_xml(node)) == node

    def test_empty_internal_node_vs_empty_string_leaf(self):
        # An internal node with zero edges ([]) and a leaf holding the empty
        # string ('') both serialize to the same XML element, <tag />, so
        # read_xml can't tell them apart -- see issue #68.
        empty_internal = [("A", [])]
        empty_leaf = [("A", "")]

        # Both write to the identical XML text.
        assert write_xml(empty_internal) == write_xml(empty_leaf)

        # Writing the empty internal node is the lossy direction: check_xml
        # flags it, and reading it back never reconstructs [] -- it always
        # comes back as the empty-string leaf.
        rep_internal = check_xml(empty_internal)
        assert [a.code for a in rep_internal] == ["shape.empty_ambiguous"]
        assert read_xml(write_xml(empty_internal)) == [("A", "")]
        assert read_xml(write_xml(empty_internal)) != empty_internal

        # Writing the empty-string leaf is not lossy: it round-trips fine and
        # is not flagged.
        rep_leaf = check_xml(empty_leaf)
        assert list(rep_leaf) == []
        assert read_xml(write_xml(empty_leaf)) == empty_leaf

    def test_illegal_xml_control_char_is_sanitized_and_reported(self):
        # XML 1.0 forbids most C0 control characters in character data (only
        # tab/LF/CR and U+0020+ are legal).  write_xml used to emit them
        # verbatim, producing text that read_xml's own parser then rejected
        # -- see issue #67.  It should now substitute U+FFFD and flag it.
        node = [("a", "x\x08y")]
        rep = check_xml(node)
        assert [a.code for a in rep] == ["string.illegal_xml_char"]
        assert rep.errors                      # error severity, not a warning

        text = write_xml(node)
        assert "\x08" not in text              # the illegal byte is gone
        assert "�" in text                # replaced with U+FFFD
        assert read_xml(text) == [("a", "x�y")]   # round-trips cleanly now

        with pytest.raises(WriteError) as ei:
            write_xml(node, strict=True)
        assert [a.code for a in ei.value.report] == ["string.illegal_xml_char"]

    def test_carriage_return_normalization_is_reported(self):
        # CR is legal XML, but XML's mandated line-ending normalization on
        # parse turns '\r' (and '\r\n') into '\n', so it's a documented,
        # non-error lossiness rather than a crash -- see issue #67.
        node = [("a", "x\ry")]
        rep = check_xml(node)
        assert [a.code for a in rep] == ["string.cr_normalized"]
        assert rep.warnings and not rep.errors

        text = write_xml(node)
        assert "\r" in text                    # CR is left as-is on write
        assert read_xml(text) == [("a", "x\ny")]   # but reads back as LF

    def test_label_with_trailing_newline_is_sanitized_and_reported(self):
        # A label like 'A\n' isn't a valid XML name, but the old _XML_NAME
        # regex used a bare '$' anchor, which in Python matches just before a
        # trailing '\n' as well as at the absolute end of string -- so
        # 'A\n' was treated as already-valid and wasn't flagged or
        # sanitized, even though ElementTree happily wrote a tag literally
        # containing the newline. check_xml's empty report then lied: the
        # label silently lost its trailing newline on round-trip -- see
        # issue #95. It should be sanitized and flagged like any other
        # illegal-XML-name label.
        node = [("A\n", "x")]
        rep = check_xml(node)
        assert [a.code for a in rep] == ["key.sanitized"]
        assert rep.warnings and not rep.errors

        text = write_xml(node)
        assert "\n" not in text.split(">", 1)[0]   # no raw newline in the tag
        assert read_xml(text) == [("A_", "x")]   # round-trips via sanitized name

    def test_embedded_newline_label_is_sanitized_and_reported(self):
        # Same bug class as above, but with the newline in the middle of the
        # label rather than at the very end.
        node = [("A\nB", "x")]
        rep = check_xml(node)
        assert [a.code for a in rep] == ["key.sanitized"]

        text = write_xml(node)
        assert read_xml(text) == [("A_B", "x")]


# ----------------------------------------------------------- TOML write errors
class TestTomlWriteErrors:
    def test_non_object_root_raises(self):
        with pytest.raises(WriteError, match="top-level table"):
            write_toml("bare leaf")
