"""YAML alias limits (omnist-spec D-18, D-18a, D-19, D-20, D-22; section 2.4.1).

PyYAML's composer hands back the *anchor/alias graph*: an alias resolves to the
very node object its anchor defined, so the composed graph is linear in the
input however large the expansion it describes. :func:`check_alias_limits`
walks that graph once, with every container's ``(W, S)`` memoized, **before**
anything is constructed from it, and never walks the expanded tree.

For every candidate node (every mapping, every sequence in an ordinary value
position, the root included, an inline merge source included; scalars never)
it computes ``W``, the value slots materialized, and ``S``, the value slots
written, and refuses the input with ``document.limit.alias-expansion`` when
``W / S`` exceeds the maximum:

* a container and a scalar each count one slot, a mapping key none;
* an alias counts one slot in ``S`` and the ``W`` of its target in ``W``;
* a merge key counts one slot (the ``<<`` entry) in ``S`` and contributes
  ``W - 1`` per merged mapping, whose container is flattened away;
* a sequence in merge-value position is a syntactic *carrier* (D-18a): no slot
  in either count, never a candidate, whether or not it is anchored; ``<<: *s``
  over a sequence contributes the sum of its members' ``W - 1``.

A reference to a node whose definition has not finished is a cycle (D-20) and
is refused under the same code. For an input that contains an alias or a merge
key, ``W`` of the root above the maximum expanded size is refused with
``document.limit.expanded-size`` (D-22), after every candidate has passed the
ratio check, so an input failing both reports ``alias-expansion``.

Merge shapes are validated first, in a pass of their own (D-18a): a merge value
that is not a mapping or a sequence of mappings is ``parse.codec-syntax`` and
wins over every limit code. ``<<: []`` merges nothing and is accepted.

Both passes are iterative (a deeply chained input cannot reach Python's
recursion limit). The ratio is checked as each container completes, so no
``W`` ever held exceeds ``max * S`` of the node in hand plus the one addition
in flight; Python integers do not wrap, so no saturation is needed (the
specification asks for saturating *or* arbitrary-precision counts).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .errors import DocumentError, ParseError

# Reference defaults and the ceilings an option may not exceed (D-10, D-11,
# D-22: "SHOULD NOT configure one above 10 000 000").
DEFAULT_MAX_ALIAS_EXPANSION = 50
MAX_ALIAS_EXPANSION_CEILING = 10_000
DEFAULT_MAX_EXPANDED_SLOTS = 1_000_000
MAX_EXPANDED_SLOTS_CEILING = 10_000_000

_MERGE_TAG = "tag:yaml.org,2002:merge"

# How a completed child folds into its parent.
_VALUE = 0          # an ordinary value (or complex key): w and s in full
_MERGE_MAPPING = 1  # a mapping in merge-value position: w - 1 and s - 1
_CARRIER = 2        # a sequence in merge-value position: its members' totals
_SEQ_ITEM = 3       # an item of a sequence
_ROOT = 4           # the document root


def validate_limit_options(max_alias_expansion: Any, max_expanded_slots: Any) -> None:
    """Refuse a non-integer, a non-positive or an over-ceiling maximum.

    ``TypeError`` for a wrong type (``bool`` is not accepted as an int),
    ``ValueError`` for a value outside ``1 .. ceiling``."""
    for name, value, ceiling in (
            ("max_alias_expansion", max_alias_expansion, MAX_ALIAS_EXPANSION_CEILING),
            ("max_expanded_slots", max_expanded_slots, MAX_EXPANDED_SLOTS_CEILING)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int, not {type(value).__name__}")
        if not 1 <= value <= ceiling:
            raise ValueError(f"{name} must be between 1 and {ceiling}, not {value}")


def _is_merge_key(key: Any, scalar_node: Any) -> bool:
    return isinstance(key, scalar_node) and key.tag == _MERGE_TAG


def _malformed_merge(at: Any, what: str) -> ParseError:
    mark = at.start_mark
    return ParseError(
        f"invalid YAML: a merge key's value must be a mapping or a sequence of "
        f"mappings, not {what}", code="parse.codec-syntax",
        path=f"{mark.line + 1}:{mark.column + 1}")


def validate_merge_shapes(root: Any, nodes: Any) -> None:
    """D-18a: every merge value is a mapping or a sequence of mappings.

    ``nodes`` is ``yaml.nodes`` (``yaml`` is an optional dependency, so it is
    never imported here). Reports the first malformed merge in document order;
    visits each node once, iteratively."""
    scalar_node, sequence_node = nodes.ScalarNode, nodes.SequenceNode
    mapping_node = nodes.MappingNode

    def kind(n: Any) -> str:
        return "a scalar" if isinstance(n, scalar_node) else "a sequence"

    seen = set()
    todo = [root]
    while todo:
        n = todo.pop()
        if isinstance(n, scalar_node) or id(n) in seen:
            continue
        seen.add(id(n))
        children: List[Any] = []
        if isinstance(n, mapping_node):
            for key, value in n.value:
                children.append(key)
                if _is_merge_key(key, scalar_node):
                    if isinstance(value, sequence_node):
                        for member in value.value:
                            if not isinstance(member, mapping_node):
                                raise _malformed_merge(
                                    member, f"a sequence member that is {kind(member)}")
                    elif not isinstance(value, mapping_node):
                        raise _malformed_merge(value, kind(value))
                children.append(value)
        else:
            children.extend(n.value)
        todo.extend(reversed(children))      # first in document order pops first


class _Slots:
    """A container's memoized counts; ``done`` is false while it is being walked."""
    __slots__ = ("done", "sequence", "w", "s", "merge_w", "inline_s")

    def __init__(self, sequence: bool) -> None:
        self.done = False
        self.sequence = sequence
        self.w = 0
        self.s = 0
        # Sequence only: the sum over mapping members of W - 1 (what
        # ``<<: *seq`` contributes) and over first-defined mapping members of
        # S - 1 (the written slots a carrier adds to its referrer).
        self.merge_w = 0
        self.inline_s = 0


