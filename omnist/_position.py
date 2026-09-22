"""Text positions (Sec8.4, E-11): ``line:col`` for a ``parse.*`` diagnostic.

A leaf module, like ``_encoding``, so every text surface (OML, OSD and the
four codecs) computes a position one way.
"""
from __future__ import annotations

from typing import Tuple


def line_col(text: str, offset: int) -> Tuple[int, int]:
    """The 1-based ``(line, col)`` of character ``offset`` in ``text``.

    Lines end at ``"\\n"``; columns count characters (code points) from the
    start of the line, so the first character of the text is ``(1, 1)``.
    ``offset == len(text)`` is the position just past the last character
    (where an error at end of input is reported).
    """
    line = text.count("\n", 0, offset) + 1
    col = offset - text.rfind("\n", 0, offset)
    return line, col


def position(text: str, offset: int) -> str:
    """The ``line:col`` text-position path (E-11) of character ``offset``."""
    line, col = line_col(text, offset)
    return f"{line}:{col}"
