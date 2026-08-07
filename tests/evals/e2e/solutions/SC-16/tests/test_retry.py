from retry import call_with_retry


def test_first_try_success_calls_once_and_never_sleeps():
    delays = []
    calls = []

    def op():
        calls.append(1)
        return "ok"

    assert (
        call_with_retry(op, attempts=5, base_delay=1.0, retry_on=(ConnectionError,), sleep=delays.append)
        == "ok"
    )
    assert calls == [1]
    assert delays == []


def test_succeeds_on_third_attempt_with_exponential_delays():
    delays = []
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ConnectionError("down")
        return state["n"]

    assert (
        call_with_retry(flaky, attempts=4, base_delay=1.0, retry_on=(ConnectionError,), sleep=delays.append)
        == 3
    )
    assert delays == [1.0, 2.0]


def test_exhaustion_reraises_last_error_and_stops_sleeping():
    delays = []
    errors = []

    def always_down():
        e = TimeoutError("t%d" % (len(errors) + 1))
        errors.append(e)
        raise e

    try:
        call_with_retry(
            always_down, attempts=3, base_delay=1.0, retry_on=(TimeoutError,), sleep=delays.append
        )
    except TimeoutError as e:
        assert e is errors[-1]
    else:
        raise AssertionError("expected TimeoutError")
    assert len(errors) == 3
    assert delays == [1.0, 2.0]


def test_non_retryable_error_propagates_immediately():
    delays = []
    calls = []

    def bad():
        calls.append(1)
        raise ValueError("a bug, not an outage")

    try:
        call_with_retry(
            bad, attempts=5, base_delay=1.0, retry_on=(ConnectionError, TimeoutError), sleep=delays.append
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert calls == [1]
    assert delays == []
