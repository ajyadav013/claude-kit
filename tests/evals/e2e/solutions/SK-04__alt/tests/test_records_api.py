import copy

import pytest

from records_api import list_records

SAMPLE = [
    {"id": 1, "name": "mango", "category": "tools", "priority": 3},
    {"id": 2, "name": "apple", "category": "toys", "priority": 1},
    {"id": 3, "name": "peach", "category": "tools", "priority": 2},
    {"id": 4, "name": "banana", "category": "food", "priority": 3},
    {"id": 5, "name": "cherry", "category": "toys", "priority": 2},
    {"id": 6, "name": "grape", "category": "food", "priority": 1},
    {"id": 7, "name": "lemon", "category": "tools", "priority": 1},
    {"id": 8, "name": "fig", "category": "food", "priority": 2},
    {"id": 9, "name": "olive", "category": "toys", "priority": 3},
    {"id": 10, "name": "date", "category": "tools", "priority": 2},
    {"id": 11, "name": "kiwi", "category": "food", "priority": 1},
    {"id": 12, "name": "plum", "category": "toys", "priority": 2},
]


def page_ids(**kwargs):
    return [r["id"] for r in list_records(copy.deepcopy(SAMPLE), **kwargs)["items"]]


def test_envelope_defaults_and_keys():
    res = list_records(SAMPLE)
    assert sorted(res) == ["has_next", "items", "limit", "page", "total"]
    assert (res["total"], res["page"], res["limit"], res["has_next"]) == (12, 1, 10, True)


def test_pagination_boundaries_and_past_end():
    assert page_ids(page=2, limit=6) == [7, 8, 9, 10, 11, 12]
    assert list_records(SAMPLE, page=2, limit=6)["has_next"] is False
    assert list_records(SAMPLE, page=3, limit=6)["items"] == []
    assert list_records([], page=4)["total"] == 0


def test_filter_then_sort_then_paginate():
    res = list_records(SAMPLE, filters={"category": "tools"}, sort_by="priority", page=2, limit=2)
    assert [r["id"] for r in res["items"]] == [10, 1]
    assert res["total"] == 4 and res["has_next"] is False


def test_desc_sort_is_stable_not_reversed_asc():
    assert page_ids(sort_by="priority", sort_dir="desc", limit=12) == [
        1, 4, 9, 3, 5, 8, 10, 12, 2, 6, 7, 11,
    ]


def test_unknown_fields_and_bad_paging_raise():
    for kwargs in (
        {"filters": {"colour": "red"}},
        {"sort_by": "colour"},
        {"sort_dir": "sideways"},
        {"page": 0},
        {"limit": 0},
    ):
        with pytest.raises(ValueError):
            list_records(SAMPLE, **kwargs)


def test_input_list_untouched():
    data = copy.deepcopy(SAMPLE)
    list_records(data, sort_by="name", sort_dir="desc")
    assert data == SAMPLE
