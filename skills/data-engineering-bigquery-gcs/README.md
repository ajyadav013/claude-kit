# Data Engineering: BigQuery & GCS Pipelines

BigQuery data pipeline patterns with medallion architecture and Temporal orchestration, derived from real-world production Python/FastAPI services. GCS blob upload/download is covered by the companion **`gcs-file-storage-patterns`** skill; this skill focuses on BigQuery itself.

## What this skill covers

- **Medallion architecture**: Bronze (raw CDC) → Silver (cleaned, joined) → Gold (aggregated metrics); layer-specific naming conventions
- **BigQuery client patterns**: Query execution, schema introspection, dry-run inference, table creation with partitioning/clustering, MERGE upserts
- **Temp table staging pattern**: Load to temp → MERGE to main → cleanup; atomic upserts with timestamp-based conflict resolution
- **LoadJobConfig options**: `ignore_unknown_values`, `write_disposition`, `job_id_prefix`, schema building for nested RECORD fields
- **Parameterized queries**: `QueryJobConfig` + `ScalarQueryParameter`/`ArrayQueryParameter` for safe, type-checked, injection-free SQL
- **Streaming inserts**: `insert_rows_json` with batching and per-row error handling for near-real-time ingestion (<1000-row batches)
- **In-memory DataFrame loads**: `load_table_from_dataframe` to load pandas DataFrames directly to BigQuery without GCS staging
- **Dynamic schema evolution**: `update_table` to append NULLABLE columns when upstream schemas drift
- **TimePartitioning Python API**: programmatic creation of partitioned/clustered tables (vs. SQLX/Dataform DDL)
- **BigQueryUtils wrapper**: a reusable client class centralizing init, error handling, and common operations
- **Temporal activity-based I/O**: Heavy I/O (BQ queries, GCS ops) in activities; workflows orchestrate only
- **Partitioning/clustering conventions**: Date partitioning + clustering by high-cardinality dimensions (org_id, site, product_id)
- **CDC deduplication**: `QUALIFY ROW_NUMBER()` pattern for Datastream bronze tables

## Provenance

Derived from real-world production Python/FastAPI services implementing data pipelines with BigQuery, GCS, Temporal, and medallion architecture patterns.

## How to apply

1. **For medallion architecture**: Create three BigQuery datasets (`bronze`, `silver`, `gold`). Bronze ingests raw CDC with deduplication; Silver cleans and joins; Gold aggregates.
2. **For BigQuery schemas**: Always partition by date column (`metric_date`, `event_date`). Cluster by high-cardinality dimensions used in filters (`org_id`, `site`). Use the `TimePartitioning` Python API for programmatic table creation, or `PARTITION BY` in SQLX/Dataform.
3. **For incremental sync jobs**: Use temp table + MERGE pattern — load (from GCS via `load_table_from_uri`, or in-memory via `load_table_from_dataframe`) → temp table with `WRITE_TRUNCATE`, MERGE temp → main with timestamp check, track MAX(timestamp), cleanup temp.
4. **For user-supplied query values**: Always use parameterized queries (`QueryJobConfig` + `ScalarQueryParameter`/`ArrayQueryParameter`); never f-string interpolate input into SQL.
5. **For Temporal orchestration**: Put all BigQuery queries and GCS blob operations inside `@activity.defn` functions. Workflows orchestrate via `workflow.execute_activity()` and never perform blocking I/O.
6. **For multi-tenant data**: Add `org_id STRING NOT NULL` to every Silver and Gold table; cluster by `org_id` first.
7. **For CDC bronze tables**: Use `QUALIFY ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY created_at DESC, datastream_metadata.source_timestamp DESC) = 1` to keep the latest event.
8. **For evolving schemas**: Set `ignore_unknown_values=True` in LoadJobConfig to tolerate extra fields, and use `update_table` to append NULLABLE columns when new fields must be queryable.

## Pattern Sources

- **Codebase-derived**: Medallion layer structure, CDC deduplication logic, BigQuery client usage, parameterized queries, streaming inserts with batching, `load_table_from_dataframe`, dynamic schema evolution, `TimePartitioning` Python API, reusable `BigQueryUtils` wrapper, Temporal activity/workflow pattern, parent-child workflow chaining with rollback.
- **Inferred patterns**: partitioning/clustering conventions (derived from multi-tenancy patterns and BigQuery best practices); raw-DDL table creation (repos use SQLX/Dataform declarative config instead).
- **API documentation**: BigQuery `PARTITION BY`/`CLUSTER BY` syntax and parameterized-query/streaming-insert APIs (GCP BigQuery documentation), `google.cloud.bigquery.Client` API (google-cloud-bigquery library docs), Temporal activity/workflow separation (Temporal Python SDK documentation on replay safety and determinism).
- **GCS blob operations**: see the companion `gcs-file-storage-patterns` skill.
