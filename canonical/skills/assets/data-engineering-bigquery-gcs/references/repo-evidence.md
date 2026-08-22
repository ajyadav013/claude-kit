# Example Patterns

Real-world code examples illustrating conventions in the data-engineering-bigquery-gcs skill.

## Medallion Architecture

### Bronze Layer CDC Deduplication

**Example from medallion generator:**
```python
sql_query = f"""SELECT * EXCEPT(datastream_metadata)
FROM `{full_table_name}`
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY {primary_key_col}
  ORDER BY created_at DESC,
          datastream_metadata.source_timestamp DESC,
          datastream_metadata.change_sequence_number DESC
) = 1
AND datastream_metadata.change_type NOT LIKE '%DELETE%'"""
```

**Config block generation:**
```python
bronze_sql = f"""config {{
  type: "table",
  schema: "bronze",
  name: "br_{table_name}",
  tags: ["bronze", "cdc"],
  description: "{self._escape_sqlx_string(descriptions['table_description'])}",
{columns_block}
}}

{sql_query}"""
```

### Silver Layer with Bronze Dependencies

**Example config and SQL generation:**
```python
silver_sql = f"""config {{
  type: "table",
  schema: "silver",
  name: "slv_{domain}_clean",
  tags: ["silver", "daily"],
  dependencies: [{deps_str}],
  description: "{self._escape_sqlx_string(descriptions['table_description'])}",
{columns_block}
}}

{modified_sql}"""
```

**Bronze reference replacement logic:**
```python
bronze_dependencies = []
for table in analysis["source_tables"]:
    table_name = table.split('.')[-1]
    bronze_dependencies.append(f"br_{table_name}")

modified_sql = view_sql  
for table in analysis["source_tables"]:
    table_name = table.split('.')[-1]
    bronze_ref = f'${{ref("br_{table_name}")}}'
    
    if '.' in table:
        modified_sql = modified_sql.replace(f'`{table}`', bronze_ref)
        modified_sql = modified_sql.replace(table, bronze_ref)
```

### Gold Layer with Silver Dependencies

**Example config and SQL generation:**
```python
gold_sql = f"""config {{
  type: "table",
  schema: "gold",
  name: "gld_{domain}_metrics",
  tags: ["gold", "daily"],
  dependencies: ["slv_{domain}_clean"],
  description: "{self._escape_sqlx_string(descriptions['table_description'])}",
{columns_block}
}}



{select_clause}"""
```

**Aggregation logic:**
```python
if has_aggregations:
    output_columns = view_columns
    select_clause = f"""select
    *
    from ${{ref("slv_{domain}_clean")}}"""
else:
    dimensions = []
    for col in view_columns:
        col_lower = col.lower()
        if any(dim in col_lower for dim in ["_id", "_name", "_type", "_code", "_category"]):
            dimensions.append(col)
    
    if not dimensions:
        dimensions = view_columns
    
    if len(dimensions) == len(view_columns):
        select_clause = f"""select
    COUNT(*) as total_count
```

## BigQuery Client Patterns

### Client Initialization

**Example from medallion generator:**
```python
self.client = bigquery.Client()
```

**Example from Streamlit app:**
```python
client = bigquery.Client(project=project_id)
```

### Query Execution

**Example from data fetching:**
```python
def _fetch_sample_rows(self, table_name: str, limit: int) -> List[Dict]:
    """Fetch sample rows from a table."""
    if limit <= 0:
        return []
    
    query = f"SELECT * FROM `{table_name}` LIMIT {limit}"
    rows = self.client.query(query).result()
    
    return [
        {
            k: v if isinstance(v, (int, float, bool)) or v is None else str(v)
            for k, v in dict(row).items()
        }
        for row in rows
    ]
```

### Schema Introspection

**Example view definition fetch:**
```python
try:
    view_ref = self.client.get_table(f"{project_id}.{dataset_id}.{view_id}")
    view_sql = view_ref.view_query
    
    if not view_sql:
        raise ValueError(f"View {view_name} has no SQL definition")
    
    schema = []
    for field in view_ref.schema:
        schema.append({
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
            "description": field.description or ""
        })
    
    return view_sql, schema
    
except Exception as e:
    raise Exception(f"Failed to fetch view definition: {str(e)}")
```

## GCS Client Patterns

### Client Initialization and Upload

**Example from GCS utilities:**
```python
storage_client = storage.Client()

# ...

bucket = storage_client.bucket(bucket_name)
# ...
destination_blob_name = file["filename"]
blob = bucket.blob(destination_blob_name)
file_content = base64.b64decode(file["data"])
blob.upload_from_string(data=file_content, content_type=file["contentType"])
```

### Download and Existence Check

**Example blob download with existence check:**
```python
bucket = storage_client.bucket(bucket_name)
download_images = {}
for filename in filenames:
    blob = bucket.blob(filename)
    if not blob.exists():
        download_images[filename] = None
    else:
        image_bytes = blob.download_as_bytes()
        download_images[filename] = base64.b64encode(image_bytes).decode('utf-8')
```

## Temporal Orchestration

### Activity-Based I/O Rule

**From Temporal workflow documentation:**
> "It also gives a clean boundary between **API code** (which triggers workflows and returns IDs) and **worker code** (which executes activities and updates DB/GCS/externals)."

**Workflow execution pattern:**
```
4. **Workers execute workflows**
   - A worker process, started with `MODE=temporal_worker` and `WORKER_MODE=<mode>`, loads the relevant config
     from `WORKER_MODE_CONFIG_MAP` and runs a `Worker` that:
     - polls the configured task queue,
     - runs `workflow_class.run(...)` for started workflows,
```

### Parent-Child Workflow Chaining with Rollback

**Example workflow chain pattern:**
```
- Orchestrates 4 child workflows sequentially using `workflow.execute_child_workflow()`:
  1. **ManualQueryWorkflow** — register usecase, detect query type, insert query
  2. **MaterializeQueryWorkflow** — create BQ table, insert silver layer metadata, generate descriptions
  3. **SyncMetadataWorkflow** — sync descriptions to BigQuery
  4. **DataSyncWorkflow** — execute query and load data
- **Rollback**: If any child workflow fails, `rollback_by_usecase_activity` is triggered to clean up all DB records and BQ resources by `usecase_id`.
```

**Workflow architecture diagram:**
```
POST /create-query → ParentWorkflow
  try:
    ├── Child 1: ManualQueryWorkflow
    ├── Child 2: MaterializeQueryWorkflow
    ├── Child 3: SyncMetadataWorkflow
    └── Child 4: DataSyncWorkflow
  except:
    → rollback_by_usecase_activity (cleanup by usecase_id)
```

## BigQuery Load and MERGE Patterns

### LoadJobConfig with Options

**Example schema building for nested RECORD fields:**
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

**Load job with configuration:**
```python
def load_json_to_temp_table(gcs_pattern, bq_temp_table, schema_fields, project, dataset, bucket):
    client = bigquery.Client(project=project)
    schema = build_schema(schema_fields)

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
    logger.info(f"Loaded JSON into temp table: {table_ref}")
```

### MERGE Upsert Pattern

**Example MERGE implementation:**
```python
from google.cloud import bigquery
from core.logging import Logger

logger = Logger.get_logger("bigquery_merger")

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
    logger.info("MERGE completed for %s", bq_table)

    result = client.query(f"SELECT MAX({time_key}) as last_sync_time FROM `{project}.{dataset}.{bq_temp_table}`").result()
    for row in result:
        return row.last_sync_time

def clear_temp_table(bq_temp_table, project, dataset, action="truncate"):
    client = bigquery.Client(project=project)
    if action == "truncate":
        client.query(f"TRUNCATE TABLE `{project}.{dataset}.{bq_temp_table}`").result()
        logger.info(f"Truncated temp table: {bq_temp_table}")
    elif action == "drop":
        client.query(f"DROP TABLE `{project}.{dataset}.{bq_temp_table}`").result()
        logger.info(f"Dropped temp table: {bq_temp_table}")
```

## ETL Pipeline Example

### Mongo → GCS → BigQuery Sync

**Example ETL pipeline orchestration:**
```python
def process_all_collections(settings, mappings, timeConfig):
    MONGO_URI, DATABASE_NAME = settings.mongo_uri, settings.mongo_collecion
    BQ_PROJECT, BQ_DATASET, GCS_BUCKET = settings.bq_project, settings.bq_dataset, settings.gcp_bucket
    updated = False

    for m in mappings:
        collection = m.mongo_db
        logger.info(f"Processing {DATABASE_NAME}.{collection}")

        last_sync = timeConfig.get(f"{collection}_last_sync_time") or datetime(2024, 7, 1, tzinfo=timezone.utc)
        gcs_pattern = export_to_gcs_json(MONGO_URI, DATABASE_NAME, collection, GCS_BUCKET,
                                         m.gcs_path, last_sync, m.schema_as_bq(), m.time_key)

        if not gcs_pattern:
            continue

        load_json_to_temp_table(gcs_pattern, m.bq_temp_table, m.schema_as_bq(), BQ_PROJECT, BQ_DATASET, GCS_BUCKET)
        updated_sync = merge_temp_to_main(m.bq_table, m.bq_temp_table, "_id", m.schema_as_bq(),
                                          m.time_key, BQ_PROJECT, BQ_DATASET)
        if updated_sync:
            timeConfig[f"{collection}_last_sync_time"] = updated_sync
            updated = True

        clear_temp_table(m.bq_temp_table, BQ_PROJECT, BQ_DATASET, action="truncate")
        delete_gcs_files(GCS_BUCKET, gcs_pattern)
```

**Overall pattern**: Export MongoDB → GCS JSON → BigQuery temp table → MERGE to main table → cleanup temp + GCS files.

## Vertex AI LLM for Descriptions

**Example description generation with LLM:**
```python
prompt = {
    "table": table,
    "layer": "bronze",
    "columns": columns_info,
    "sample_rows": sample_rows,
    "instructions": (
        "Generate STRICT JSON only.\n"
        "Keys:\n"
        '  - "table_description": short business description (1 sentence)\n'
        '  - "columns": OBJECT where keys are column names and values are descriptions\n'
        "Make descriptions business-focused and clear.\n"
        "Do not return a list. Do not add extra text."
    ),
}

response = generate_json_text(
    user_prompt=json.dumps(prompt),
    personas=[PERSONA_DATA_ANALYST],
    task_instruction="Generate production-grade BigQuery Bronze layer documentation.",
    model=VERTEX_MODEL,
    project_id=VERTEX_PROJECT_ID,
    location=VERTEX_LOCATION     
)
docs = json.loads(response)
```

**Environment variables:**
```python
VERTEX_MODEL = os.environ.get("VERTEX_MODEL", "gemini-2.5-flash").strip()
VERTEX_PROJECT_ID = (
    os.environ.get("VERTEX_PROJECT_ID")
    or os.environ.get("BQ_PROJECT_ID")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or ""
).strip()
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1").strip()
```

## Multi-Tenancy org_id Pattern

**Pattern**: Every Silver and Gold table includes `org_id STRING NOT NULL`, partitioned by `metric_date`, clustered by `org_id, site, ...`.

**Derived from**: Multi-tenancy conventions for analytics tables, medallion generator output schema handling, and BigQuery best practices for time-series multi-tenant data.

## Inferred Patterns

### pandas Usage

**Status**: Not directly observed in production examples.

**Context**: Production services use BigQuery native load jobs (`load_table_from_uri()`) and SQLX/Dataform for in-warehouse transformations. pandas would be used for pre-processing before load, but the pattern leans on SQL-first data warehouse approaches.

**Inferred pattern**: Standard Python ETL practice for GCS↔BigQuery pipelines (read GCS CSV/Parquet → pandas DataFrame transforms → `to_gbq()` or write Parquet back to GCS → BigQuery load).

### Partitioning/Clustering SQL

**Status**: No direct `CREATE TABLE ... PARTITION BY ... CLUSTER BY` SQL observed in production examples.

**Context**: Production services use SQLX/Dataform config blocks (declarative) rather than raw SQL DDL. Partitioning/clustering is specified in Dataform config.

**Inferred pattern**: Standard BigQuery practice for time-series data (partition by date, cluster by high-cardinality dimensions), cross-referenced with multi-tenancy patterns.
