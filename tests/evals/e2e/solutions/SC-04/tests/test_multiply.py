from calc import multiply


def test_multiply_returns_the_product():
    assert multiply(3, 4) == 12


def test_multiply_handles_negative_operands():
    assert multiply(-2, 5) == -10


def test_multiply_by_zero_is_zero():
    assert multiply(0, 9) == 0
