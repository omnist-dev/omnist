"""YAML alias limits: omnist-spec v0.26.0-beta D-18, D-18a, D-19, D-20, D-22
(docs/02-document-model.md section 2.4.1, docs/formats/yaml.md).

Every boundary is tested as a pair, an input at the limit that is accepted and
one more slot that is rejected, so a ``>`` turned into ``>=``, a default that
drifts, or an off-by-one in ``S`` flips one side of a pair. The shapes mirror
the vendored vectors (test-suite/formats-yaml/alias-expansion.json) because the
pytest run does not need the submodule; a differential test against an
independent recursive implementation of the section 2.4.1 rules covers the rest.
"""
from __future__ import annotations

import time
from fractions import Fraction
from typing import Any, Optional

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from omnist import Doc, read_yaml
from omnist._yaml_alias import check_alias_limits
from omnist.cli import main
from omnist.errors import DocumentError, OmnistError, ParseError
from omnist.formats import _yaml_loader
from omnist.registry import get_format

ALIAS = "document.limit.alias-expansion"
SIZE = "document.limit.expanded-size"
SYNTAX = "parse.codec-syntax"


def outcome(text: str, **options: Any) -> Optional[tuple[str, str]]:
    """``None`` when the read succeeds, else the ``(code, path)`` it fails with."""
    try:
        read_yaml(text, **options)
    except OmnistError as exc:
        return (exc.code, exc.path)   # type: ignore[attr-defined, no-any-return]
    return None


def keys(n: int, prefix: str = "k") -> str:
    return ", ".join(f"{prefix}{i}: 1" for i in range(n))


def boundary(accept: str, reject: str, code: str = ALIAS, **options: Any) -> None:
    """``accept`` is exactly at the limit, ``reject`` exactly one slot past."""
    assert outcome(accept, **options) is None
    assert outcome(reject, **options) == (code, "$")


# --------------------------------------------------------------- D-18 ratio

