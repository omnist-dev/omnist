"""Schema minimization: partition-refinement to the canonical minimal form.

Implements the paper's Algorithm 2 (MinimizeSA) -- the same family as DFA
minimization by partition refinement (Hopcroft/Moore-style state merging).
``normalize(s)`` returns an equivalent schema with the *fewest possible*
env records, unique up to record naming (paper Theorems 3-4; they transfer
to omnist's deterministic counting-language restriction -- see
``docs/design/model.md``).

Algorithm:

1. ``s = prune(s)`` -- mandatory first step. Two semantically-equal records
   must not be kept apart by never-emittable fields or unreachable
   records; pruning first is what makes the partition canonical (see
   ``ops/prune.py``).
2. **Initial partition**: env records grouped by ``local_signature`` (see
   ``ops/signature.py``) -- a target-blind structural key, so records that
   might turn out equivalent via differently-named ref targets still start
   in the same block.
3. **Refine**: split any block whose members disagree, for some label,
   on which *block* their same-labeled ref-typed field points to. Repeat
   until no block splits (a fixpoint -- always reached on a finite env).
   This is exactly DFA-minimization-style refinement: two states are
   equivalent iff every transition leads to equivalent states.
4. **Merge**: collapse each stable block to a single representative --
   its lexicographically smallest member name (deterministic) -- and
   remap every ref and the root to representatives.

Special case: an unsatisfiable (empty-language) root. ``prune()``
deliberately leaves such a root's fields untouched (see its docstring),
so partition refinement over the unsatisfiable core isn't meaningful --
there's no "fewest records" notion to compute when the schema accepts no
finite document at all. In that case ``normalize`` just returns the
pruned schema unchanged.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..schema import Field, Record, Ref, Scalar, Schema
from .prune import is_empty, prune
from .signature import local_signature


def normalize(s: Schema) -> Schema:
    """The canonical minimal schema equivalent to ``s``: fewest env
    records, unique up to record naming. See module docstring for the
    algorithm (paper's Algorithm 2, MinimizeSA)."""
    s = prune(s)
    if is_empty(s):
        return s

    names = sorted(s.env)
    block_of: Dict[str, int] = {}
    blocks: List[List[str]] = _group_by(names, lambda n: local_signature(s.env[n]))
    for i, block in enumerate(blocks):
        for n in block:
            block_of[n] = i

    changed = True
    while changed:
        changed = False
        new_blocks: List[List[str]] = []
        new_block_of: Dict[str, int] = {}
        for block in blocks:
            for sub in _group_by(block, lambda n: _refine_key(s.env[n], block_of)):
                idx = len(new_blocks)
                new_blocks.append(sub)
                for n in sub:
                    new_block_of[n] = idx
        if len(new_blocks) != len(blocks):
            changed = True
        blocks = new_blocks
        block_of = new_block_of

    rep: Dict[str, str] = {}
    for block in blocks:
        keep = min(block)
        for n in block:
            rep[n] = keep

    new_env: Dict[str, Record] = {}
    for name in names:
        if rep[name] == name:
            new_env[name] = _remap(s.env[name], rep)
    new_root = Ref(rep.get(s.root.name, s.root.name))
    return Schema(new_root, new_env)


def _group_by(names: List[str], key: Callable[[str], Any]) -> List[List[str]]:
    groups: Dict[Any, List[str]] = {}
    for n in names:
        groups.setdefault(key(n), []).append(n)
    return list(groups.values())


def _refine_key(rec: Record, block_of: Dict[str, int]) -> tuple[Any, tuple[Any, ...]]:
    """A record's refinement key: its target-blind local signature, plus
    -- for each field in label order -- the current block id of its ref
    target (or ``None`` for a scalar field). Two records land in the same
    refined block only if they agree on both."""
    fields = tuple(sorted(
        (
            (f.label, f.min, f.max,
             block_of[f.type.name] if isinstance(f.type, Ref) else None)
            for f in rec.fields
        ),
        key=lambda t: t[0],
    ))
    return (local_signature(rec), fields)


def _remap(rec: Record, rep: Dict[str, str]) -> Record:
    return Record([Field(f.label, _remap_type(f.type, rep), f.min, f.max)
                   for f in rec.fields])


def _remap_type(t: Ref | Scalar, rep: Dict[str, str]) -> Ref | Scalar:
    if isinstance(t, Ref):
        return Ref(rep.get(t.name, t.name))
    return t
