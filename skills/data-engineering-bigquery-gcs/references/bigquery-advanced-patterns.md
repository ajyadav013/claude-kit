# BigQuery Advanced Patterns

Deep reference for parameterized queries, streaming inserts, DataFrame loads, dynamic schema evolution, time partitioning API, and reusable BigQueryUtils wrappers.

## Parameterized Queries

**Why**: Prevent SQL injection when incorporating user input or dynamic values. String interpolation (f-strings) is unsafe; parameterized queries are type-safe and validated by BigQuery.

**How**: Use `QueryJobConfig(query_parameters=[...])` with `@param_name` placeholders in SQL. BigQuery binds parameters at execution time.

**ScalarQueryParameter**: For single values.

```python
from google.cloud import bigquery

client = bigquery.Client(project="my-project")

# Query with scalar parameter
sql = """
SELECT order_id, total_amount
FROM `my-project.my_dataset.orders`
WHERE user_id = @user_id
  AND order_date >= @start_date
"""

job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("user_id", "STRING", "user123"),
        bigquery.ScalarQueryParameter("start_date", "DATE", "2026-01-01"),
    ]
)

rows = client.query(sql, job_config=job_config).result()
for row in rows:
    print(f"Order {row.order_id}: {row.total_amount}")
```

**ArrayQueryParameter**: For list values in `IN` clauses or `UNNEST`.