class TestRatioBoundaries:
    def test_default_is_fifty_on_a_mapping_that_merges_a_block(self):
        # job: {<<: *base, script: x} writes 3 slots and materializes keys + 2:
        # E = 150 / 3 = 50 accepted, 151 / 3 = 50.33 rejected (equal accepts).
        accept = f"base: &b {{{keys(148)}}}\njob: {{<<: *b, script: x}}\n"
        reject = f"base: &b {{{keys(149)}}}\njob: {{<<: *b, script: x}}\n"
        boundary(accept, reject)

    def test_default_is_fifty_not_forty_nine_or_fifty_one(self):
        e49 = f"base: &b {{{keys(145)}}}\njob: {{<<: *b, script: x}}\n"     # 147/3 = 49
        e51 = f"base: &b {{{keys(151)}}}\njob: {{<<: *b, script: x}}\n"     # 153/3 = 51
        assert outcome(e49) is None
        assert outcome(e51) == (ALIAS, "$")

    def test_nested_anchor_fan_out(self):
        # each level has W = 1 + 4 * W(previous) over S = 5: E is 1, 4.2, 17, 68
        text = "a: &a leaf\n"
        for name, prev in (("b", "a"), ("c", "b"), ("d", "c")):
            text += f"{name}: &{name} {{p: *{prev}, q: *{prev}, r: *{prev}, s: *{prev}}}\n"
        assert outcome(text) is None
        text += "e: &e {p: *d, q: *d, r: *d, s: *d}\n"
        assert outcome(text) == (ALIAS, "$")

    def test_anchored_at_limit_and_one_past(self):
        # x has 4 scalars (W = S = 5); y: {inner: *x} has W = 6, S = 2: E = 3.
        text = "x: &x {a: 1, b: 2, c: 3, d: 4}\ny: &y {inner: *x}\ntop: *y\n"
        assert outcome(text, max_alias_expansion=3) is None
        assert outcome(text, max_alias_expansion=2) == (ALIAS, "$")

    def test_unanchored_merge_fan_in(self):
        text = f"b: &b {{{keys(10)}}}\nt: {{<<: [{', '.join(['*b'] * 10)}]}}\n"
        assert outcome(text, max_alias_expansion=5) == (ALIAS, "$")
        assert outcome(text, max_alias_expansion=51) is None   # 101 / 2 = 50.5

    def test_unanchored_sequence_is_a_candidate(self):
        # The sequence has no anchor and E = (1 + 4 * 11) / (1 + 4) = 9; the
        # root is diluted with scalars so only the sequence is over 5.
        pad = ", ".join(f"p{i}: 1" for i in range(200))
        text = f"b: &b {{{keys(10)}}}\n{pad.replace(', ', chr(10))}\nlist: [*b, *b, *b, *b]\n"
        assert outcome(text, max_alias_expansion=9) is None
        assert outcome(text, max_alias_expansion=8) == (ALIAS, "$")

    def test_root_is_a_candidate(self):
        # b (11 slots) has E = 1; the root aliases it 10 times:
        # W = 1 + 11 + 10 * 11 = 122, S = 1 + 11 + 10 = 22, E = 5.55.
        body = "".join(f"r{i}: *b\n" for i in range(10))
        text = f"b: &b {{{keys(10)}}}\n{body}"
        assert outcome(text, max_alias_expansion=6) is None
        assert outcome(text, max_alias_expansion=5) == (ALIAS, "$")

    def test_inline_merge_source_is_a_candidate(self):
        # {x1: *b, x2: *b} has W = 1 + 2 * (k + 1), S = 3.
        accept = f"b: &b {{{keys(3)}}}\nt: {{<<: {{x1: *b, x2: *b}}, z: 1}}\n"   # 9 / 3
        reject = f"b: &b {{{keys(4)}}}\nt: {{<<: {{x1: *b, x2: *b}}, z: 1}}\n"   # 11 / 3
        boundary(accept, reject, max_alias_expansion=3)

    def test_referrer_counts_the_inline_source_slots_direct_path(self):
        # z: {<<: {a: 1}, m: *b}: W = 1 + (2 - 1) + (k + 1), S = 4 (z, <<, a, m).
        # With max 3 the limit is W = 12 (k = 9) and W = 13 (k = 10) is one past:
        # an S one too small rejects the first, one too large accepts the second.
        accept = f"b: &b {{{keys(9)}}}\nz: {{<<: {{a: 1}}, m: *b}}\n"
        reject = f"b: &b {{{keys(10)}}}\nz: {{<<: {{a: 1}}, m: *b}}\n"
        boundary(accept, reject, max_alias_expansion=3)

    def test_referrer_counts_the_inline_source_slots_carrier_path(self):
        # z: {<<: [{a: 1}, *x], m: *b}: W = 1 + 1 + 1 + (k + 1), S = 4.
        accept = f"x: &x {{c: 1}}\nb: &b {{{keys(8)}}}\nz: {{<<: [{{a: 1}}, *x], m: *b}}\n"
        reject = f"x: &x {{c: 1}}\nb: &b {{{keys(9)}}}\nz: {{<<: [{{a: 1}}, *x], m: *b}}\n"
        boundary(accept, reject, max_alias_expansion=3)

    def test_anchored_member_defined_inside_a_carrier(self):
        # z: {<<: [&m {y: 2}, *m], k: *b}: W = 1 + 1 + 1 + (kb + 1), and
        # S = 4 (z, <<, y, k): the later alias *m adds no written slot.
        accept = f"b: &b {{{keys(8)}}}\nz: {{<<: [&m {{y: 2}}, *m], k: *b}}\n"   # W = 12 = 3 * 4
        reject = f"b: &b {{{keys(9)}}}\nz: {{<<: [&m {{y: 2}}, *m], k: *b}}\n"   # W = 13
        boundary(accept, reject, max_alias_expansion=3)

    def test_worked_carrier_example_is_exactly_one(self):
        # z: {<<: [{x: 1}, &m {y: 2}, *m], k: 3}: W = 5, S = 5, E = 1.00
        text = "z: {<<: [{x: 1}, &m {y: 2}, *m], k: 3}\n"
        assert outcome(text, max_alias_expansion=1) is None

    def test_single_anchored_inline_merge_source(self):
        assert outcome("z: {<<: &m {y: 2}, k: 3}\n", max_alias_expansion=1) is None

    def test_anchored_carrier_is_not_a_candidate_and_changes_no_verdict(self):
        # z: {<<: [*p, *q], m...}: W = 1 + 3 + 3 + 3 = 10, S = 1 + 1 + 3 = 5, E = 2.
        body = "p: &p {{{}}}\nq: &q {{{}}}\nz: {{<<: {}, m1: 7, m2: 8, m3: 9}}\n"
        plain = body.format(keys(3, "a"), keys(3, "b"), "[*p, *q]")
        anchored = body.format(keys(3, "a"), keys(3, "b"), "&s [*p, *q]")
        for text in (plain, anchored):
            assert outcome(text, max_alias_expansion=2) is None
            assert outcome(text, max_alias_expansion=1) == (ALIAS, "$")
        # were the carrier a candidate it would read W = 1 + 4 + 4 over S = 3
        # (E = 3): one past, W(z) = 12 over S = 5 (2.4), is rejected at 2 either way.
        one_past = body.format(keys(4, "a"), keys(4, "b"), "&s [*p, *q]")
        assert outcome(one_past, max_alias_expansion=2) == (ALIAS, "$")
        assert outcome(one_past, max_alias_expansion=3) is None

    def test_alias_to_a_sequence_in_merge_position(self):
        # s: &s [*p, *q, *p, *q] is an ordinary sequence: W = 1 + 4 * 2 = 9, S = 5.
        # z: {<<: *s, m: 3} merges the four members flattened: W = 1 + 4 + 1 = 6, S = 3: E = 2.
        text = "p: &p {a: 1}\nq: &q {b: 2}\ns: &s [*p, *q, *p, *q]\nz: {<<: *s, m: 3}\n"
        assert outcome(text, max_alias_expansion=2) is None
        assert outcome(text, max_alias_expansion=1) == (ALIAS, "$")
        # one past at max 2: drop m and the S drops by one: W = 5, S = 2: E = 2.5
        text2 = "p: &p {a: 1}\nq: &q {b: 2}\ns: &s [*p, *q, *p, *q]\nz: {<<: *s}\n"
        assert outcome(text2, max_alias_expansion=2) == (ALIAS, "$")
        assert outcome(text2, max_alias_expansion=3) is None

    def test_plain_alias_to_an_anchored_carrier_materializes_the_list(self):
        # t: *s where s was written as <<: &s [*p, *q]: 1 + W(p) + W(q) = 1 + 11 + 11.
        text = (f"p: &p {{{keys(10, 'a')}}}\nq: &q {{{keys(10, 'b')}}}\n"
                "z: {<<: &s [*p, *q]}\n" + "".join(f"t{i}: *s\n" for i in range(30)))
        # root: W = 1 + 11 + 11 + 21 + 30 * 23 = 734, S = 1 + 11 + 11 + 2 + 30 = 55:
        # E = 13.35 (z itself is 10.5, 21 over 2)
        assert outcome(text, max_alias_expansion=14) is None
        assert outcome(text, max_alias_expansion=13) == (ALIAS, "$")

    def test_alias_to_empty_sequence_and_empty_carrier_merge_nothing(self):
        assert outcome("z: {<<: [], a: 1}\n") is None
        assert outcome("s: &s []\nz: {<<: *s, a: 1}\n") is None
        assert read_yaml("z: {<<: [], a: 1}\n") == [("z", [("a", 1)])]

    def test_scalar_aliased_many_times_is_accepted(self):
        text = "c: &c 1\n" + "".join(f"k{i}: *c\n" for i in range(500))
        assert outcome(text) is None

    def test_scalars_are_never_candidates(self):
        assert outcome("a: &a 1\nb: *a\n", max_alias_expansion=1) is None


