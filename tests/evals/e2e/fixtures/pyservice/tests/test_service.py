from service import handle


def test_routes_to_calc():
    assert handle("/add", {"a": "2", "b": "3"}) == (200, {"result": 5})
    assert handle("/subtract", {"a": "5", "b": "3"}) == (200, {"result": 2})


def test_unknown_route_is_404():
    status, body = handle("/nope", {})
    assert status == 404
    assert "no route" in body["error"]


def test_missing_parameters_are_400_not_a_crash():
    status, body = handle("/add", {"a": "2"})
    assert status == 400
    assert "b" in body["error"]


def test_non_integer_parameters_are_400():
    status, body = handle("/add", {"a": "two", "b": "3"})
    assert status == 400
