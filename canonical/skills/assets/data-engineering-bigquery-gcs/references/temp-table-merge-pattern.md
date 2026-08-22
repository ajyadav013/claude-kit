# Temp Table + MERGE Pattern

Atomic upsert pattern for BigQuery: Load to temp table → MERGE to main → cleanup temp.

## Overview

The temp table + MERGE pattern is used for incremental data sync jobs where:
- Source data may contain both new records and updates to existing records
- You need atomic upserts (insert new rows, update existing rows based on a key)
- You want to avoid race conditions by isolating staging from production
- You need to track the last successful sync timestamp for incremental processing

## Pattern Steps

1. **Load from source to temp table** — GCS → BigQuery temp table with `WRITE_TRUNCATE`
2. **MERGE temp to main** — Atomic upsert based on primary key and timestamp
3. **Track sync metadata** — Extract MAX(timestamp) from temp table for next sync
4. **Cleanup temp** — `TRUNCATE` or `DROP` the temp table

## Why This Pattern

**Atomicity**: MERGE is a single atomic operation; either all rows succeed or none do.

**Isolation**: Temp table isolates staging from production; concurrent queries on main table are unaffected during load.

**Idempotency**: If the MERGE fails, you can retry without duplicating data (key-based upsert).

**Performance**: Bulk load to temp is faster than row-by-row inserts; MERGE is optimized for batch operations.

**Audit trail**: Tracking MAX(timestamp) enables incremental sync (only fetch new/changed rows from source).

## Example Pattern

**Real-world orchestration flow:**
```python
last_sync = timeConfig.get(f"{collection}_last_sync_time") or datetime(2024, 7, 1, tzinfo=timezone.utc)

# Step 1: Export from Mongo to GCS
gcs_pattern = export_to_gcs_json(MONGO_URI, DATABASE_NAME, collection, GCS_BUCKET,
                                 m.gcs_path, last_sync, m.schema_as_bq(), m.time_key)

# Step 2: Load GCS → BigQuery temp table
load_json_to_temp_table(gcs_pattern, m.bq_temp_table, m.schema_as_bq(), BQ_PROJECT, BQ_DATASET, GCS_BUCKET)

# Step 3: MERGE temp to main (returns new last_sync_time)
updated_sync = merge_temp_to_main(m.bq_table, m.bq_temp_table, "_id", m.schema_as_bq(),
                                  m.time_key, BQ_PROJECT, BQ_DATASET)
if updated_sync:
    timeConfig[f"{collection}_last_sync_time"] = updated_sync
    updated = True

# Step 4: Cleanup
clear_temp_table(m.bq_temp_table, BQ_PROJECT, BQ_DATASET, action="truncate")
delete_gcs_files(GCS_BUCKET, gcs_pattern)
```

## Implementation Details

### Step 1: Load to Temp Table

```python
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, SourceFormat

def load_to_temp(gcs_uri, project, dataset, temp_table, schema):
    client = bigquery.Client(project=project)
    
    job_config = LoadJobConfig(
        source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
        write_disposition="WRITE_TRUNCATE",  # Clear temp table on each load
        ignore_unknown_values=True,  # Tolerate schema evolution
    )
    
    table_ref = f"{project}.{dataset}.{temp_table}"
    load_job = client.load_table_from_uri(
        gcs_uri, table_ref, job_config=job_config, job_id_prefix=f"sync_{temp_table}_"
    )
    load_job.result()  # Wait for completion
```

**Key config options**:
- `WRITE_TRUNCATE`: Overwrite temp table (not append) for clean staging
- `ignore_unknown_values=True`: If source schema evolves, extra fields are dropped instead of failing
- `job_id_prefix`: Helps identify load jobs in BigQuery console

### Step 2: MERGE Temp to Main

```python
def merge_temp_to_main(project, dataset, main_table, temp_table, key_column, time_key):
    client = bigquery.Client(project=project)
    
    # Generate MERGE SQL
    merge_sql = f"""
    MERGE `{project}.{dataset}.{main_table}` T
    USING `{project}.{dataset}.{temp_table}` S
    ON T.{key_column} = S.{key_column}
    WHEN MATCHED AND S.{time_key} > T.{time_key} THEN
      UPDATE SET *  -- Update all columns (or specify explicit SET clauses)
    WHEN NOT MATCHED THEN
      INSERT *  -- Insert all columns (or specify explicit column list)
    """
    
    client.query(merge_sql).result()
```

**MERGE clauses**:
- `ON T.{key_column} = S.{key_column}`: Primary key match condition
- `WHEN MATCHED AND S.{time_key} > T.{time_key}`: Only update if source is newer (prevents stale updates)
- `WHEN NOT MATCHED THEN INSERT`: Insert new rows

**Alternative: Explicit column lists:**
```python
cols = ["order_id", "total_amount", "updated_at"]
updates = ", ".join([f"{c} = S.{c}" for c in cols if c != key_column])
inserts = ", ".join(cols)
values = ", ".join([f"S.{c}" for c in cols])

merge_sql = f"""
MERGE `{project}.{dataset}.{main_table}` T
USING `{project}.{dataset}.{temp_table}` S
ON T.{key_column} = S.{key_column}
WHEN MATCHED AND S.{time_key} > T.{time_key} THEN UPDATE SET {updates}
WHEN NOT MATCHED THEN INSERT ({inserts}) VALUES ({values})
"""
```

This gives finer control (e.g., exclude audit columns from updates).