class _Frame:
    __slots__ = ("node", "fold", "slots", "entries", "pos", "key_done", "w", "s",
                 "merge_w", "inline_s", "is_mapping")

    def __init__(self, node: Any, fold: int, slots: _Slots, is_mapping: bool) -> None:
        self.node = node
        self.fold = fold
        self.slots = slots
        self.entries = node.value
        self.is_mapping = is_mapping
        self.pos = 0
        self.key_done = False
        self.w = 1
        self.s = 1
        self.merge_w = 0
        self.inline_s = 0


def _alias_limit(message: str) -> DocumentError:
    return DocumentError(f"$: {message}", code="document.limit.alias-expansion", path="$")


def check_alias_limits(root: Any, nodes: Any, *, saw_alias: bool,
                       max_alias_expansion: int = DEFAULT_MAX_ALIAS_EXPANSION,
                       max_expanded_slots: int = DEFAULT_MAX_EXPANDED_SLOTS) -> None:
    """Enforce D-18, D-18a, D-19, D-20 and D-22 on a composed document.

    ``root`` is the composed root node and ``nodes`` is ``yaml.nodes``.
    ``saw_alias`` is whether the composer resolved any alias: PyYAML nodes do
    not record their anchors, so the composer says so (an aliased scalar is
    otherwise indistinguishable from any other). Raises ``ParseError``
    (``parse.codec-syntax``, a malformed merge) or ``DocumentError``
    (``document.limit.alias-expansion`` or ``document.limit.expanded-size``,
    path ``$``)."""
    validate_merge_shapes(root, nodes)
    scalar_node, sequence_node = nodes.ScalarNode, nodes.SequenceNode
    if isinstance(root, scalar_node):
        return
    memo: Dict[int, _Slots] = {}
    stack: List[_Frame] = []
    saw_merge = False

    def new_frame(node: Any, fold: int) -> _Frame:
        is_seq = isinstance(node, sequence_node)
        slots = _Slots(is_seq)
        memo[id(node)] = slots
        return _Frame(node, fold, slots, not is_seq)

    def fold_into(p: Any, fold: int, c: _Slots, alias: bool) -> None:
        if fold == _VALUE:
            p.w += c.w
            p.s += 1 if alias else c.s
        elif fold == _MERGE_MAPPING:
            p.w += c.w - 1
            p.s += 0 if alias else c.s - 1
        elif fold == _CARRIER:
            p.w += c.merge_w
            p.s += 0 if alias else c.inline_s
        else:   # _SEQ_ITEM: the root never folds into a parent
            p.w += c.w
            p.s += 1 if alias else c.s
            if not c.sequence:
                p.merge_w += c.w - 1
                p.inline_s += 0 if alias else c.s - 1

    def reference(parent: _Frame, n: Any, fold: int) -> Optional[_Frame]:
        """A container (or complex key) met as a child of ``parent``: first
        sight returns the frame to walk; an already-completed node is an alias,
        folded from its memo; one still being walked is a cycle (D-20)."""
        m = memo.get(id(n))
        if m is None:
            return new_frame(n, fold)
        if not m.done:
            raise _alias_limit("an anchored definition refers to itself, so its "
                               "expansion is unbounded (D-20)")
        fold_into(parent, fold, m, True)
        return None

    def step_mapping(f: _Frame) -> Optional[_Frame]:
        nonlocal saw_merge
        entries: List[Tuple[Any, Any]] = f.entries
        while f.pos < len(entries):
            key, value = entries[f.pos]
            if not f.key_done:
                f.key_done = True
                # A complex key is materialized like any value; counted so it
                # cannot hide a bomb.
                if not isinstance(key, scalar_node):
                    c = reference(f, key, _VALUE)
                    if c is not None:
                        return c
            f.pos += 1
            f.key_done = False
            c = None
            if _is_merge_key(key, scalar_node):
                saw_merge = True
                f.s += 1
                c = reference(f, value, _CARRIER if isinstance(value, sequence_node)
                              else _MERGE_MAPPING)
            elif isinstance(value, scalar_node):
                f.w += 1
                f.s += 1
            else:
                c = reference(f, value, _VALUE)
            if c is not None:
                return c
        return None

    def step_sequence(f: _Frame) -> Optional[_Frame]:
        items: List[Any] = f.entries
        while f.pos < len(items):
            item = items[f.pos]
            f.pos += 1
            if isinstance(item, scalar_node):
                f.w += 1
                f.s += 1
                continue
            c = reference(f, item, _SEQ_ITEM)
            if c is not None:
                return c
        return None

    def finish(f: _Frame) -> None:
        slots = f.slots
        slots.w, slots.s = f.w, f.s
        slots.merge_w, slots.inline_s = f.merge_w, f.inline_s
        slots.done = True
        # E = W / S above the maximum, exactly and without division (S >= 1).
        # A carrier is not a candidate (D-18a).
        if f.fold != _CARRIER and f.w > max_alias_expansion * f.s:
            raise _alias_limit(
                f"the expansion factor of a mapping or sequence exceeds the maximum "
                f"({max_alias_expansion}): it materializes {f.w} value slots from "
                f"{f.s} written")
        if f.fold == _ROOT:
            if (saw_alias or saw_merge) and f.w > max_expanded_slots:
                raise DocumentError(
                    f"$: the input expands to {f.w} value slots, over the maximum "
                    f"({max_expanded_slots})",
                    code="document.limit.expanded-size", path="$")
            return
        fold_into(stack[-1], f.fold, slots, False)

    stack.append(new_frame(root, _ROOT))
    while stack:
        f = stack[-1]
        child = step_mapping(f) if f.is_mapping else step_sequence(f)
        if child is not None:
            stack.append(child)
        else:
            stack.pop()
            finish(f)       # folds into the parent, now the top of the stack
