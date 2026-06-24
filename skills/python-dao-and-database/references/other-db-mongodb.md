# MongoDB: Static-Class DAO Pattern

Some production services use **sync pymongo** (NOT motor/beanie) with a static-class DAO pattern and dict-based data flow (Pydantic is absent).

## Architecture overview

- **Client**: module-level `MongoClient(MONGO_URI, maxPoolSize=100)` in `config/mongo.py`
- **DAO**: static class `MongoDB` with `@classmethod` methods
- **Collections**: defined in `constants/mongo_constant.py` with index specs
- **Indexes**: created on startup by looping the `collections` list and calling `MongoDB.create_index`
- **Data flow**: pure dicts (no Pydantic models)
- **BSON**: handled via `bson.json_util.dumps` / `json_util.object_hook`

## Module-level client

```python
# config/mongo.py
from pymongo import MongoClient
from config import settings

configuration = settings.Config()
mongo_client = MongoClient(configuration.MONGO_URI, maxPoolSize=100)
```

**SYNC, not async**: `pymongo.MongoClient` is blocking. This pattern does NOT use `motor` (async driver) or `beanie` (async ODM). All methods are sync except those marked `async` (which are misleading; they don't await anything async internally).

## Static-class DAO

```python
class MongoDB:
    """Class has the methods to work with mongodb."""

    @classmethod
    def fetch_one(cls, collection_name, filter_condition, required_field=None):
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        document = collection.find_one(filter_condition, required_field)
        if document is None:
            return False, None
        return True, json.loads(json_util.dumps(document), object_hook=json_util.object_hook)

    @classmethod
    async def insert_bulk(cls, collection_name, write_request, *filter_columns):
        with MongoClient(configuration.MONGO_URI) as client:  # New client per call (inefficient)
            db = client.get_default_database()
            collection = db[collection_name]
            bulk_operations = []
            for document in write_request:
                document['updatedAt'] = cls.get_current_timestamp()
                match = {filter: document[filter] for filter in filter_columns}
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

    @classmethod
    def aggregate_query(cls, collection_name, query):
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        with collection.aggregate(query) as cursor:
            document_list = list(cursor)
        if not document_list:
            return False, None
        return True, document_list

    @classmethod
    def create_index(cls, collection_name, indexes):
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        index_models = []
        for index_spec in indexes:
            if isinstance(index_spec, tuple) and len(index_spec) == 2:
                fields, options = index_spec
                index_models.append(IndexModel(fields, **options))
            else:
                index_models.append(IndexModel(index_spec))
        collection.create_indexes(index_models)
        return True

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

    @classmethod
    def get_count(cls, collection_name, filters=None):
        if not filters:
            filters = {}
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        total = collection.count_documents(filters)
        return total

    @classmethod
    def update_one(cls, collection_name, filter_data, update_data):
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        result = collection.update_one(filter=filter_data, update={"$set": update_data})
        return True

    @classmethod
    def insert_one(cls, collection_name, document):
        db = mongo_client.get_default_database()
        collection = db[collection_name]
        result = collection.insert_one(document)
        return True

    @classmethod
    def __get_pagination_skip_count(cls, limit, page_no):
        return max(0, (page_no - 1) * limit)

    @classmethod
    def get_current_timestamp(cls):
        from pytz import timezone
        ist = timezone('Asia/Kolkata')
        return datetime.datetime.now(ist)
```

## Bulk upsert pattern

The `insert_bulk` method builds a list of `UpdateOne` operations with `upsert=True`:

```python
bulk_operations = []
for document in write_request:
    document['updatedAt'] = cls.get_current_timestamp()
    match = {filter_col: document[filter_col] for filter_col in filter_columns}
    update_operation = UpdateOne(
        match,                                                      # Filter by these fields
        {"$set": {k: v for k, v in document.items() if k != "_id"}},  # Update all other fields
        upsert=True,                                                # Insert if not found
    )
    bulk_operations.append(update_operation)

collection.bulk_write(bulk_operations, ordered=False)
```

**Key techniques:**
- `ordered=False`: continue on errors (don't stop at first failure)
- `upsert=True`: insert if no match, update if match
- `match` dict: constructed from `*filter_columns` variadic args
- `$set`: replaces all fields except `_id`

## BSON serialization

```python
import json
from bson import json_util

# Serialize BSON to JSON (handles ObjectId, datetime, etc.)
document = collection.find_one({"_id": ObjectId("...")})
json_str = json_util.dumps(document)

# Deserialize JSON to BSON
document = json.loads(json_str, object_hook=json_util.object_hook)
```

`json_util.dumps` converts BSON types (ObjectId, datetime, Binary, etc.) to JSON-compatible dicts. `json_util.object_hook` reverses the process.

## Collection and index definitions

```python
# constants/mongo_constant.py
from pymongo import ASCENDING, DESCENDING

RECORDS = "records"
MEDIA = "media_items"
FASHION_EYE_IMAGES = "fashion_eye_images"

collections = [
    {
        "name": RECORDS,
        "indexes": [
            [("id", ASCENDING)],
            [("category", ASCENDING), ("id", ASCENDING), ("gender", ASCENDING)],
        ],
    },
    {
        "name": MEDIA,
        "indexes": [
            [("imageUrl", ASCENDING), ("insertDate", DESCENDING)],
            [("recordId", ASCENDING)],
        ],
    },
    {
        "name": "form_details",
        "indexes": [
            ([("formId", ASCENDING)], {"unique": True})  # Index with options (unique)
        ]
    },
]
```

**Index spec formats:**
- Simple: `[("field", ASCENDING)]`
- Compound: `[("field1", ASCENDING), ("field2", DESCENDING)]`
- With options: `([("field", ASCENDING)], {"unique": True})` (tuple of fields + options dict)

## Startup index creation

On application startup, loop the `collections` list and create indexes:

```python
from constants.mongo_constant import collections
from config.mongo import MongoDB

for col in collections:
    MongoDB.create_index(col["name"], col["indexes"])
```

This ensures indexes exist before the application serves traffic.

## Data flow (no Pydantic)

```python
# Controller
document = {
    "recordId": 12345,
    "mediaId": "abc",
    "noOfLikes": 0,
    "category": "fashion",
}
success = await MongoDB.insert_bulk("media_items", [document], "recordId", "mediaId")

# DAO
success, result = MongoDB.fetch_one("media_items", {"recordId": 12345})
if success:
    print(result["mediaId"])  # dict access, no Pydantic
```

All data is plain dicts. There are NO Pydantic models in this pattern.

## Common patterns

### Find one

```python
success, document = MongoDB.fetch_one("collection_name", {"field": "value"})
if success:
    # document is a dict
    print(document["field"])
```

### Find many with pagination

```python
success, documents = MongoDB.fetch_all(
    "collection_name",
    filter_condition={"status": "active"},
    limit=20,
    page_no=1,
    sort_by=[("created_at", DESCENDING)],
    required_field={"_id": 0, "name": 1, "email": 1}  # Projection
)
if success:
    for doc in documents:
        print(doc["name"])
```

### Aggregation pipeline

```python
pipeline = [
    {"$match": {"category": "fashion"}},
    {"$group": {"_id": "$recordId", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]
success, results = MongoDB.aggregate_query("media_items", pipeline)
if success:
    for result in results:
        print(result["_id"], result["count"])
```

### Count

```python
total = MongoDB.get_count("collection_name", filters={"status": "active"})
```

### Update one

```python
success = MongoDB.update_one(
    "collection_name",
    filter_data={"_id": ObjectId("...")},
    update_data={"status": "inactive", "updatedAt": datetime.utcnow()}
)
```

## Anti-patterns observed

1. **New client per `insert_bulk` call**: `with MongoClient(configuration.MONGO_URI) as client` creates a new connection pool for each bulk insert. Should reuse the module-level `mongo_client`.
2. **Misleading `async` keyword**: `insert_bulk` is marked `async` but performs blocking I/O (sync pymongo). Should either be truly async (motor) or drop the `async` keyword.
3. **No Pydantic validation**: dict-based flow is error-prone (typos, missing fields, wrong types). Consider adding Pydantic models for validation.
4. **Boolean tuple returns**: `(success, result)` tuples are clunky. Consider raising exceptions for errors (easier to trace) or using `Optional[result]`.

## When to use this pattern

- **Single-service MongoDB usage** (no shared DAO library)
- **CRUD-heavy, no complex domain logic** (analytics, logs, simple KV store)
- **Python 3.7+** (relies on dict insertion order)

**Do NOT use** for:
- High-concurrency async services (use motor + async DAOs)
- Complex domain models (use Pydantic + beanie ODM)
- Multi-tenant or sharded setups (need connection pooling per tenant)
