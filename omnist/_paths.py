"""Document paths for edges (omnist-spec E-10 / E-36, Sec8.4)."""
from __future__ import annotations

import re
from typing import Any, Iterator

# E-36: a label needs quoting when empty or when it holds ``.[]"\``, a control
# character (U+0000..U+001F), U+007F, U+0085, U+2028 or U+2029.
_NEEDS_QUOTE = re.compile('[\x00-\x1f.\\[\\]"\\\\\x7f\x85  ]')
_SHORT = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def label_segment(label: str) -> str:
    """The path segment for ``label`` (E-36): ``.label`` when bare, else
    ``["label"]`` with the pinned escapes (lowercase ``\\uXXXX``)."""
    if label and not _NEEDS_QUOTE.search(label):
        return "." + label
    out = []
    for c in label:
        if c in _SHORT:
            out.append(_SHORT[c])
        elif c < " " or c in "\x7f\x85  ":
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    return '["' + "".join(out) + '"]'


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
        seg = label_segment(label)
        yield label, child, (f"{path}{seg}[{i}]" if totals[label] > 1 else f"{path}{seg}")
