# MongoDB Advanced Patterns

This document covers aggregation pipelines, bulk upserts, index creation, and batched pagination patterns observed in production sync pymongo DAOs.

## Aggregation pipelines

**Core pattern**

```python
from pymongo import MongoClient

mongo_client = MongoClient(MONGO_URI, maxPoolSize=100)

@classmethod
def aggregate_query(cls, collection_name, query):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    with collection.aggregate(query) as cursor:
        document_list = list(cursor)
    
    if not document_list:
        return False, None
    
    return True, document_list
```

**Key points:**
- `collection.aggregate(pipeline)` returns a **cursor**, NOT a list
- MUST use context manager (`with ... as cursor`) to ensure cursor cleanup
- Pipeline is a list of stage dicts (`$match`, `$group`, `$project`, `$sort`, `$limit`, `$unwind`, etc.)
- Boolean tuple return `(success, results)` is an anti-pattern; prefer `Optional[list[dict]]` or raise exceptions

**Common pipeline stages**

```python
# $match — filter documents (equivalent to find() filter)
{"$match": {"status": "active", "category": "fashion"}}

# $group — aggregate by field
{"$group": {
    "_id": "$category",           # Group by category field
    "count": {"$sum": 1},          # Count documents per group
    "total": {"$sum": "$amount"}   # Sum amount field per group
}}

# $project — shape output (include/exclude/compute fields)
{"$project": {
    "_id": 0,                      # Exclude _id
    "name": 1,                     # Include name
    "displayName": "$name"         # Rename field
}}

# $sort — order results
{"$sort": {"count": -1}}           # -1 = descending, 1 = ascending

# $limit — cap result count
{"$limit": 10}

# $unwind — flatten array field into separate documents
{"$unwind": "$tags"}               # Document with tags=["a", "b"] becomes two docs
```

**Example 1: Min/max aggregation**

```python
# Find min and max price across filtered documents
pipeline = [
    {"$match": {"category": "shoes", "status": "available"}},
    {"$group": {
        "_id": None,
        "minPrice": {"$min": "$fromPrice"},
        "maxPrice": {"$max": "$toPrice"}
    }},
    {"$project": {"_id": 0, "minPrice": 1, "maxPrice": 1}}
]

success, result = MongoDB.aggregate_query("products", pipeline)
if success and result:
    min_price = result[0].get("minPrice")
    max_price = result[0].get("maxPrice")
```

**Example 2: Distinct values from array field**

```python
# Get distinct values from an array field (e.g., tags, colors)
pipeline = [
    {"$match": {"category": "fashion"}},
    {"$unwind": "$colors"},                              # Flatten array
    {"$group": {
        "_id": None,
        "distinctColors": {"$addToSet": "$colors"}       # Collect unique values
    }},
    {"$sort": {"distinctColors": 1}},
    {"$project": {"_id": 0, "colors": "$distinctColors"}}
]

success, result = MongoDB.aggregate_query("products", pipeline)
if success and result:
    colors = result[0].get("colors", [])
```

**Example 3: Leaderboard (group + sort + limit)**

```python
# Top 10 categories by document count
pipeline = [
    {"$match": {"status": "active"}},
    {"$group": {"_id": "$category", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]

success, results = MongoDB.aggregate_query("items", pipeline)
if success:
    for item in results:
        category = item["_id"]
        count = item["count"]
```

## Bulk upserts

**Core pattern**

```python
from pymongo import UpdateOne

@classmethod
async def insert_bulk(cls, collection_name, write_request, *filter_columns):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    bulk_operations = []
    
    for document in write_request:
        document['updatedAt'] = datetime.datetime.utcnow()
        
        # Build match dict from filter columns
        match = {filter_col: document[filter_col] for filter_col in filter_columns}
        
        # Build update dict (exclude _id from $set)
        update_operation = UpdateOne(
            match,
            {"$set": {key: value for key, value in document.items() if key != "_id"}},
            upsert=True,
        )
        bulk_operations.append(update_operation)
    
    if bulk_operations:
        result = collection.bulk_write(bulk_operations, ordered=False)
        write_request.clear()
    
    return True
```

