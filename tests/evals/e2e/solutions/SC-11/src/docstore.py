"""Document access for a product catalogue. Query documents are built as plain dicts."""

# Suppliers live in their own collection; products reference one by id instead of
# carrying a duplicated copy of the whole record.
INDEXES = {
    "products": [("category", 1), ("active", 1), ("price", 1)],
    "suppliers": [("supplier_id", 1)],
}


def ensure_indexes(db) -> None:
    """Create the indexes every query path depends on."""
    for collection, keys in INDEXES.items():
        for key, direction in keys:
            db[collection].create_index([(key, direction)])


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
