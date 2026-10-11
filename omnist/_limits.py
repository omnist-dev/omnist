"""The universal safety limits of Sec2.4 -- nesting depth, node count and
integer digits -- as a per-call setting.

A leaf module (it imports nothing from the package) so ``document``,
``formats`` and ``oml`` can all share one definition. Every reader takes
``max_depth``, ``max_nodes`` and ``max_int_digits`` keyword options, the way
it takes ``max_input_bytes`` (D-23); an unset one keeps the default below.
The options bound one read: they are not process-wide state.

Each option may be *lowered*, and raised only up to a ceiling, because the
rest of the library relies on it:

* ``max_depth`` (default and ceiling 200): the writers, ``validate`` and
  ``infer`` all enforce 200, and the parsers recurse; a document read at a
  higher depth could not be used afterwards (D-12).
* ``max_nodes`` (default 1 000 000, ceiling 10 000 000).
* ``max_int_digits`` (default and ceiling 4300) counts the **decimal digits of
  the value** (D-28), not of a hex, octal, binary or underscored spelling.
  CPython refuses to convert an integer of more than 4300 decimal digits to or
  from a string, so a limit above that could not be honoured.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_DEPTH = 200
DEFAULT_MAX_NODES = 1_000_000
DEFAULT_MAX_INT_DIGITS = 4300      # CPython's own default sys.get_int_max_str_digits()
MAX_DEPTH_CEILING = 200
MAX_NODES_CEILING = 10_000_000
MAX_INT_DIGITS_CEILING = 4300


@dataclass(frozen=True)
class Limits:
    """The three limits one read enforces."""
    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_int_digits: int = DEFAULT_MAX_INT_DIGITS
    #: ``10 ** max_int_digits``: an int is over the digit limit iff its
    #: magnitude reaches this (compared, never ``str()``-converted).
    magnitude: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "magnitude", 10 ** self.max_int_digits)


DEFAULT_LIMITS = Limits()


def _check(name: str, value: Any, ceiling: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, not {type(value).__name__}")
    if not 1 <= value <= ceiling:
        raise ValueError(f"{name} must be between 1 and {ceiling}, not {value}")


def make_limits(max_depth: Any = DEFAULT_MAX_DEPTH, max_nodes: Any = DEFAULT_MAX_NODES,
                max_int_digits: Any = DEFAULT_MAX_INT_DIGITS) -> Limits:
    """Validate the three options and return them as a :class:`Limits`.

    ``TypeError`` for a wrong type (``bool`` is not accepted as an int),
    ``ValueError`` for a value below 1 or above the option's ceiling."""
    _check("max_depth", max_depth, MAX_DEPTH_CEILING)
    _check("max_nodes", max_nodes, MAX_NODES_CEILING)
    _check("max_int_digits", max_int_digits, MAX_INT_DIGITS_CEILING)
    return Limits(max_depth, max_nodes, max_int_digits)


class OverLimitInt:
    """What a reader's integer hook returns, instead of converting, for an
    integer literal of more than ``max_int_digits`` digits: converting it
    could raise CPython's own ``ValueError``, a failure that carries no
    Document path. ``build_node`` -- or, for OML, the parser's final check --
    then refuses it at the path of the leaf that holds it (E-4a)."""
    __slots__ = ()


def int_or_over_limit(text: str, max_digits: int) -> Any:
    """The value of the base-10 integer literal ``text`` (an optional sign,
    then digits), or an :class:`OverLimitInt` when it has more than
    ``max_digits`` digits, sign excluded -- or more than CPython's own
    int-string guard allows (a process may have lowered it below this limit),
    which would otherwise be a bare ``ValueError`` with no Document path."""
    if len(text.lstrip("+-")) > max_digits:
        return OverLimitInt()
    try:
        return int(text)
    except ValueError:
        return OverLimitInt()