### Step 3: Track Last Sync Time

```python
def get_last_sync_time(project, dataset, temp_table, time_key):
    client = bigquery.Client(project=project)
    
    query = f"SELECT MAX({time_key}) as last_sync_time FROM `{project}.{dataset}.{temp_table}`"
    result = client.query(query).result()
    
    for row in result:
        return row.last_sync_time
    
    return None
```

**Why track MAX(timestamp)**:
- Next sync only fetches rows where `source_timestamp > last_sync_time`
- Enables incremental processing (don't re-fetch all historical data)
- Stored in a config table, GCS file, or database for persistence

### Step 4: Cleanup Temp Table

```python
def cleanup_temp(project, dataset, temp_table, action="truncate"):
    client = bigquery.Client(project=project)
    
    if action == "truncate":
        client.query(f"TRUNCATE TABLE `{project}.{dataset}.{temp_table}`").result()
    elif action == "drop":
        client.query(f"DROP TABLE `{project}.{dataset}.{temp_table}`").result()
```

**TRUNCATE vs DROP**:
- `TRUNCATE`: Keep table structure, delete all rows (fast, no schema recreation needed)
- `DROP`: Delete table entirely (use if temp table schema changes frequently)

## End-to-End Example

```python
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, SourceFormat
from datetime import datetime

def sync_mongo_to_bigquery(
    gcs_uri,
    project,
    dataset,
    main_table,
    temp_table,
    schema,
    key_column="_id",
    time_key="updated_at"
):
    client = bigquery.Client(project=project)
    
    # 1. Load GCS → temp table
    job_config = LoadJobConfig(
        source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
        write_disposition="WRITE_TRUNCATE",
        ignore_unknown_values=True,
    )
    
    temp_ref = f"{project}.{dataset}.{temp_table}"
    load_job = client.load_table_from_uri(gcs_uri, temp_ref, job_config=job_config)
    load_job.result()
    print(f"✓ Loaded {load_job.output_rows} rows to {temp_table}")
    
    # 2. MERGE temp → main
    merge_sql = f"""
    MERGE `{project}.{dataset}.{main_table}` T
    USING `{project}.{dataset}.{temp_table}` S
    ON T.{key_column} = S.{key_column}
    WHEN MATCHED AND S.{time_key} > T.{time_key} THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """
    client.query(merge_sql).result()
    print(f"✓ MERGE completed for {main_table}")
    
    # 3. Get last sync time
    result = client.query(f"SELECT MAX({time_key}) as t FROM `{temp_ref}`").result()
    last_sync = [row.t for row in result][0]
    print(f"✓ Last sync time: {last_sync}")
    
    # 4. Cleanup
    client.query(f"TRUNCATE TABLE `{temp_ref}`").result()
    print(f"✓ Truncated {temp_table}")
    
    return last_sync

# Usage
last_sync_time = sync_mongo_to_bigquery(
    gcs_uri="gs://my-bucket/exports/*.json",
    project="my-project",
    dataset="my_dataset",
    main_table="orders",
    temp_table="orders_temp",
    schema=[
        bigquery.SchemaField("_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("total_amount", "FLOAT64"),
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ],
)

# Store last_sync_time for next incremental sync
```

## Anti-Patterns

- **Skipping temp table and MERGE directly to main** — No staging isolation; concurrent queries may see partial data during load.
- **Using INSERT instead of MERGE** — Duplicates data on retry; no way to update existing rows.
- **Not checking timestamp before UPDATE** — Stale data from temp can overwrite newer data in main.
- **Not cleaning up temp table** — Wasted storage; next sync may fail if schema changed.
- **Hard-coding table/project names** — Makes code non-portable across environments.

## Variations

### MERGE with DELETE

If you need to remove rows (e.g., soft-deleted in source):

```sql
MERGE `project.dataset.main_table` T
USING `project.dataset.temp_table` S
ON T.order_id = S.order_id
WHEN MATCHED AND S.deleted = TRUE THEN DELETE
WHEN MATCHED AND S.updated_at > T.updated_at THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
```

### MERGE with Conditional Insert

Only insert if certain criteria are met:

```sql
MERGE `project.dataset.main_table` T
USING `project.dataset.temp_table` S
ON T.order_id = S.order_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED AND S.status = 'completed' THEN INSERT *
```

### Persistent Temp Table

If temp table schema is stable, keep it as a persistent staging area:

```python
# First run: Create temp table
client.query(f"CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{temp_table}` AS SELECT * FROM `{project}.{dataset}.{main_table}` LIMIT 0").result()

# Each sync: TRUNCATE (not DROP), then load
client.query(f"TRUNCATE TABLE `{project}.{dataset}.{temp_table}`").result()
# ... load and MERGE as usual
```

## When to Use This Pattern

✅ **Use when**:
- Syncing data from external sources (APIs, databases, GCS) to BigQuery
- You need both inserts and updates based on a primary key
- You want atomic all-or-nothing behavior
- Source data includes a timestamp for change tracking

❌ **Don't use when**:
- Data is append-only (no updates) — just use direct `WRITE_APPEND` load
- Source has no primary key — MERGE requires a join condition
- Volume is tiny (<1000 rows) — overhead of temp table may not be worth it
- Real-time streaming — use BigQuery Streaming API or Dataflow instead

## References

- BigQuery MERGE documentation: https://cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax#merge_statement
- BigQuery load jobs: https://cloud.google.com/bigquery/docs/loading-data
