import copy

import pytest

from records_api import list_records


def make_records():
    rows = [
        (1, "mango", "tools", 3),
        (2, "apple", "toys", 1),
        (3, "peach", "tools", 2),
        (4, "banana", "food", 3),
        (5, "cherry", "toys", 2),
        (6, "grape", "food", 1),
        (7, "lemon", "tools", 1),
        (8, "fig", "food", 2),
        (9, "olive", "toys", 3),
        (10, "date", "tools", 2),
        (11, "kiwi", "food", 1),
        (12, "plum", "toys", 2),
    ]
    return [{"id": i, "name": n, "category": c, "priority": p} for i, n, c, p in rows]


def ids(res):
    return [r["id"] for r in res["items"]]


def test_default_page_envelope():
    res = list_records(make_records())
    assert set(res) == {"items", "total", "page", "limit", "has_next"}
    assert ids(res) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert res["total"] == 12 and res["page"] == 1 and res["limit"] == 10
    assert res["has_next"] is True


def test_last_page_and_out_of_range():
    data = make_records()
    assert ids(list_records(data, page=2, limit=10)) == [11, 12]
    past = list_records(data, page=99, limit=10)
    assert past == {"items": [], "total": 12, "page": 99, "limit": 10, "has_next": False}


def test_filtering_is_anded_and_counts_total():
    data = make_records()
    res = list_records(data, filters={"category": "toys", "priority": 2})
    assert ids(res) == [5, 12] and res["total"] == 2
    assert list_records(data, filters={"category": "nope"})["total"] == 0


def test_sort_is_stable_in_both_directions():
    data = make_records()
    asc = list_records(data, sort_by="priority", limit=12)
    desc = list_records(data, sort_by="priority", sort_dir="desc", limit=12)
    assert ids(asc) == [2, 6, 7, 11, 3, 5, 8, 10, 12, 1, 4, 9]
    assert ids(desc) == [1, 4, 9, 3, 5, 8, 10, 12, 2, 6, 7, 11]


def test_invalid_inputs_raise_value_error():
    data = make_records()
    for kwargs in (
        {"filters": {"color": "red"}},
        {"sort_by": "color"},
        {"sort_dir": "up"},
        {"page": 0},
        {"limit": 0},
        {"limit": -1},
    ):
        with pytest.raises(ValueError):
            list_records(data, **kwargs)


def test_does_not_mutate_input():
    data = make_records()
    before = copy.deepcopy(data)
    list_records(data, sort_by="name", sort_dir="desc", filters={"category": "food"})
    assert data == before
