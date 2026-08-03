"""Document access for a product catalogue. Query documents are built as plain dicts."""


def find_by_category(category: str) -> dict:
    return {"category": category}


def find_active_in_price_range(low: int, high: int) -> dict:
    return {"active": True, "price": {"$gte": low, "$lte": high}}


def product_document(sku: str, name: str, price: int) -> dict:
    """Every product carries its full supplier record inline."""
    return {
        "sku": sku,
        "name": name,
        "price": price,
        "supplier": {"name": "", "address": "", "contact": "", "terms": ""},
    }