class TestFalsePositiveGuards:
    def test_hundred_services_merging_a_twenty_key_block(self):
        text = f"x-defaults: &d {{{keys(20)}}}\nservices:\n"
        text += "".join(f"  s{i}: {{<<: *d, image: i{i}}}\n" for i in range(100))
        assert outcome(text) is None

    def test_hundred_key_block_aliased_sixty_times_at_the_root_is_accepted(self):
        text = f"b: &b {{{keys(100)}}}\n" + "".join(f"r{i}: *b\n" for i in range(60))
        assert outcome(text) is None

    def test_hundred_key_block_aliased_a_hundred_times_at_the_root_is_rejected(self):
        text = f"b: &b {{{keys(100)}}}\n" + "".join(f"r{i}: *b\n" for i in range(100))
        assert outcome(text) == (ALIAS, "$")

    def test_ordinary_merge_config_reads_unchanged(self):
        text = "base: &b {a: 1, b: 2}\nx: {<<: *b, c: 3}\n"
        assert read_yaml(text) == [("base", [("a", 1), ("b", 2)]),
                                   ("x", [("a", 1), ("b", 2), ("c", 3)])]


# ---------------------------------------------------------------- D-22 size

class TestExpandedSize:
    BASE = "base: &base {k1: 1, k2: 2, k3: 3}\nt: {a: *base, b: *base, c: *base, d: *base}\n"
    # W(root) = 1 + 4 + (1 + 4 * 4) = 22

    def test_at_the_cap_accepted_one_past_rejected(self):
        assert outcome(self.BASE, max_expanded_slots=22) is None
        assert outcome(self.BASE, max_expanded_slots=21) == (SIZE, "$")

    def test_default_cap_is_one_million(self):
        # b has 49 slots; each of the `copies` mappings is 1 + 2 * 49 = 99 slots
        # (E = 33, under the ratio), so W(root) = 51 + 99 * copies.
        assert _timed_check(self._shared(10_100))[0] is None      # 999,951
        assert _timed_check(self._shared(10_102))[0] == SIZE      # 1,000,149
        # and exactly at the cap: 49 more root scalars make W(root) 1,000,000
        assert _timed_check(self._shared(10_100, 49))[0] is None
        assert _timed_check(self._shared(10_100, 50))[0] == SIZE

    @staticmethod
    def _shared(copies: int, scalars: int = 0) -> str:
        return ("".join(f"x{i}: 1\n" for i in range(scalars))
                + f"b: &b [{', '.join(['1'] * 48)}]\nl:\n"
                + "".join("  - {a: *b, c: *b}\n" for _ in range(copies)))

    def test_cap_fails_where_ratio_passes(self):
        assert outcome(self.BASE, max_alias_expansion=4, max_expanded_slots=21) == (SIZE, "$")

    def test_cap_passes_where_ratio_fails(self):
        assert outcome(self.BASE, max_alias_expansion=3, max_expanded_slots=22) == (ALIAS, "$")

    def test_both_fail_in_the_root_itself_reports_the_ratio(self):
        # the root is the candidate over both: E = 122 / 22 = 5.5, W = 122
        text = f"b: &b {{{keys(10)}}}\n" + "".join(f"r{i}: *b\n" for i in range(10))
        assert outcome(text, max_alias_expansion=5, max_expanded_slots=100) == (ALIAS, "$")
        assert outcome(text, max_alias_expansion=6, max_expanded_slots=100) == (SIZE, "$")

    def test_both_fail_reports_the_ratio(self):
        assert outcome(self.BASE, max_alias_expansion=3, max_expanded_slots=21) == (ALIAS, "$")

    def test_alias_free_document_is_exempt_however_large(self):
        text = "".join(f"k{i}: {i}\n" for i in range(7))
        assert outcome(text, max_expanded_slots=3) is None

    def test_one_alias_subjects_the_document_to_the_cap(self):
        plain = "".join(f"k{i}: {i}\n" for i in range(7))
        assert outcome(plain, max_expanded_slots=3) is None
        assert outcome("k0: &x 1\n" + plain.split("\n", 1)[1] + "k8: *x\n",
                       max_expanded_slots=3) == (SIZE, "$")

    def test_a_merge_key_without_an_alias_subjects_the_document_to_the_cap(self):
        assert outcome("t: {<<: {a: 1}}\n", max_expanded_slots=2) == (SIZE, "$")
        assert outcome("t: {<<: {a: 1}}\n", max_expanded_slots=3) is None

    def test_the_cliff_a_plain_file_over_the_cap_passes_and_one_alias_fails(self):
        # 24,000 slots against a cap of 10,000: alias-free passes; one added alias
        # subjects the very same file to the cap.
        plain = "x: 1\n" + "".join(f"k{i}: 1\n" for i in range(12_000))
        assert outcome(plain, max_expanded_slots=10_000) is None
        assert outcome(plain.replace("x: 1", "x: &x 1") + "y: *x\n",
                       max_expanded_slots=10_000) == (SIZE, "$")

    def test_a_high_ratio_ceiling_does_not_mask_a_size_failure(self):
        # E is 2,500 at most, far under the ceiling of 10,000; W is over the cap
        text = (f"b: &b [{', '.join(['1'] * 4_999)}]\nl:\n"
                + "".join("  - {a: *b}\n" for _ in range(5)))
        assert outcome(text, max_alias_expansion=10_000, max_expanded_slots=10_000) == (SIZE, "$")
        assert outcome(text, max_alias_expansion=10_000, max_expanded_slots=40_000) is None