**Key points:**
- `UpdateOne(filter, update, upsert=True)` inserts if no match, updates if match
- `ordered=False` continues on errors (doesn't stop at first failure); use for idempotent writes
- `ordered=True` (default) stops at first error; use when order matters or to fail fast
- `match` dict constructed from `*filter_columns` variadic args (e.g., `"recordId", "mediaId"`)
- `$set` replaces all fields except `_id` (MongoDB auto-generates `_id` on insert)

**Usage example**

```python
documents = [
    {"productId": 123, "name": "Product A", "price": 100},
    {"productId": 456, "name": "Product B", "price": 200},
]

# Upsert by productId (insert if new, update if exists)
success = await MongoDB.insert_bulk("products", documents, "productId")
```

**Bulk operation variants**

```python
from pymongo import InsertOne, UpdateOne, DeleteOne, ReplaceOne

# Mix operations in a single bulk_write
bulk_ops = [
    InsertOne({"name": "New Item"}),
    UpdateOne({"_id": 123}, {"$set": {"status": "inactive"}}),
    DeleteOne({"_id": 456}),
    ReplaceOne({"_id": 789}, {"name": "Replaced", "status": "new"}),
]

collection.bulk_write(bulk_ops, ordered=False)
```

## Index creation

**Core pattern**

```python
from pymongo import IndexModel, ASCENDING, DESCENDING

@classmethod
def create_index(cls, collection_name, indexes):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    index_models = []
    
    for index_spec in indexes:
        # Handle tuple format: (fields, options)
        if isinstance(index_spec, tuple) and len(index_spec) == 2:
            fields, options = index_spec
            index_models.append(IndexModel(fields, **options))
        else:
            # Plain field list (no options)
            index_models.append(IndexModel(index_spec))
    
    collection.create_indexes(index_models)
    return True
```

**Index spec formats**

```python
from pymongo import ASCENDING, DESCENDING

# Simple index (single field)
[("email", ASCENDING)]

# Compound index (multiple fields)
[("category", ASCENDING), ("createdAt", DESCENDING)]

# Index with options (unique constraint)
([("userId", ASCENDING)], {"unique": True})

# Compound index with options (unique + sparse)
([("email", ASCENDING), ("tenantId", ASCENDING)], {"unique": True, "sparse": True})
```

**Collection and index definitions**

```python
# constants/collections.py
from pymongo import ASCENDING, DESCENDING

USERS = "users"
PRODUCTS = "products"
ORDERS = "orders"

collections = [
    {
        "name": USERS,
        "indexes": [
            [("email", ASCENDING)],
            ([("userId", ASCENDING)], {"unique": True}),
        ],
    },
    {
        "name": PRODUCTS,
        "indexes": [
            [("productId", ASCENDING)],
            [("category", ASCENDING), ("createdAt", DESCENDING)],
            [("name", ASCENDING), ("status", ASCENDING)],
        ],
    },
    {
        "name": ORDERS,
        "indexes": [
            [("orderId", ASCENDING)],
            [("userId", ASCENDING), ("createdAt", DESCENDING)],
        ],
    },
]
```

**Startup index creation**

```python
# On application startup (e.g., in main.py or startup event)
from constants.collections import collections
from config.mongo import MongoDB

for collection_spec in collections:
    MongoDB.create_index(
        collection_spec["name"],
        collection_spec["indexes"]
    )
```

**Index options**

```python
# Common options
{"unique": True}                 # Unique constraint
{"sparse": True}                 # Only index documents with the field
{"expireAfterSeconds": 3600}    # TTL index (auto-delete after 1 hour)
{"background": True}             # Create index in background (deprecated in MongoDB 4.2+)
{"name": "custom_index_name"}   # Custom index name
```

## Batched pagination

**Core pattern**

```python
@classmethod
async def get_batch(cls, collection_name, query, page_number, page_size):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    skip_count = cls.__get_pagination_skip_count(page_size, page_number)
    
    with collection.find(query, skip=skip_count, limit=page_size) as cursor:
        documents = list(cursor)
    
    return documents

@classmethod
def __get_pagination_skip_count(cls, limit, page_no):
    return max(0, (page_no - 1) * limit)
```

**Key points:**
- `skip` is **slow** for high offsets (MongoDB scans and discards skipped documents)
- For large datasets, prefer **cursor-based pagination** (filter by `_id > last_seen_id` or `timestamp > last_timestamp`)
- Always use context manager for cursor cleanup
- Combine with `sort()` for consistent ordering across batches

**Usage: batch processing**

```python
# Process all documents in batches (e.g., for data migration or sync)
total_count = MongoDB.get_count("products", filters={})
batch_size = 100
num_batches = (total_count + batch_size - 1) // batch_size  # Ceiling division

for batch_number in range(num_batches):
    documents = await MongoDB.get_batch(
        "products",
        query={},
        page_number=batch_number,
        page_size=batch_size
    )
    
    # Process batch
    for doc in documents:
        process_document(doc)
```

**Cursor-based pagination (better for large datasets)**

```python
@classmethod
def get_batch_cursor_based(cls, collection_name, last_id, page_size):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    
    query = {"_id": {"$gt": last_id}} if last_id else {}
    
    with collection.find(query).sort("_id", ASCENDING).limit(page_size) as cursor:
        documents = list(cursor)
    
    return documents

# Usage
last_id = None
while True:
    batch = MongoDB.get_batch_cursor_based("products", last_id, page_size=100)
    if not batch:
        break
    
    for doc in batch:
        process_document(doc)
    
    last_id = batch[-1]["_id"]  # Next batch starts after this ID
```

## Fetch all with pagination

**Extended pattern (sort + skip + limit)**

```python
@classmethod
def fetch_all(cls, collection_name, filter_condition, limit, page_no, sort_by=None, required_field=None):
    db = mongo_client.get_default_database()
    collection = db[collection_name]
    
    with collection.find(filter_condition, required_field) as cursor:
        cursor.sort(sort_by).limit(limit).skip(cls.__get_pagination_skip_count(limit, page_no))
        document_list = list(cursor)
    
    if not document_list:
        return False, None
    
    return True, json.loads(json_util.dumps(document_list), object_hook=json_util.object_hook)
```

**Usage**

```python
success, documents = MongoDB.fetch_all(
    "products",
    filter_condition={"status": "active"},
    limit=20,
    page_no=1,
    sort_by=[("createdAt", DESCENDING)],
    required_field={"_id": 0, "name": 1, "price": 1}  # Projection (exclude _id, include name/price)
)

if success:
    for doc in documents:
        print(doc["name"], doc["price"])
```

## Anti-patterns

1. **New client per call**: Creating `MongoClient(...)` inside a method creates a new connection pool. Reuse the module-level `mongo_client`.
2. **No context manager for cursors**: Always wrap `aggregate()` or `find()` cursors in `with` blocks to ensure cleanup.
3. **High skip offsets**: `skip=10000` scans and discards 10k documents. For large offsets, use cursor-based pagination (filter by last `_id`).
4. **Missing index on sort field**: Sorting without an index is slow. Create compound indexes for common filter+sort combinations.
5. **Boolean tuple returns**: `(success, result)` tuples are clunky. Prefer `Optional[result]` or raise exceptions for errors.
6. **Ordered bulk writes for idempotent ops**: `ordered=True` stops at first error. Use `ordered=False` for bulk upserts when order doesn't matter.

## When to use these patterns

- **Aggregation**: analytics queries (counts, sums, min/max), grouping, distinct values
- **Bulk upserts**: syncing external data sources, batch imports, periodic refreshes
- **Index creation**: on startup to ensure queries are fast; define indexes alongside collections
- **Batched pagination**: processing large collections in chunks (data migrations, exports, periodic jobs)

**Do NOT use** for:
- High-concurrency async services (use motor + async DAOs instead of sync pymongo)
- Complex domain models (consider Pydantic + beanie ODM for validation)
- Real-time analytics (aggregation pipelines can be slow; consider pre-computed summaries or caching)
