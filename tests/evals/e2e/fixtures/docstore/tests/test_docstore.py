from docstore import find_active_in_price_range, find_by_category, product_document


def test_category_filter_uses_the_category_field():
    assert find_by_category("tools") == {"category": "tools"}


def test_price_range_is_inclusive():
    q = find_active_in_price_range(100, 500)
    assert q["price"]["$gte"] == 100 and q["price"]["$lte"] == 500


def test_product_document_carries_a_sku():
    assert product_document("A-1", "Hammer", 999)["sku"] == "A-1"
