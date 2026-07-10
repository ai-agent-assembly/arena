"""FAKE fixture module — part of Arena's github-maintainer-dungeon repo tree.

Synthetic test data only, not real application code.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield successive chunks of `size` items from `iterable`."""
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk
