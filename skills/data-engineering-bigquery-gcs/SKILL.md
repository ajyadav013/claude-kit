---
name: data-engineering-bigquery-gcs
description: BigQuery and GCS data pipeline patterns — medallion architecture (bronze/silver/gold), BigQuery client query/load operations with MERGE upserts, GCS blob read/write, temp table staging pattern, pandas transform pipelines, Datastream CDC deduplication, partitioning/clustering conventions, and Temporal activity-based I/O (not workflow). Use when building batch ETL pipelines, implementing medallion data layers, designing BigQuery schemas with partitioning, orchestrating data sync jobs with Temporal, performing atomic upserts with MERGE, or transforming data between GCS and BigQuery using pandas.
---

# Data Engineering: BigQuery & GCS Pipelines

Stack-agnostic BigQuery and GCS batch data pipeline patterns with medallion layering, pandas transforms, and Temporal orchestration.

## When to use

- Implementing medallion architecture (bronze/silver/gold layers) for a data warehouse
- Building ETL pipelines that read from GCS and write to BigQuery
- Designing BigQuery schemas with date partitioning and clustering
- Orchestrating data sync jobs with Temporal workflows and activities
- Implementing atomic upserts (MERGE) from staging tables to production tables
- Transforming data with pandas DataFrames before loading to BigQuery
- Implementing CDC deduplication for Datastream-synced bronze tables
- Loading data from GCS with schema flexibility and nested RECORD fields
- Generating table and column descriptions for data catalogs

## Core conventions

### Medallion Architecture (Bronze → Silver → Gold)

**Three-layer pattern**: Bronze = raw ingestion (Datastream CDC, GCS exports); Silver = cleaned, joined, business logic; Gold = aggregated metrics and KPIs. Each layer is a separate BigQuery dataset.

**Bronze table conventions**: Schema `da_bronze`, table prefix `br_`, tags `["bronze", "cdc"]`. Use `QUALIFY ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY created_at DESC, datastream_metadata.source_timestamp DESC) = 1` to deduplicate CDC events. Exclude deletes: `WHERE datastream_metadata.change_type NOT LIKE '%DELETE%'`.

**Silver table conventions**: Schema `da_silver`, table prefix `slv_`, tags `["silver", "daily"]`. Reference bronze tables via `${ref("br_tablename")}` for Dataform lineage. Silver layer injects `org_id` for multi-tenant analytics.

**Gold table conventions**: Schema `da_gold`, table prefix `gld_`, tags `["gold", "daily"]`. Reference silver via `${ref("slv_domain_clean")}`. Gold contains aggregations (COUNT, SUM, AVG) grouped by dimensions. If silver already has aggregations, gold passes through `SELECT *`.

**Layer dependencies**: Track via `dependencies: ["br_table1", "br_table2"]` in SQLX config blocks. Each layer references the layer below; never skip layers (bronze → gold is an anti-pattern).

### BigQuery Client Patterns

**Client initialization**: `from google.cloud import bigquery; client = bigquery.Client(project=project_id)`. For explicit project override, pass `project=` to the constructor.

**Query execution**: `rows = client.query(sql_query).result()` for sync execution. Iterate `rows` to consume results. For large result sets, stream rows without loading all into memory.

**Schema introspection**: `table = client.get_table(f"{project}.{dataset}.{table_name}")`. Access `table.schema` for field list, `table.view_query` for view SQL. Each field has `.name`, `.field_type`, `.mode`, `.description`.

**Dry-run for schema inference**: Execute query with `job_config.dry_run = True` to get schema without running query. Use this to derive table schema before first load.

**Table creation with partitioning**: `CREATE TABLE {table} (...) PARTITION BY metric_date CLUSTER BY org_id, site`. Always partition by date column for time-series data; cluster by high-cardinality dimensions used in filters. _(Pattern inferred from BigQuery best practices; not directly observed in evidence repos, which use SQLX/Dataform declarative config instead of raw DDL)_

**Load job from GCS**: Use `client.load_table_from_uri(gcs_pattern, table_ref, job_config=LoadJobConfig(...))` to ingest JSON/CSV/Parquet from GCS into BigQuery. Common config options: `source_format`, `schema`, `write_disposition` ("WRITE_TRUNCATE"|"WRITE_APPEND"), `ignore_unknown_values=True` for schema flexibility, `job_id_prefix` for tracking.