def _compose(text: str) -> tuple[Any, bool]:
    loader = _yaml_loader(yaml)(text)
    root = loader.get_single_node()
    return root, loader.omnist_saw_alias


# --------------------------------------------------------- malformed merges

class TestMalformedMerges:
    @pytest.mark.parametrize("text, position", [
        ("a:\n  <<: 1\n", "2:7"),
        ("a:\n  <<: [1]\n", "2:8"),
        ("a:\n  <<: [[{a: 1}]]\n", "2:8"),
        ("s: &s [1, 2]\nz:\n  <<: *s\n", "1:8"),
        ("a:\n  <<:\n", "2:6"),
        ("a: {<<: [{x: 1}, 2]}\n", "1:18"),
    ])
    def test_syntax_error_at_a_line_col(self, text, position):
        with pytest.raises(ParseError) as info:
            read_yaml(text)
        assert (info.value.code, info.value.path) == (SYNTAX, position)

    def test_alias_to_sequence_of_sequences(self):
        with pytest.raises(ParseError) as info:
            read_yaml("s: &s [[{a: 1}]]\nz: {<<: *s}\n")
        assert info.value.code == SYNTAX

    def test_malformed_wins_over_a_bomb_that_precedes_it(self):
        text = "p: &p {a: 1, b: 2, c: 3}\nt: {<<: [*p, *p, *p, *p]}\nbad:\n  <<: 1\n"
        with pytest.raises(ParseError) as info:
            read_yaml(text, max_alias_expansion=2)
        assert info.value.code == SYNTAX

    def test_malformed_wins_over_a_bomb_that_follows_it(self):
        text = "bad:\n  <<: 1\np: &p {a: 1, b: 2, c: 3}\nt: {<<: [*p, *p, *p, *p]}\n"
        with pytest.raises(ParseError) as info:
            read_yaml(text, max_alias_expansion=2)
        assert info.value.code == SYNTAX

    def test_malformed_wins_over_the_size_limit(self):
        text = "p: &p {a: 1}\nq: {x: *p, y: *p}\nbad: {<<: 1}\n"
        with pytest.raises(ParseError) as info:
            read_yaml(text, max_expanded_slots=2)
        assert info.value.code == SYNTAX

    def test_first_malformed_merge_in_document_order_is_reported(self):
        with pytest.raises(ParseError) as info:
            read_yaml("a: {<<: 1}\nb: {<<: 2}\n")
        assert info.value.path == "1:9"

    def test_malformed_merge_inside_a_sequence_and_a_complex_key_walk(self):
        with pytest.raises(ParseError):
            read_yaml("l:\n  - {<<: 1}\n")

    def test_empty_merge_is_accepted(self):
        assert outcome("a: {<<: []}\n") is None


# ----------------------------------------------------------------- cycles

