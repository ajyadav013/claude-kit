# BigQuery and GCS Client I/O Patterns

How to initialize clients, execute queries, introspect schemas, and perform blob operations.

## BigQuery Client Initialization

```python
from google.cloud import bigquery

# Default credentials from environment (ADC)
client = bigquery.Client()

# Explicit project override
client = bigquery.Client(project="my-gcp-project")
```

**Example from medallion generator:**  
```python
self.client = bigquery.Client()
```

**Example from Streamlit app:**  
```python
client = bigquery.Client(project=project_id)
```

## Query Execution (Sync)

```python
query = "SELECT * FROM `project.dataset.table` LIMIT 10"
rows = client.query(query).result()

for row in rows:
    print(dict(row))
```

**Example:**  
```python
query = f"SELECT * FROM `{table_name}` LIMIT {limit}"
rows = self.client.query(query).result()
```

## Schema Introspection

```python
table = client.get_table("project.dataset.table")

# Access schema fields
for field in table.schema:
    print(f"{field.name} ({field.field_type}): {field.description}")

# For views, get the SQL
if table.view_query:
    print(table.view_query)
```

**Example:**  
```python
view_ref = self.client.get_table(f"{project_id}.{dataset_id}.{view_id}")
view_sql = view_ref.view_query

schema = []
for field in view_ref.schema:
    schema.append({
        "name": field.name,
        "type": field.field_type,
        "mode": field.mode,
        "description": field.description or ""
    })
```

## Dry-Run for Schema Inference

Not directly observed in production examples, but referenced in workflow documentation:

**Pattern**: Execute query with `job_config.dry_run = True` to derive schema without running the query.

**Pattern**: Derive schema via dry-run before table creation.

## Table Creation with Partitioning and Clustering

```sql
CREATE TABLE my_project.da_silver.slv_sales (
  org_id STRING NOT NULL,
  metric_date DATE NOT NULL,
  site STRING NOT NULL,
  total_amount FLOAT64,
  _ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY metric_date
CLUSTER BY org_id, site
```

**Note**: Partitioning/clustering is standard BigQuery practice for time-series multi-tenant data, derived from multi-tenancy patterns and BigQuery best practices.

## Load Job from GCS

```python
from google.cloud.bigquery import LoadJobConfig, SourceFormat

job_config = LoadJobConfig(
    source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
    schema=schema,
    write_disposition="WRITE_TRUNCATE",  # or "WRITE_APPEND"
    ignore_unknown_values=True,  # Ignore extra fields in source data
)

gcs_uri = "gs://my-bucket/data/*.json"
table_ref = "project.dataset.temp_table"

load_job = client.load_table_from_uri(
    gcs_uri, table_ref, job_config=job_config, job_id_prefix="sync_temp_"
)
load_job.result()  # Wait for completion
```

**Example:**  
```python
job_config = bigquery.LoadJobConfig(
    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    schema=schema,
    write_disposition="WRITE_TRUNCATE",
    ignore_unknown_values=True,
)

uri = f"gs://{bucket}/{gcs_pattern}"
table_ref = f"{project}.{dataset}.{bq_temp_table}"
load_job = client.load_table_from_uri(uri, table_ref, job_config=job_config,
                                      job_id_prefix=f"sync_{bq_temp_table}_")
load_job.result()
```

## Schema Building for Nested Fields

```python
from google.cloud import bigquery

def build_schema(fields):
    schema = []
    for f in fields:
        if f["type"] == "RECORD":
            schema.append(bigquery.SchemaField(
                f["name"], 
                f["type"],
                mode=f.get("mode", "NULLABLE"),
                fields=build_schema(f["fields"])  # Recursive for nested RECORD
            ))
        else:
            schema.append(bigquery.SchemaField(
                f["name"], 
                f["type"], 
                mode=f.get("mode", "NULLABLE")
            ))
    return schema

# Example usage
schema_fields = [
    {"name": "order_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "customer", "type": "RECORD", "mode": "NULLABLE", "fields": [
        {"name": "name", "type": "STRING"},
        {"name": "email", "type": "STRING"}
    ]},
    {"name": "total_amount", "type": "FLOAT64"}
]
schema = build_schema(schema_fields)
```