**MERGE for upserts**: Use BigQuery MERGE to atomically update existing rows and insert new ones. Pattern: Load to temp table → MERGE temp to main → cleanup temp. MERGE condition typically checks a timestamp to only update when source is newer.

**Schema building for nested fields**: For RECORD types, use recursive schema building with `bigquery.SchemaField(name, "RECORD", fields=[...])`. Each nested field is itself a SchemaField with name, type, and mode.

### GCS Client Patterns

**Client initialization**: `from google.cloud import storage; storage_client = storage.Client()`. No project parameter needed if default credentials are set.

**Upload blob from string**: `bucket = storage_client.bucket(bucket_name); blob = bucket.blob(blob_name); blob.upload_from_string(data=file_content, content_type=content_type)`. Use for small in-memory payloads.

**Download blob as bytes**: `blob = bucket.blob(blob_name); image_bytes = blob.download_as_bytes()`. For base64 encoding, wrap with `base64.b64encode(image_bytes).decode('utf-8')`.

**Existence check**: `blob.exists()` returns `True` if blob is present, `False` otherwise. Always check before downloading to avoid exceptions.

**Wildcard patterns for bulk operations**: Use GCS URI patterns like `gs://{bucket}/{prefix}/*.json` with BigQuery load jobs to import multiple files.

### pandas Transform Pipelines

**Typical flow**: Read from GCS (CSV/Parquet) → pandas DataFrame transforms (filter, join, aggregate, dtype casts) → write to BigQuery via `to_gbq()` or to GCS as Parquet. _(inferred pattern; standard for GCS↔BQ pipelines)_

**GCS Parquet read**: Use `pandas.read_parquet(f"gs://{bucket}/{path}")` if `gcsfs` is installed, or download blob to memory and `pandas.read_parquet(BytesIO(blob_content))`. _(common pattern, not directly observed in evidence)_

**BigQuery write**: `df.to_gbq(destination_table=f"{dataset}.{table}", project_id=project_id, if_exists="append"|"replace", chunksize=10000)`. Always specify `chunksize` for large DataFrames to avoid memory exhaustion. _(common pattern, not directly observed in evidence)_

### Temporal Orchestration (Activity-Based I/O)

**Critical rule: Heavy I/O in activities, not workflows**: BigQuery queries, GCS uploads/downloads, pandas transforms, and external API calls MUST run inside Temporal activities, never directly in workflow code. Workflows are replay-safe and should only orchestrate, not execute blocking I/O.

**Activity pattern**: Define activity functions decorated with `@activity.defn`. Each activity should be idempotent. Use activities for: BigQuery queries, GCS blob operations, database writes, HTTP requests, pandas processing.

**Workflow pattern**: Workflow functions orchestrate by calling `await workflow.execute_activity(activity_fn, args, ...)`. Workflows maintain state and handle retries, but do not perform I/O.

**Parent-child workflow chaining**: Use `workflow.execute_child_workflow()` to sequentially chain workflows (e.g., a parent workflow chains ManualQueryWorkflow → MaterializeSilverQueryWorkflow → SyncSilverDescriptionWorkflow → SilverDataSyncWorkflow). If a child fails, parent can trigger rollback activities.

**Rollback on failure**: When a child workflow fails, parent workflow invokes a rollback activity (e.g., `rollback_silver_by_usecase_activity`) to clean up database records and BigQuery resources by identifier.

### Partitioning and Schema Conventions

**Date partitioning**: All time-series tables MUST use `PARTITION BY {date_column}` (e.g., `metric_date`, `event_date`). This enables efficient pruning and reduces query costs. _(inferred from multi-tenancy org_id pattern)_

**Clustering**: After partitioning, add `CLUSTER BY` for high-cardinality columns used in WHERE clauses and JOINs (e.g., `org_id`, `site`, `product_id`). Clustering is free and improves query performance. _(inferred from multi-tenancy org_id pattern)_

**org_id for multi-tenant data**: Every Silver and Gold table MUST include `org_id STRING NOT NULL` as a mandatory column for multi-org analytics. Cluster by `org_id` first for efficient tenant scoping. _(Pattern inferred from multi-tenancy conventions and medallion generator schema handling)_

**Audit columns**: Add `_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()` to Bronze and Silver tables. For CDC bronze, use `datastream_metadata.source_timestamp` for source change tracking. _(inferred from bronze_dataset_generator.py deduplication logic)_

## Skeleton / example

```python
# BigQuery client initialization and query
from google.cloud import bigquery

client = bigquery.Client(project="my-gcp-project")

# Query with sync execution
query = """
SELECT org_id, metric_date, SUM(sales) as total_sales
FROM `my-project.da_silver.slv_sales_clean`
WHERE metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY org_id, metric_date
"""
rows = client.query(query).result()
for row in rows:
    print(f"{row.org_id}: {row.total_sales}")

# Schema introspection
table = client.get_table("my-project.da_bronze.br_orders")
for field in table.schema:
    print(f"{field.name} ({field.field_type}): {field.description}")

# GCS client for blob operations
from google.cloud import storage

storage_client = storage.Client()
bucket = storage_client.bucket("my-data-bucket")

# Upload JSON blob
blob = bucket.blob("exports/data_2026_06_20.json")
blob.upload_from_string(data=json.dumps(data), content_type="application/json")

# Download blob as bytes
download_blob = bucket.blob("imports/source_file.csv")
if download_blob.exists():
    csv_bytes = download_blob.download_as_bytes()
    # Process csv_bytes...

# Load from GCS to BigQuery with configuration
from google.cloud.bigquery import LoadJobConfig, SourceFormat

job_config = LoadJobConfig(
    source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
    schema=schema,
    write_disposition="WRITE_TRUNCATE",
    ignore_unknown_values=True,
)

gcs_uri = "gs://my-bucket/exports/*.json"
table_ref = "my-project.my_dataset.temp_table"
load_job = client.load_table_from_uri(
    gcs_uri, table_ref, job_config=job_config, job_id_prefix="sync_temp_"
)
load_job.result()  # Wait for completion

# MERGE temp table to main table (upsert pattern)
merge_sql = f"""
MERGE `my-project.my_dataset.main_table` T
USING `my-project.my_dataset.temp_table` S
ON T.order_id = S.order_id
WHEN MATCHED AND S.updated_at > T.updated_at THEN
  UPDATE SET total_amount = S.total_amount, updated_at = S.updated_at
WHEN NOT MATCHED THEN
  INSERT (order_id, total_amount, updated_at) 
  VALUES (S.order_id, S.total_amount, S.updated_at)
"""
client.query(merge_sql).result()

# Cleanup temp table
client.query("TRUNCATE TABLE `my-project.my_dataset.temp_table`").result()

# Bronze table with CDC deduplication (SQLX)
config {
  type: "table",
  schema: "da_bronze",
  name: "br_orders",
  tags: ["bronze", "cdc"],
  description: "Raw orders from Datastream CDC"
}

SELECT * EXCEPT(datastream_metadata)
FROM `my-project.raw_cdc.orders`
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY order_id
  ORDER BY created_at DESC,
          datastream_metadata.source_timestamp DESC,
          datastream_metadata.change_sequence_number DESC
) = 1
AND datastream_metadata.change_type NOT LIKE '%DELETE%'

# Silver table with bronze dependency (SQLX)
config {
  type: "table",
  schema: "da_silver",
  name: "slv_sales_clean",
  tags: ["silver", "daily"],
  dependencies: ["br_orders", "br_customers"],
  description: "Cleaned sales data with customer joins"
}

SELECT
  o.order_id,
  o.org_id,
  o.order_date as metric_date,
  c.customer_name,
  o.total_amount
FROM ${ref("br_orders")} o
JOIN ${ref("br_customers")} c ON o.customer_id = c.customer_id
WHERE o.order_status = 'completed'

# Gold table with aggregations (SQLX)
config {
  type: "table",
  schema: "da_gold",
  name: "gld_sales_metrics",
  tags: ["gold", "daily"],
  dependencies: ["slv_sales_clean"],
  description: "Daily sales metrics by org and site"
}

SELECT
  org_id,
  metric_date,
  site,
  COUNT(DISTINCT order_id) as order_count,
  SUM(total_amount) as total_sales,
  AVG(total_amount) as avg_order_value
FROM ${ref("slv_sales_clean")}
GROUP BY org_id, metric_date, site

# Temporal activity for BigQuery query (Python)
from temporalio import activity
from google.cloud import bigquery

@activity.defn
async def execute_bq_query_activity(query: str, project_id: str) -> list:
    """Execute BigQuery query and return results.
    
    MUST be an activity, not workflow code (blocking I/O).
    """
    client = bigquery.Client(project=project_id)
    rows = client.query(query).result()
    return [dict(row) for row in rows]

# Temporal workflow orchestrating activities
from temporalio import workflow

@workflow.defn
class DataSyncWorkflow:
    @workflow.run
    async def run(self, params: dict) -> dict:
        # Heavy I/O delegated to activities
        raw_data = await workflow.execute_activity(
            fetch_from_gcs_activity,
            args=[params["bucket"], params["blob_path"]],
            start_to_close_timeout=timedelta(minutes=10),
        )
        
        transformed = await workflow.execute_activity(
            transform_data_activity,
            args=[raw_data],
            start_to_close_timeout=timedelta(minutes=5),
        )
        
        await workflow.execute_activity(
            load_to_bigquery_activity,
            args=[transformed, params["target_table"]],
            start_to_close_timeout=timedelta(minutes=10),
        )
        
        return {"status": "success"}

# Parent workflow with child chaining and rollback
@workflow.defn
class SilverLayerOrchestrationWorkflow:
    @workflow.run
    async def run(self, usecase_id: str) -> dict:
        try:
            await workflow.execute_child_workflow(
                ManualQueryWorkflow.run,
                args=[usecase_id],
                id=f"manual-query-{usecase_id}",
            )
            
            await workflow.execute_child_workflow(
                MaterializeSilverQueryWorkflow.run,
                args=[usecase_id],
                id=f"materialize-{usecase_id}",
            )
            
            await workflow.execute_child_workflow(
                SyncSilverDescriptionWorkflow.run,
                args=[usecase_id],
                id=f"sync-desc-{usecase_id}",
            )
            
            await workflow.execute_child_workflow(
                SilverDataSyncWorkflow.run,
                args=[usecase_id],
                id=f"data-sync-{usecase_id}",
            )
            
            return {"status": "success"}
        
        except Exception as e:
            # Rollback on any child failure
            await workflow.execute_activity(
                rollback_silver_by_usecase_activity,
                args=[usecase_id],
                start_to_close_timeout=timedelta(minutes=5),
            )
            raise
```

