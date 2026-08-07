"""A paginated, filterable, sortable listing API over in-memory record dicts.

A record is a dict with exactly these fields, always present and non-None:

    {"id": int, "name": str, "category": str, "priority": int}

`list_records` applies filter -> sort -> paginate and returns an envelope dict
with exactly the keys: items, total, page, limit, has_next.
"""

RECORD_FIELDS = ("id", "name", "category", "priority")


def list_records(records, *, filters=None, sort_by=None, sort_dir="asc", page=1, limit=10):
    """Return one page of `records` after filtering and sorting.

    - filters: None or {field: required value}; entries AND together, compared
      with ==. None or {} means no filtering. Unknown field -> ValueError.
      A value that matches nothing is not an error (empty result).
    - sort_by: None (keep input order) or a record field, else ValueError.
    - sort_dir: 'asc' or 'desc' (validated even when sort_by is None), else
      ValueError. Sorting is stable in both directions.
    - page: 1-based; limit: page size. page < 1 or limit < 1 -> ValueError.
      A page past the end returns empty items, not an error.
    - Envelope: {'items', 'total', 'page', 'limit', 'has_next'} where total is
      the filtered count and has_next is True iff page * limit < total.

    Never mutates the `records` list it is given.
    """
    if sort_dir not in ("asc", "desc"):
        raise ValueError(f"sort_dir must be 'asc' or 'desc', got {sort_dir!r}")
    if sort_by is not None and sort_by not in RECORD_FIELDS:
        raise ValueError(f"unknown sort field: {sort_by!r}")
    if filters:
        for field in filters:
            if field not in RECORD_FIELDS:
                raise ValueError(f"unknown filter field: {field!r}")
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    selected = list(records)
    if filters:
        selected = [r for r in selected if all(r[f] == v for f, v in filters.items())]
    if sort_by is not None:
        selected.sort(key=lambda r: r[sort_by], reverse=(sort_dir == "desc"))

    total = len(selected)
    start = (page - 1) * limit
    return {
        "items": selected[start : start + limit],
        "total": total,
        "page": page,
        "limit": limit,
        "has_next": page * limit < total,
    }
