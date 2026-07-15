from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any


def page_params(limit: int = 100, offset: int = 0) -> dict[str, int]:
    return {"limit": max(1, int(limit)), "offset": max(0, int(offset))}


def iter_offset_pages(
    fetch_page: Callable[[int, int], dict[str, Any]],
    *,
    item_key: str,
    limit: int = 100,
    offset: int = 0,
) -> Iterator[dict[str, Any]]:
    current = max(0, int(offset))
    page_limit = max(1, int(limit))
    while True:
        page = fetch_page(page_limit, current)
        items = page.get(item_key) or []
        for item in items:
            yield item
        total = int((page.get("pagination") or {}).get("total") or page.get("total") or 0)
        current += len(items)
        if not items or current >= total:
            break
