"""Document paths for edges (omnist-spec E-10 / Sec8.4)."""
from __future__ import annotations

from typing import Any, Iterator


def edge_paths(path: str, node: Any) -> Iterator[tuple[str, Any, str]]:
    """Yield ``(label, child, child_path)`` for every edge of the list node
    ``node``. The index ``[i]`` (the 0-based position among the edges with
    that label) is on EVERY edge of a label that occurs more than once in
    the node, including the first, and absent when the label occurs once."""
    totals: dict[str, int] = {}
    for label, _ in node:
        totals[label] = totals.get(label, 0) + 1
    seen: dict[str, int] = {}
    for label, child in node:
        i = seen.get(label, 0)
        seen[label] = i + 1
        yield label, child, (f"{path}.{label}[{i}]" if totals[label] > 1 else f"{path}.{label}")
