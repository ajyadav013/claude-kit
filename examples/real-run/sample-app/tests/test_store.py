"""Unit tests for the task store domain layer."""

import pytest
from tasktracker.store import TaskStore, ValidationError


def test_add_and_get():
    store = TaskStore()
    task = store.add("write tests", priority="high")
    assert task.id == 1
    assert store.get(1).title == "write tests"
    assert store.get(1).priority == "high"


def test_add_strips_and_rejects_empty_title():
    store = TaskStore()
    assert store.add("  spaced  ").title == "spaced"
    with pytest.raises(ValidationError):
        store.add("   ")


def test_add_rejects_bad_priority():
    store = TaskStore()
    with pytest.raises(ValidationError):
        store.add("x", priority="urgent")


def test_complete_marks_done():
    store = TaskStore()
    store.add("a")
    assert store.complete(1).done is True
    assert store.get(1).done is True


def test_list_filters_by_status():
    store = TaskStore()
    store.add("a")
    store.add("b")
    store.complete(1)
    assert [t.id for t in store.list()] == [1, 2]
    assert [t.id for t in store.list(status="open")] == [2]
    assert [t.id for t in store.list(status="done")] == [1]


def test_list_rejects_unknown_status():
    store = TaskStore()
    with pytest.raises(ValidationError):
        store.list(status="archived")


def test_ids_are_sequential():
    store = TaskStore()
    ids = [store.add(f"t{i}").id for i in range(3)]
    assert ids == [1, 2, 3]
