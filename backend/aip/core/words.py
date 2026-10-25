"""Small helpers for the sentences the studio writes to people."""

from __future__ import annotations


def plural(n: int, noun: str, many: str | None = None) -> str:
    """'1 room', '3 rooms'; ``many`` for a plural that is not noun + s."""
    return f"{n} {noun if n == 1 else many or noun + 's'}"