```python
# Query with array parameter
sql = """
SELECT table_name, column_name
FROM `my-project.my_dataset.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN UNNEST(@table_names)
ORDER BY table_name, ordinal_position
"""

job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ArrayQueryParameter("table_names", "STRING", ["orders", "customers", "products"]),
    ]
)

rows = client.query(sql, job_config=job_config).result()
```

**Common types**: `"STRING"`, `"INT64"`, `"FLOAT64"`, `"BOOL"`, `"DATE"`, `"DATETIME"`, `"TIMESTAMP"`, `"NUMERIC"`, `"BIGNUMERIC"`.

**When to use**:
- User input in WHERE clauses (user_id, date ranges, filters)
- Dynamic table/column names in INFORMATION_SCHEMA queries
- Any value that comes from external sources (API requests, config files)

**Anti-pattern**:

```python
# NEVER do this (SQL injection risk)
user_id = request.args.get("user_id")
sql = f"SELECT * FROM orders WHERE user_id = '{user_id}'"
rows = client.query(sql).result()
```

## Streaming Inserts

**Why**: Near-real-time row insertion without load jobs. Ideal for small batches (<1000 rows) with low latency requirements. Bypasses BigQuery's load job queue.

**How**: Use `client.insert_rows_json(table_ref, rows_batch)` to stream a list of row dicts. BigQuery validates schema and types on the fly.

**Batching**: Accumulate rows in a list and flush when batch size is reached. Use `BATCH_SIZE = 500` as a starting point; tune based on row size and latency needs.

**Error handling**: `insert_rows_json` returns a list of error dicts for failed rows. Empty list = all rows succeeded. Non-empty = partial failure; log and retry or skip.

```python
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)

client = bigquery.Client(project="my-project")
table_ref = "my-project.my_dataset.events"
BATCH_SIZE = 500

batch = []

for event_dict in event_stream:
    # Add timestamp if not present
    if "event_timestamp" not in event_dict:
        event_dict["event_timestamp"] = datetime.utcnow().isoformat()
    
    batch.append(event_dict)
    
    if len(batch) >= BATCH_SIZE:
        errors = client.insert_rows_json(table_ref, batch)
        if errors:
            logger.error(f"Streaming insert errors: {len(errors)} rows failed")
            for error in errors[:5]:  # Log first 5 errors
                logger.error(f"  {error}")
        else:
            logger.info(f"Inserted {len(batch)} rows")
        batch = []

# Flush remaining rows
if batch:
    errors = client.insert_rows_json(table_ref, batch)
    if errors:
        logger.error(f"Final batch: {len(errors)} rows failed")
```

**When to use**:
- Real-time event ingestion (clickstreams, IoT sensors, audit logs)
- Small batch sizes (<1000 rows per flush)
- Latency-sensitive use cases (data visible within seconds)

**When NOT to use**:
- Bulk loads (>10K rows) — use `load_table_from_uri` or `load_table_from_dataframe` instead (cheaper, faster for bulk)
- Historical backfills — use load jobs for better throughput and cost

**Cost note**: Streaming inserts have a per-row cost (vs. load jobs which are free). See BigQuery pricing for current rates.

## load_table_from_dataframe

**Why**: Load in-memory pandas DataFrames directly to BigQuery without intermediate GCS staging. Simplifies ETL pipelines that transform data in memory (API responses, Excel uploads, pandas processing).

**How**: Use `client.load_table_from_dataframe(df, table_fqn, job_config=LoadJobConfig(...)).result()` to upload the DataFrame as a load job. BigQuery infers schema from DataFrame dtypes.

**Schema inference**: Maps pandas dtypes to BigQuery types. Override with explicit `job_config.schema=[...]` if needed.

**Write disposition**: Always specify `WRITE_APPEND` (add to existing table) or `WRITE_TRUNCATE` (replace table contents).

```python
import pandas as pd
from google.cloud import bigquery

# In-memory DataFrame from API response or file upload
df = pd.DataFrame({
    "order_id": [1, 2, 3],
    "customer_id": ["C001", "C002", "C003"],
    "total_amount": [100.0, 200.0, 150.0],
    "order_date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
    "status": ["completed", "pending", "completed"]
})

client = bigquery.Client(project="my-project")
table_fqn = "my-project.my_dataset.orders"

job_config = bigquery.LoadJobConfig(
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND
)

load_job = client.load_table_from_dataframe(df, table_fqn, job_config=job_config)
load_job.result()  # Wait for completion

print(f"Loaded {load_job.output_rows} rows to {table_fqn}")
```

**With explicit schema**:

```python
schema = [
    bigquery.SchemaField("order_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("customer_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("total_amount", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("order_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("status", "STRING", mode="NULLABLE"),
]

job_config = bigquery.LoadJobConfig(
    schema=schema,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND
)

load_job = client.load_table_from_dataframe(df, table_fqn, job_config=job_config)
load_job.result()
```

**When to use**:
- In-memory transformations (pandas, Excel uploads, API responses)
- Data fits in memory (<1GB)
- Bypassing GCS intermediate staging for simplicity

**When NOT to use**:
- Large datasets (>1GB) — use GCS staging + `load_table_from_uri` to avoid memory exhaustion
- Data already in GCS — use `load_table_from_uri` directly

**Replaces**: The old pattern of `df.to_parquet("gs://bucket/temp.parquet")` → `load_table_from_uri("gs://bucket/temp.parquet", ...)` → cleanup. Now it's a single call.

## Dynamic Schema Evolution

**Why**: Handle evolving schemas from semi-structured sources (JSON APIs, GCS exports, user uploads) without breaking load jobs when new fields appear.

**How**: Fetch existing table schema, compare against incoming data columns, compute missing columns, append them as NULLABLE `SchemaField` objects, and update the table via `client.update_table(table, ["schema"])`.

**Constraint**: Only NULLABLE columns can be added via `update_table`. NOT NULL columns require a full table rebuild (CREATE new table, INSERT from old, DROP old, RENAME new).

```python
from google.cloud import bigquery

client = bigquery.Client(project="my-project")
table = client.get_table("my-project.my_dataset.events")

# Incoming data columns (e.g., from JSON payload)
incoming_keys = ["event_id", "user_id", "event_type", "new_field1", "new_field2"]

# Existing table columns
existing_cols = {field.name for field in table.schema}

# Compute missing columns
new_fields = [
    bigquery.SchemaField(name=key, field_type="STRING", mode="NULLABLE")
    for key in incoming_keys
    if key not in existing_cols
]

if new_fields:
    print(f"Adding {len(new_fields)} new columns: {[f.name for f in new_fields]}")
    updated_schema = list(table.schema) + new_fields
    table.schema = updated_schema
    client.update_table(table, ["schema"])
    print("Schema updated successfully")
else:
    print("No new columns to add")
```

**With type inference** (map JSON types to BigQuery types):

```python
def infer_bigquery_type(value) -> str:
    """Infer BigQuery field type from Python value."""
    if isinstance(value, bool):
        return "BOOL"
    elif isinstance(value, int):
        return "INT64"
    elif isinstance(value, float):
        return "FLOAT64"
    elif isinstance(value, (list, dict)):
        return "JSON"  # or "STRING" for serialized JSON
    else:
        return "STRING"

# Incoming JSON row
json_row = {
    "event_id": "evt123",
    "user_id": "user456",
    "event_type": "click",
    "count": 42,
    "metadata": {"key": "value"}
}

existing_cols = {field.name for field in table.schema}

new_fields = [
    bigquery.SchemaField(
        name=key,
        field_type=infer_bigquery_type(value),
        mode="NULLABLE"
    )
    for key, value in json_row.items()
    if key not in existing_cols
]

if new_fields:
    updated_schema = list(table.schema) + new_fields
    table.schema = updated_schema
    client.update_table(table, ["schema"])
```

**When to use**:
- JSON payloads from external APIs with evolving schemas
- User-uploaded files where columns change over time
- Datastream or change-data-capture sources with schema drift

**Anti-pattern**: Trying to add NOT NULL columns via `update_table`. This will fail. Either make the column NULLABLE or rebuild the table.

## TimePartitioning Python API

**Why**: Programmatically create time-partitioned tables via Python code (vs. SQLX/Dataform DDL). Partitioning reduces query costs by pruning partitions based on date filters.

**How**: Set `table.time_partitioning = bigquery.TimePartitioning(type_=TimePartitioningType.DAY, field="timestamp_column")` before calling `client.create_table(table)`.

**Common partition types**: `DAY` (most common), `HOUR`, `MONTH`, `YEAR`. Use `DAY` for time-series data unless you have specific requirements.

```python
from google.cloud import bigquery

client = bigquery.Client(project="my-project")
dataset_ref = bigquery.DatasetReference("my-project", "my_dataset")
table_ref = bigquery.TableReference(dataset_ref, "events")

schema = [
    bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event_timestamp", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("user_id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("event_type", "STRING", mode="NULLABLE"),
]

table = bigquery.Table(table_ref, schema=schema)

# Configure time partitioning
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="event_timestamp",
    expiration_ms=90 * 24 * 60 * 60 * 1000,  # Expire partitions after 90 days
)

# Optional: clustering for further query optimization
table.clustering_fields = ["user_id", "event_type"]

client.create_table(table)
print(f"Created partitioned table {table.project}.{table.dataset_id}.{table.table_id}")
```

**Partition expiration**: Use `expiration_ms` to auto-delete old partitions (e.g., 90 days for compliance/cost control). Useful for rolling retention windows.

**Clustering with partitioning**: Always partition first, then cluster. Clustering is applied within each partition. Order clustering fields by cardinality (high-cardinality first) and filter frequency.

**When to use**:
- Creating tables via Python code (not SQLX/Dataform)
- Time-series data (events, logs, metrics, transactions)
- Large tables (>1GB) where partition pruning reduces costs

**Declarative alternative**: For SQLX/Dataform, use `PARTITION BY {date_column}` in the CREATE TABLE statement. The Python API is for programmatic table creation.

## BigQueryUtils Wrapper Class

**Why**: Centralize BigQuery client initialization, common operations, error handling, and logging. Avoids repeating boilerplate across modules. Easier to mock for testing.

**How**: Define a class with `__init__(project_id)` that creates a `bigquery.Client`, and methods for common operations (query, load, insert, etc.). Each method wraps try/except for consistent error handling.

**Minimal wrapper**:

```python
from typing import Any, Dict, List
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)

class BigQueryUtils:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.client = self._initialize_client()
    
    def _initialize_client(self) -> bigquery.Client:
        """Initialize BigQuery client with error handling."""
        try:
            return bigquery.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            raise
    
    def query_data(self, query: str) -> List[Dict[str, Any]]:
        """Execute query and return results as list of dicts."""
        try:
            query_job = self.client.query(query)
            results = query_job.result()
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"BigQuery query failed: {e}")
            raise
    
    def insert_rows(self, table_fqn: str, rows: List[Dict[str, Any]]) -> None:
        """Insert rows via streaming insert with error handling."""
        try:
            errors = self.client.insert_rows_json(table_fqn, rows)
            if errors:
                logger.error(f"Streaming insert errors: {errors}")
                raise RuntimeError(f"Failed to insert {len(errors)} rows")
        except Exception as e:
            logger.error(f"BigQuery insert failed: {e}")
            raise
```

**Usage**:

```python
# Initialize once, reuse across module
bq_utils = BigQueryUtils(project_id="my-project")

# Query
rows = bq_utils.query_data("SELECT * FROM `my-project.my_dataset.my_table` LIMIT 10")
for row in rows:
    print(row)

# Insert
events = [
    {"event_id": "evt1", "event_type": "click", "timestamp": "2026-06-20T12:00:00Z"},
    {"event_id": "evt2", "event_type": "view", "timestamp": "2026-06-20T12:01:00Z"},
]
bq_utils.insert_rows("my-project.my_dataset.events", events)
```

**Extended wrapper** (with parameterized queries, DataFrame loads):

```python
from google.cloud import bigquery
import pandas as pd

class BigQueryUtils:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.client = bigquery.Client(project=self.project_id)
    
    def query_data(self, query: str, params: List[bigquery.ScalarQueryParameter] = None) -> List[Dict]:
        """Execute parameterized query."""
        job_config = None
        if params:
            job_config = bigquery.QueryJobConfig(query_parameters=params)
        
        query_job = self.client.query(query, job_config=job_config)
        return [dict(row) for row in query_job.result()]
    
    def load_dataframe(self, df: pd.DataFrame, table_fqn: str, write_disposition: str = "WRITE_APPEND") -> int:
        """Load DataFrame to BigQuery."""
        job_config = bigquery.LoadJobConfig(
            write_disposition=getattr(bigquery.WriteDisposition, write_disposition)
        )
        load_job = self.client.load_table_from_dataframe(df, table_fqn, job_config=job_config)
        load_job.result()
        return load_job.output_rows
    
    def get_table_schema(self, table_fqn: str) -> List[bigquery.SchemaField]:
        """Fetch table schema."""
        table = self.client.get_table(table_fqn)
        return table.schema
```

**When to use**:
- Multiple modules/services need BigQuery access
- Consistent error handling and logging across the codebase
- Easier mocking for unit tests (mock the wrapper instead of the client)
- Centralized configuration (retries, timeouts, default project)

**Anti-pattern**: Creating a new `bigquery.Client()` in every function. Clients are expensive to initialize; reuse via a singleton or dependency injection.

## References

- [BigQuery Python Client Library](https://cloud.google.com/python/docs/reference/bigquery/latest) — Official API reference
- [Parameterized Queries](https://cloud.google.com/bigquery/docs/parameterized-queries) — BigQuery docs
- [Streaming Inserts](https://cloud.google.com/bigquery/streaming-data-into-bigquery) — BigQuery docs
- [Partitioned Tables](https://cloud.google.com/bigquery/docs/partitioned-tables) — BigQuery docs