class TestCycles:
    @pytest.mark.parametrize("text", [
        "a: &a {<<: *a, k: 1}\n",
        "a: &a [*a]\n",
        "a: &a {x: *a}\n",
        "a: &a {x: &b {y: *a}}\n",
        "a: &a {<<: [*a], k: 1}\n",
        "a: &a [{<<: *a}]\n",
        "&a {<<: *a, k: 1}\n",
        "a: &a [*a]\nb: 1\n",
    ])
    def test_self_referential_anchor_is_rejected_with_the_alias_code(self, text):
        assert outcome(text) == (ALIAS, "$")

    def test_a_cycle_through_a_merge_source_is_rejected_before_construction(self):
        assert outcome("a: &a {k: 1, <<: {<<: *a}}\n") == (ALIAS, "$")

    def test_a_complex_key_is_counted(self):
        # a key that is itself a container is walked; PyYAML then refuses to build
        # an unhashable key, as it always did.
        with pytest.raises(OmnistError):
            read_yaml("? {a: 1}\n: 2\n")
        with pytest.raises(OmnistError):
            read_yaml("? [1, 2]\n: 2\n")

    def test_a_complex_key_alias_counts_as_an_alias(self):
        assert outcome("k: &k {a: 1}\n? *k\n: 2\n", max_alias_expansion=50) is not None


# ---------------------------------------------------------------- options

class TestOptions:
    @pytest.mark.parametrize("name, ceiling", [("max_alias_expansion", 10_000),
                                               ("max_expanded_slots", 10_000_000)])
    def test_ceiling_is_accepted_and_one_past_refused(self, name, ceiling):
        read_yaml("a: 1\n", **{name: ceiling})
        with pytest.raises(ValueError, match=name):
            read_yaml("a: 1\n", **{name: ceiling + 1})

    @pytest.mark.parametrize("name", ["max_alias_expansion", "max_expanded_slots"])
    @pytest.mark.parametrize("value", [0, -1])
    def test_non_positive_refused(self, name, value):
        with pytest.raises(ValueError, match=name):
            read_yaml("a: 1\n", **{name: value})

    @pytest.mark.parametrize("name", ["max_alias_expansion", "max_expanded_slots"])
    @pytest.mark.parametrize("value", [True, 2.5, "50", None])
    def test_wrong_type_refused(self, name, value):
        with pytest.raises(TypeError, match=name):
            read_yaml("a: 1\n", **{name: value})

    def test_one_is_the_smallest_accepted(self):
        assert read_yaml("a: 1\n", max_alias_expansion=1, max_expanded_slots=1) == [("a", 1)]

    def test_options_reach_from_yaml(self):
        text = "b: &b {a: 1, c: 2, d: 3}\nt: {<<: *b, z: 1}\n"
        assert Doc.from_yaml(text) is not None
        with pytest.raises(OmnistError) as info:
            Doc.from_yaml(text, max_alias_expansion=1)
        assert info.value.code == ALIAS      # type: ignore[attr-defined]
        with pytest.raises(OmnistError) as info:
            Doc.from_yaml(text, max_expanded_slots=3)
        assert info.value.code == SIZE       # type: ignore[attr-defined]

    def test_validation_runs_before_parsing(self):
        with pytest.raises(ValueError):
            read_yaml("a: [", max_alias_expansion=0)

    def test_bad_yaml_still_reports_syntax_with_a_position(self):
        with pytest.raises(ParseError) as info:
            read_yaml("a: [\n")
        assert info.value.code == SYNTAX


# --------------------------------------------------------- entry points

BOMB = "a: &a [1]\n" + "".join(
    f"a{i}: &a{i} [{', '.join([f'*a{i - 1}' if i > 1 else '*a'] * 4)}]\n" for i in range(1, 12))


class TestEntryPoints:
    def test_library(self):
        assert outcome(BOMB) == (ALIAS, "$")

    def test_doc_from_yaml(self):
        with pytest.raises(DocumentError) as info:
            Doc.from_yaml(BOMB)
        assert info.value.code == ALIAS

    def test_registry(self):
        with pytest.raises(DocumentError) as info:
            get_format("yaml").read(BOMB)
        assert info.value.code == ALIAS
        with pytest.raises(DocumentError):
            Doc.from_format("yaml", BOMB)

    def test_cli_convert_exit_code_message_and_json(self, tmp_path, capsys):
        p = tmp_path / "bomb.yaml"
        p.write_text(BOMB)
        assert main(["convert", str(p), "--from", "yaml", "--to", "json"]) == 2
        out, err = capsys.readouterr()
        assert out == "" and err.startswith("error: $: the expansion factor")
        assert main(["convert", str(p), "--from", "yaml", "--to", "json", "--json"]) == 2
        import json
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert [(e["path"], e["code"]) for e in payload["errors"]] == [("$", ALIAS)]

    def test_cli_size_limit_and_malformed_merge(self, tmp_path, capsys):
        import json
        size = tmp_path / "size.yaml"
        size.write_text(TestExpandedSize._shared(10_102))
        assert main(["convert", str(size), "--from", "yaml", "--to", "json", "--json"]) == 2
        assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == SIZE
        bad = tmp_path / "bad.yaml"
        bad.write_text("a:\n  <<: 1\n")
        assert main(["convert", str(bad), "--from", "yaml", "--to", "json", "--json"]) == 2
        err = json.loads(capsys.readouterr().out)["errors"][0]
        assert (err["path"], err["code"]) == ("2:7", SYNTAX)

    def test_cli_validate_json_reports_the_code(self, tmp_path, capsys):
        import json
        p = tmp_path / "bomb.yaml"
        p.write_text(BOMB)
        s = tmp_path / "s.osd"
        s.write_text("record R {\n}\nroot R\n")
        assert main(["validate", str(p), "--schema", str(s), "--from", "yaml", "--json"]) == 2
        assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == ALIAS


