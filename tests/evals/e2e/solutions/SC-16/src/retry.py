"""Retry helper: call an unreliable operation with exponential backoff."""

import time


def call_with_retry(
    fn,
    *,
    attempts=3,
    base_delay=0.1,
    retry_on=(ConnectionError, TimeoutError),
    sleep=time.sleep,
):
    """Call ``fn()`` and return its result, retrying transient failures.

    ``fn`` is called at most ``attempts`` times in total. An exception is
    retried only when ``isinstance(exc, retry_on)``; anything else propagates
    immediately. Before retry number k the injected ``sleep`` is called once
    with ``base_delay * 2 ** (k - 1)`` (exponential backoff, no jitter). After
    the final failed attempt the last exception is re-raised unchanged.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(attempts):
        try:
            return fn()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (2**attempt))
    raise AssertionError("unreachable")
