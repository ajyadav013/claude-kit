from inventory import needs_restock, reorder_quantity


def test_below_threshold_needs_restock():
    assert needs_restock(4, 5) is True


def test_above_threshold_does_not_need_restock():
    assert needs_restock(6, 5) is False


def test_at_threshold_needs_restock():
    # Reported by warehouse ops: an item sitting exactly on its reorder
    # threshold is never flagged, so it silently runs out.
    assert needs_restock(5, 5) is True


def test_reorder_quantity_at_threshold():
    assert reorder_quantity(5, 5) == 10


def test_reorder_quantity_is_zero_when_well_stocked():
    assert reorder_quantity(10, 5) == 0