## Anti-patterns to avoid

- **Skipping layers in medallion** — never go from bronze directly to gold; always go bronze → silver → gold.
- **Running BigQuery queries in Temporal workflow code** — all blocking I/O (BQ, GCS, pandas) must be in activities, not workflows (replay-safety violation).
- **Missing partitioning on time-series tables** — always `PARTITION BY {date_column}` for efficient querying and cost control.
- **Forgetting org_id in Silver/Gold** — multi-org analytics require `org_id STRING NOT NULL` on every table for tenant scoping.
- **Not deduplicating CDC bronze tables** — Datastream sends multiple events per row; use `QUALIFY ROW_NUMBER()` with `PARTITION BY {pk}` to keep only the latest.
- **Hard-coding project IDs** — pass `project_id` as a parameter or environment variable for cross-environment portability.
- **Loading entire GCS blob into memory for large files** — use streaming or BigQuery native load via `load_table_from_uri()` for files >1GB.
- **Omitting `if_exists` in pandas `to_gbq()`** — always specify `"append"` or `"replace"` to avoid ambiguous behavior.
- **Directly inserting/updating main tables without temp staging** — use temp table → MERGE → cleanup pattern for atomic upserts and easier rollback.
- **Not setting `ignore_unknown_values=True` for evolving schemas** — schema changes in source systems can break load jobs; this option provides flexibility.

## References

- [bigquery-gcs-io.md](./references/bigquery-gcs-io.md) — BigQuery client and GCS client operations
- [temp-table-merge-pattern.md](./references/temp-table-merge-pattern.md) — Atomic upsert pattern with temp table staging
- [pandas-pipelines.md](./references/pandas-pipelines.md) — Pandas transform patterns for GCS/BQ pipelines
- [medallion-architecture.md](./references/medallion-architecture.md) — Bronze/Silver/Gold layer design and conventions
- [repo-evidence.md](./references/repo-evidence.md) — Real file paths and snippets from source repos