# ---------------------------------------------------------------- bombs

def _tower(base: int, fan: int, levels: int) -> str:
    text = f"a0: &a0 [{', '.join(['1'] * base)}]\n"
    for i in range(1, levels + 1):
        text += f"a{i}: &a{i} [{', '.join([f'*a{i - 1}'] * fan)}]\n"
    return text


def _timed_check(text: str, **options: Any) -> tuple[Optional[str], float]:
    root, saw = _compose(text)
    start = time.perf_counter()
    try:
        check_alias_limits(root, yaml.nodes, saw_alias=saw, **options)
        code = None
    except OmnistError as exc:
        code = exc.code   # type: ignore[attr-defined]
    return code, time.perf_counter() - start


class TestBombs:
    @pytest.mark.parametrize("text", [
        _tower(1, 4, 10),                  # 4^10
        _tower(1, 2, 30),                  # 2^30
        _tower(1, 2, 70),                  # 2^70: no wrapped or huge number matters
        _tower(1, 50, 4),                  # 50^4
        _tower(1, 2, 300),                 # 2^300
    ])
    def test_towers_are_rejected_by_ratio_in_milliseconds(self, text):
        code, seconds = _timed_check(text)
        assert code == ALIAS
        assert seconds < 1.0

    def test_unanchored_merge_fan_in_2000_by_2000(self):
        text = f"b: &b {{{keys(2000)}}}\nt: {{<<: [{', '.join(['*b'] * 2000)}]}}\n"
        code, seconds = _timed_check(text)
        assert code == ALIAS and seconds < 1.0

    def test_root_list_of_aliasing_mappings(self):
        text = f"b: &b [{', '.join(['1'] * 1000)}]\nl:\n" + "".join(
            "  - {k: *b}\n" for _ in range(20_000))
        code, seconds = _timed_check(text)
        assert code == ALIAS and seconds < 2.0

    def test_ten_thousand_containers_sharing_a_block_hit_the_size_cap(self):
        code, seconds = _timed_check(TestExpandedSize._shared(10_102))
        assert code == SIZE and seconds < 2.0


class TestDeepChains:
    def test_long_merge_chain_reads_without_recursion_error(self):
        # each anchor merges the previous one: W stays 2, E stays 1, depth stays 1,
        # but a recursive flatten would need a Python frame per link.
        n = 3000
        text = "a0: &a0 {k: 1}\n" + "".join(
            f"a{i}: &a{i} {{<<: *a{i - 1}}}\n" for i in range(1, n + 1))
        node = read_yaml(text)
        assert len(node) == n + 1 and node[-1] == (f"a{n}", [("k", 1)])
        assert _timed_check(text)[0] is None

    def test_long_alias_chain_is_rejected_by_ratio_not_by_recursion(self):
        text = "a0: &a0 {k: 1}\n" + "".join(
            f"a{i}: &a{i} {{k: *a{i - 1}}}\n" for i in range(1, 3000))
        assert outcome(text) == (ALIAS, "$")
        # raised to its ceiling the ratio passes (E is about 1,500): the walk
        # itself is iterative, and the construct step's own recursion limit then
        # reports the depth, as it always has
        assert _timed_check(text, max_alias_expansion=10_000,
                            max_expanded_slots=10_000_000)[0] is None
        assert outcome(text, max_alias_expansion=10_000,
                       max_expanded_slots=10_000_000) == ("document.limit.depth", "$")

    def test_deeply_nested_literal_is_still_a_depth_error(self):
        assert outcome("[" * 5000 + "]" * 5000) == ("document.limit.depth", "$")


# ------------------------------------------------- redefinition and order

class TestRedefinedAnchors:
    def test_the_latest_definition_applies(self):
        assert read_yaml("a: &x 1\nb: *x\nc: &x 2\nd: *x\n") == [
            ("a", 1), ("b", 1), ("c", 2), ("d", 2)]

    def test_redefinition_of_a_container(self):
        text = "a: &x {p: 1}\nb: {<<: *x}\nc: &x {q: 2}\nd: {<<: *x}\n"
        assert read_yaml(text)[1] == ("b", [("p", 1)])
        assert read_yaml(text)[3] == ("d", [("q", 2)])

    def test_a_redefinition_is_a_cheap_alias_check_input(self):
        text = "a: &x {p: 1}\nb: *x\nc: &x {q: 2}\nd: *x\n"
        assert outcome(text, max_alias_expansion=2) is None      # root: 9 / 7


