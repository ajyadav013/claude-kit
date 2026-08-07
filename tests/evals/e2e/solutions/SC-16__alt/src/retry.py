"""Exponential-backoff retry for unreliable operations, decorator-flavoured."""

import functools
import time


def retrying(
    *, attempts=3, base_delay=0.1, retry_on=(ConnectionError, TimeoutError), sleep=time.sleep
):
    """Decorator factory: wrap a zero-argument callable in the retry policy."""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper():
            if attempts < 1:
                raise ValueError("attempts must be >= 1")
            delay = base_delay
            remaining = attempts
            while True:
                remaining -= 1
                try:
                    return fn()
                except retry_on:
                    if remaining <= 0:
                        raise
                sleep(delay)
                delay *= 2.0

        return wrapper

    return decorate


def call_with_retry(
    fn,
    *,
    attempts=3,
    base_delay=0.1,
    retry_on=(ConnectionError, TimeoutError),
    sleep=time.sleep,
):
    """Call ``fn()`` under the retry policy and return its result.

    Retries only exceptions matching ``isinstance(exc, retry_on)``, sleeping
    ``base_delay``, ``2*base_delay``, ``4*base_delay``, ... via the injected
    ``sleep`` before each retry, and re-raises the last exception unchanged
    once ``attempts`` total calls have failed. Non-retryable exceptions
    propagate immediately with no sleeping.
    """
    policy = retrying(attempts=attempts, base_delay=base_delay, retry_on=retry_on, sleep=sleep)
    return policy(fn)()
