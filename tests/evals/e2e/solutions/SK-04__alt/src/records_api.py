"""records_api -- a filter/sort/page pipeline over in-memory record dicts.

Built from small composable helpers: validation, predicate matching, stable
ordering, and slicing are each their own step, composed by `list_records`.

Record shape (all fields required, non-None):

    {"id": int, "name": str, "category": str, "priority": int}
"""

from itertools import islice
from operator import itemgetter

RECORD_FIELDS = frozenset({"id", "name", "category", "priority"})

_SORT_DIRS = {"asc": False, "desc": True}  # sort_dir -> reverse flag


def _check(condition, message):
    """Raise ValueError(message) unless condition holds."""
    if not condition:
        raise ValueError(message)


def _validate(filters, sort_by, sort_dir, page, limit):
    _check(sort_dir in _SORT_DIRS, f"sort_dir must be one of {sorted(_SORT_DIRS)}, got {sort_dir!r}")
    _check(sort_by is None or sort_by in RECORD_FIELDS, f"unknown sort field: {sort_by!r}")
    for field in filters or {}:
        _check(field in RECORD_FIELDS, f"unknown filter field: {field!r}")
    _check(page >= 1, f"page must be >= 1, got {page}")
    _check(limit >= 1, f"limit must be >= 1, got {limit}")


def _matches(record, filters):
    """True when every filter entry compares equal on the record (AND)."""
    return all(record[field] == wanted for field, wanted in filters.items())


def _filtered(records, filters):
    """A new list of the records matching `filters` (all of them when falsy)."""
    if not filters:
        return list(records)
    return [record for record in records if _matches(record, filters)]


def _ordered(records, sort_by, sort_dir):
    """Records stably sorted by `sort_by`; input order when sort_by is None."""
    if sort_by is None:
        return records
    return sorted(records, key=itemgetter(sort_by), reverse=_SORT_DIRS[sort_dir])


def _page_of(records, page, limit):
    """The 1-based `page` of `records`, `limit` items per page."""
    start = (page - 1) * limit
    return list(islice(records, start, start + limit))


def _envelope(items, total, page, limit):
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "has_next": page * limit < total,
    }


def list_records(records, *, filters=None, sort_by=None, sort_dir="asc", page=1, limit=10):
    """Filter, then stably sort, then paginate `records`; return the envelope.

    Contract: unknown filter key / unknown sort_by / sort_dir outside
    {'asc', 'desc'} (validated even when sort_by is None) / page < 1 /
    limit < 1 all raise ValueError. A page past the end of the filtered
    result is not an error -- it yields empty items. `total` counts the
    filtered records; `has_next` is True iff page * limit < total. The
    input list is never mutated.
    """
    _validate(filters, sort_by, sort_dir, page, limit)
    matched = _filtered(records, filters)
    ordered = _ordered(matched, sort_by, sort_dir)
    return _envelope(_page_of(ordered, page, limit), len(matched), page, limit)