class TestMergeOrderUnchanged:
    def test_sequence_order_without_reversal(self):
        text = ("base: &base {region: eu}\nlimits: &limits {retries: 3}\n"
                "svc: {<<: [*base, *limits], name: api}\n")
        assert read_yaml(text)[2] == ("svc", [("region", "eu"), ("retries", 3), ("name", "api")])

    def test_nested_merge_grandparent_first(self):
        text = "g: &g {a: 1}\nm: &m {<<: *g, b: 2}\nn: {<<: *m, c: 3}\n"
        assert read_yaml(text)[2] == ("n", [("a", 1), ("b", 2), ("c", 3)])

    def test_repeated_alias_contributes_once(self):
        assert read_yaml("p: &p {a: 1}\nr: {<<: [*p, *p]}\n")[1] == ("r", [("a", 1)])

    def test_local_value_wins_in_the_merged_position(self):
        assert read_yaml("d: &d {a: 1, b: 2}\ne: {<<: *d, a: 99}\n")[1] == (
            "e", [("a", 99), ("b", 2)])

    def test_the_construct_step_only_runs_after_the_check(self, monkeypatch):
        called = []
        loader_cls = _yaml_loader(yaml)
        original = loader_cls.construct_document
        monkeypatch.setattr(loader_cls, "construct_document",
                            lambda self, node: called.append(1) or original(self, node))
        assert outcome(BOMB) == (ALIAS, "$")
        assert called == []

    def test_empty_document_reads_as_none_scalar(self):
        assert read_yaml("") is None
        assert read_yaml("# nothing\n") is None
        assert read_yaml("--- 1\n") == 1

    def test_scalar_root_skips_the_walk(self):
        assert outcome("hello\n", max_alias_expansion=1, max_expanded_slots=1) is None


class TestDocExample:
    def test_the_size_example(self):
        shared = "b: &b {k1: 1, k2: 2, k3: 3}\nt: {a: *b, b: *b, c: *b, d: *b}\n"
        read_yaml(shared, max_expanded_slots=22)
        with pytest.raises(DocumentError) as info:
            read_yaml(shared, max_expanded_slots=21)
        assert info.value.code == "document.limit.expanded-size"


# --------------------------------------------- differential, spec oracle

def _oracle(root: Any) -> tuple[Optional[str], Fraction, int, bool]:
    """An independent, recursive, memoised implementation of section 2.4.1 over
    a composed node graph (small inputs only). Returns ``("syntax" | None,
    max E over candidates, W(root), has_alias_or_merge)``."""
    Scalar, Seq, Map = yaml.ScalarNode, yaml.SequenceNode, yaml.MappingNode
    merge_tag = "tag:yaml.org,2002:merge"
    memo: dict[int, tuple[int, int]] = {}
    seen: set[int] = set()
    worst = Fraction(0)
    flags = {"alias": False, "merge": False}

    def define(n: Any, carrier: bool = False) -> tuple[int, int]:
        """(W, S) of node ``n`` as defined where first seen; an alias reads memo."""
        nonlocal worst
        if isinstance(n, Scalar):
            if id(n) in seen:
                flags["alias"] = True
            seen.add(id(n))
            return (1, 1)
        if id(n) in memo:
            flags["alias"] = True
            return memo[id(n)]
        seen.add(id(n))
        w = s = 1
        if isinstance(n, Seq):
            mergew = inlines = 0
            for item in n.value:
                first = id(item) not in memo and not isinstance(item, Scalar)
                iw, is_ = define(item)
                w += iw
                s += is_ if first or isinstance(item, Scalar) else 1
                if isinstance(item, Map):
                    mergew += iw - 1
                    inlines += (is_ - 1) if first else 0
            memo[id(n)] = (w, s)
            meta[id(n)] = (mergew, inlines)
        else:
            for k, v in n.value:
                if isinstance(k, Scalar) and k.tag == merge_tag:
                    flags["merge"] = True
                    s += 1
                    if isinstance(v, Seq):
                        members = v.value
                        if id(v) in memo:
                            flags["alias"] = True
                            w += meta[id(v)][0]
                        else:
                            seen.add(id(v))
                            for member in members:
                                first = id(member) not in memo
                                mw, ms = define(member)
                                w += mw - 1
                                s += (ms - 1) if first else 0
                            # a carrier defined here: what a later `<<: *c` merges, and
                            # the list a later plain alias materializes
                            meta[id(v)] = (sum(memo[id(m)][0] - 1 for m in members), 0)
                            memo[id(v)] = (1 + sum(memo[id(m)][0] for m in members), 1)
                    else:
                        first = id(v) not in memo
                        vw, vs = define(v)
                        w += vw - 1
                        s += (vs - 1) if first else 0
                elif isinstance(v, Scalar):
                    define(v)
                    w += 1
                    s += 1
                else:
                    first = id(v) not in memo
                    vw, vs = define(v)
                    w += vw
                    s += vs if first else 1
            memo[id(n)] = (w, s)
        worst = max(worst, Fraction(w, s))
        return (w, s)

    meta: dict[int, tuple[int, int]] = {}

    def malformed(n: Any, visited: set[int]) -> bool:
        if isinstance(n, Scalar) or id(n) in visited:
            return False
        visited.add(id(n))
        if isinstance(n, Map):
            for k, v in n.value:
                if isinstance(k, Scalar) and k.tag == merge_tag:
                    if isinstance(v, Seq):
                        if any(not isinstance(m, Map) for m in v.value):
                            return True
                    elif not isinstance(v, Map):
                        return True
                if malformed(k, visited) or malformed(v, visited):
                    return True
            return False
        return any(malformed(i, visited) for i in n.value)

    if malformed(root, set()):
        return "syntax", Fraction(0), 0, False
    w, _ = define(root)
    return None, worst, w, flags["alias"] or flags["merge"]


