"""A deliberately tiny domain module for end-to-end scenario fixtures.

Independent second reference for SC-04: multiply is derived from repeated addition rather
than the `*` operator, so a discriminator pinned to one implementation shape fails here.
"""


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Return the difference of two integers."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Return the product of two integers."""
    negative = (a < 0) != (b < 0)
    total = 0
    for _ in range(abs(b)):
        total = add(total, abs(a))
    return -total if negative else total
