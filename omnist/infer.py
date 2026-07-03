"""Infer a Schema from example Documents, on the canonical model.

Given one or more sample Documents, draft a ``record`` schema that accepts
them:

* a label present in every sample with count 1 becomes a required field
  (``[1,1]``); absent in some samples -> ``[0,1]``; seen more than once ->
  an array (``[min,]``);
* scalar children become one :class:`~omnist.schema.Scalar`
  (nullable if any sample was null). Samples disagreeing on scalar shape
  raise, except ``integer``/``number`` mixing, which collapses to
  ``number`` (the one subset relation between scalars) -- see
  ``docs/design/model.md``;
* object children become a nested, named ``record`` (recursively).

Since the model has no inline records, nested records are given generated
names derived from their label.

``infer`` deliberately does **not** auto-normalize: the raw result keeps a
1:1 correspondence between sample labels and generated record names, which
is easier to read and hand-edit, and may therefore contain structurally-
identical duplicate records. Call ``.normalize()`` on the result where a
canonical minimal schema is wanted (decided in issues #143/#151).
"""

from __future__ import annotations

from typing import Any, Dict, List

from .document import Doc, build_node
from .errors import SchemaError
from .schema import Field, Record, Ref, Scalar, Schema, value_kind


def infer(samples: List[Any], root_name: str = "Root") -> Schema:
    nodes = []
    for s in samples:
        nodes.append(s._node if isinstance(s, Doc) else build_node(s))
    if not nodes:
        raise SchemaError("cannot infer a schema from zero samples")
    if any(not isinstance(n, list) for n in nodes):
        raise SchemaError("infer expects object (record) samples at the root")
    env: Dict[str, Any] = {}
    used: set[str] = set()
    _infer_record(nodes, root_name, env, used)
    return Schema(Ref(root_name), env)


def _unique(base: str, used: set[str]) -> str:
    name = _identifier(base) or "Rec"
    name = name[0].upper() + name[1:]
    cand, i = name, 2
    while cand in used:
        cand = f"{name}{i}"
        i += 1
    used.add(cand)
    return cand


def _identifier(s: str) -> str:
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in s)
    return out.lstrip("0123456789_") or out


def _infer_record(nodes: List[Any], name: str, env: Dict[str, Any],
                  used: set[str]) -> None:
    used.add(name)
    # Pass 1: which labels exist at all, in first-seen order. Pass 2: one
    # count per sample for *every* label, defaulting to 0 for samples that
    # don't have it -- regardless of which sample first introduced the
    # label. Doing this in two passes (rather than backfilling as labels
    # are discovered) keeps the result independent of sample order: a label
    # missing from an early sample but present in a later one must still
    # come out optional, not required.
    order: List[str] = []
    seen_labels: set[str] = set()
    for node in nodes:
        for label, _ in node:
            if label not in seen_labels:
                seen_labels.add(label)
                order.append(label)

    children: Dict[str, list[Any]] = {label: [] for label in order}
    per_sample_counts: Dict[str, List[int]] = {label: [] for label in order}
    for node in nodes:
        counts_here: dict[str, int] = {}
        for label, child in node:
            children[label].append(child)
            counts_here[label] = counts_here.get(label, 0) + 1
        for label in order:
            per_sample_counts[label].append(counts_here.get(label, 0))

    fields: List[Field] = []
    for label in order:
        counts = per_sample_counts[label]
        lo, hi = min(counts), max(counts)
        if hi > 1:
            cmin, cmax = 0, None      # an array: be permissive on length
        else:
            cmin, cmax = lo, 1        # 0 or 1 -> optional/required
        typ = _infer_type(children[label], label, env, used)
        fields.append(Field(label, typ, cmin, cmax))
    env[name] = Record(fields)


def _infer_type(child_nodes: List[Any], label: str, env: Dict[str, Any],
                used: set[str]) -> Any:
    is_obj = [isinstance(c, list) for c in child_nodes]
    if all(is_obj):
        rec_name = _unique(label, used)
        _infer_record(child_nodes, rec_name, env, used)
        return Ref(rec_name)
    if any(is_obj):
        raise SchemaError(
            f"label {label!r} mixes objects and values; cannot infer one type")
    # all scalars
    names: set[str] = set()
    null = False
    for v in child_nodes:
        if v is None:
            null = True
        else:
            names.add(value_kind(v))
    if "number" in names:
        names.discard("integer")          # the one subset relation
    if not names:
        return Scalar("string", nullable=null)    # no non-null sample observed
    if len(names) > 1:
        raise SchemaError(
            f"label {label!r} has values of more than one scalar "
            f"({', '.join(sorted(names))}); cannot infer one scalar type")
    return Scalar(names.pop(), nullable=null)