@st.composite
def alias_docs(draw: Any) -> str:
    lines: list[str] = []
    maps: list[str] = []       # anchored mappings
    seqs: list[str] = []       # anchored sequences of mappings or scalars
    scalars: list[str] = []

    def scalar() -> str:
        if scalars and draw(st.booleans()):
            return "*" + draw(st.sampled_from(scalars))
        return str(draw(st.integers(0, 9)))

    def mapping(depth: int) -> str:
        parts = []
        for i in range(draw(st.integers(0, 4))):
            kind = draw(st.sampled_from(["scalar", "scalar", "map", "seq", "alias", "merge"]))
            if kind == "scalar":
                parts.append(f"k{i}: {scalar()}")
            elif kind == "map" and depth < 2:
                parts.append(f"k{i}: {mapping(depth + 1)}")
            elif kind == "seq" and depth < 2:
                parts.append(f"k{i}: {sequence(depth + 1)}")
            elif kind == "alias" and (maps or seqs):
                parts.append(f"k{i}: *{draw(st.sampled_from(maps + seqs))}")
            elif kind == "merge":
                parts.append(merge(depth))
        return "{" + ", ".join(parts) + "}"

    def merge(depth: int) -> str:
        shape = draw(st.sampled_from(["alias", "alias", "inline", "carrier", "acarrier",
                                      "aliasseq", "bad", "empty"]))
        if shape == "alias" and maps:
            return f"<<: *{draw(st.sampled_from(maps))}"
        if shape == "inline":
            return f"<<: {mapping(depth + 1) if depth < 2 else '{}'}"
        if shape in ("carrier", "acarrier"):
            members = []
            for _ in range(draw(st.integers(0, 3))):
                if maps and draw(st.booleans()):
                    members.append("*" + draw(st.sampled_from(maps)))
                else:
                    members.append(mapping(depth + 1) if depth < 2 else "{}")
            text = "[" + ", ".join(members) + "]"
            if shape == "acarrier":
                name = f"cr{len(seqs)}"
                seqs.append(name)
                return f"<<: &{name} {text}"
            return f"<<: {text}"
        if shape == "aliasseq" and seqs:
            return f"<<: *{draw(st.sampled_from(seqs))}"
        if shape == "bad":
            return "<<: " + draw(st.sampled_from(["1", "[1]", "[[{}]]"]))
        return "<<: []"

    def sequence(depth: int) -> str:
        items = []
        for _ in range(draw(st.integers(0, 4))):
            kind = draw(st.sampled_from(["scalar", "map", "alias"]))
            if kind == "scalar":
                items.append(scalar())
            elif kind == "map" and depth < 2:
                items.append(mapping(depth + 1))
            elif maps:
                items.append("*" + draw(st.sampled_from(maps + seqs)))
        return "[" + ", ".join(items) + "]"

    for i in range(draw(st.integers(1, 7))):
        kind = draw(st.sampled_from(["map", "map", "seq", "scalar", "plain"]))
        if kind == "map":
            lines.append(f"m{i}: &m{i} {mapping(0)}")
            maps.append(f"m{i}")
        elif kind == "seq":
            lines.append(f"s{i}: &s{i} {sequence(0)}")
            seqs.append(f"s{i}")
        elif kind == "scalar":
            lines.append(f"c{i}: &c{i} 5")
            scalars.append(f"c{i}")
        else:
            lines.append(f"u{i}: {mapping(0) if draw(st.booleans()) else sequence(0)}")
    return "\n".join(lines) + "\n"


@settings(max_examples=400, deadline=None)
@given(alias_docs(), st.sampled_from([1, 2, 3, 5, 50]), st.integers(1, 60))
def test_differential_against_the_recursive_oracle(text, max_ratio, max_slots):
    root, saw_alias = _compose(text)
    verdict, worst, w_root, subject = _oracle(root)
    if verdict == "syntax":
        expected: Optional[tuple[str, str]] = (SYNTAX, "")
    elif worst > max_ratio:
        expected = (ALIAS, "$")
    elif subject and w_root > max_slots:
        expected = (SIZE, "$")
    else:
        expected = None
    try:
        check_alias_limits(root, yaml.nodes, saw_alias=saw_alias,
                           max_alias_expansion=max_ratio, max_expanded_slots=max_slots)
        actual: Optional[tuple[str, str]] = None
    except ParseError as exc:
        actual = (exc.code or "", "")
    except DocumentError as exc:
        actual = (exc.code or "", exc.path or "")
    assert actual == expected, (text, max_ratio, max_slots, worst, w_root)
