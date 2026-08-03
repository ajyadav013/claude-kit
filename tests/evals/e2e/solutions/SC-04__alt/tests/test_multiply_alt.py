import pytest

from calc import multiply


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(3, 4, 12), (-2, 5, -10), (0, 9, 0), (7, 1, 7)],
)
def test_multiply_table(a, b, expected):
    assert multiply(a, b) == expected