**Example:**  
```python
def build_schema(fields):
    schema = []
    for f in fields:
        if f["type"] == "RECORD":
            schema.append(bigquery.SchemaField(f["name"], f["type"],
                                               mode=f.get("mode", "NULLABLE"),
                                               fields=build_schema(f["fields"])))
        else:
            schema.append(bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE")))
    return schema
```

## MERGE for Upserts (Temp Table Pattern)

```python
# Step 1: Load to temp table (see Load Job from GCS above)

# Step 2: MERGE temp to main table
merge_sql = f"""
MERGE `project.dataset.main_table` T
USING `project.dataset.temp_table` S
ON T.order_id = S.order_id
WHEN MATCHED AND S.updated_at > T.updated_at THEN
  UPDATE SET total_amount = S.total_amount, updated_at = S.updated_at
WHEN NOT MATCHED THEN
  INSERT (order_id, total_amount, updated_at) 
  VALUES (S.order_id, S.total_amount, S.updated_at)
"""
client.query(merge_sql).result()

# Step 3: Get last sync time from temp table
result = client.query(
    f"SELECT MAX(updated_at) as last_sync_time FROM `project.dataset.temp_table`"
).result()
for row in result:
    last_sync_time = row.last_sync_time

# Step 4: Cleanup temp table
client.query("TRUNCATE TABLE `project.dataset.temp_table`").result()
# OR
client.query("DROP TABLE `project.dataset.temp_table`").result()
```

**Example:**  
```python
def generate_merge_sql(table, temp_table, key_column, columns, project, dataset, time_key):
    cols = [c["name"] for c in columns]
    updates = ", ".join([f"{c} = S.{c}" for c in cols if c != key_column])
    inserts = ", ".join(cols)
    values = ", ".join([f"S.{c}" for c in cols])
    return f"""
    MERGE `{project}.{dataset}.{table}` T
    USING `{project}.{dataset}.{temp_table}` S
    ON T.{key_column} = S.{key_column}
    WHEN MATCHED AND S.{time_key} > T.{time_key} THEN UPDATE SET {updates}
    WHEN NOT MATCHED THEN INSERT ({inserts}) VALUES ({values})
    """

def merge_temp_to_main(bq_table, bq_temp_table, key_column, fields, time_key, project, dataset):
    client = bigquery.Client(project=project)
    sql = generate_merge_sql(bq_table, bq_temp_table, key_column, fields, project, dataset, time_key)
    client.query(sql).result()
    
    result = client.query(f"SELECT MAX({time_key}) as last_sync_time FROM `{project}.{dataset}.{bq_temp_table}`").result()
    for row in result:
        return row.last_sync_time

def clear_temp_table(bq_temp_table, project, dataset, action="truncate"):
    client = bigquery.Client(project=project)
    if action == "truncate":
        client.query(f"TRUNCATE TABLE `{project}.{dataset}.{bq_temp_table}`").result()
    elif action == "drop":
        client.query(f"DROP TABLE `{project}.{dataset}.{bq_temp_table}`").result()
```

## GCS Client Initialization

```python
from google.cloud import storage

storage_client = storage.Client()
bucket = storage_client.bucket("my-bucket")
```

**Example:**  
```python
storage_client = storage.Client()
```

## Upload Blob from String

```python
blob = bucket.blob("path/to/file.json")
blob.upload_from_string(data=json.dumps(data), content_type="application/json")
```

**Example:**  
```python
blob = bucket.blob(destination_blob_name)
file_content = base64.b64decode(file["data"])
blob.upload_from_string(data=file_content, content_type=file["contentType"])
```

## Download Blob as Bytes

```python
blob = bucket.blob("path/to/file.csv")

if blob.exists():
    csv_bytes = blob.download_as_bytes()
    # Process csv_bytes...
else:
    print("Blob does not exist")
```

**Example:**  
```python
blob = bucket.blob(filename)
if not blob.exists():
    download_images[filename] = None
else:
    image_bytes = blob.download_as_bytes()
    download_images[filename] = base64.b64encode(image_bytes).decode('utf-8')
```

## Wildcard Patterns for Bulk Loads

Use GCS URI patterns like `gs://bucket/prefix/*.json` with BigQuery load jobs to import multiple files atomically.

**Example:**  
```python
load_json_to_temp_table(gcs_pattern, bq_temp_table, schema, project, dataset, bucket)
```

The `gcs_pattern` is a wildcard URI (e.g., `gs://bucket/path/*.json`).
