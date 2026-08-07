import pytest

from retry import call_with_retry


class Flaky:
    """Callable failing a fixed number of times before succeeding."""

    def __init__(self, failures, exc=ConnectionError):
        self.failures = failures
        self.exc = exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc("failure %d" % self.calls)
        return "recovered"


def test_immediate_success_is_not_retried():
    delays = []
    op = Flaky(failures=0)
    assert (
        call_with_retry(op, attempts=9, base_delay=2.0, retry_on=(ConnectionError,), sleep=delays.append)
        == "recovered"
    )
    assert op.calls == 1
    assert delays == []


def test_recovers_after_two_failures_with_doubling_delays():
    delays = []
    op = Flaky(failures=2)
    assert (
        call_with_retry(op, attempts=5, base_delay=0.5, retry_on=(ConnectionError,), sleep=delays.append)
        == "recovered"
    )
    assert op.calls == 3
    assert delays == [0.5, 1.0]


def test_gives_up_after_total_attempts_and_reraises_last():
    delays = []
    op = Flaky(failures=99, exc=TimeoutError)
    with pytest.raises(TimeoutError):
        call_with_retry(op, attempts=4, base_delay=1.0, retry_on=(TimeoutError,), sleep=delays.append)
    assert op.calls == 4
    assert delays == [1.0, 2.0, 4.0]


def test_unlisted_exception_type_is_never_retried():
    delays = []
    op = Flaky(failures=99, exc=KeyError)
    with pytest.raises(KeyError):
        call_with_retry(
            op, attempts=6, base_delay=1.0, retry_on=(ConnectionError, TimeoutError), sleep=delays.append
        )
    assert op.calls == 1
    assert delays == []
