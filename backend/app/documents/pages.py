from typing import Any

from sqlalchemy import ColumnElement, true


def page_range(source: dict[str, Any]) -> tuple[int, int] | None:
    """The pages a run was asked to read, or None for the whole document."""
    if "page_from" not in source:
        return None
    return source["page_from"], source["page_to"]


def in_page_range(column: Any, source: dict[str, Any]) -> ColumnElement[bool]:
    """Other runs may have read other pages of a long document, and this run must not use them."""
    window = page_range(source)
    return column.between(*window) if window else true()
