# Data Engineering: BigQuery & GCS Pipelines

BigQuery and GCS batch data pipeline patterns with medallion architecture, pandas transforms, and Temporal orchestration derived from real-world production Python/FastAPI services.

## What this skill covers

- **Medallion architecture**: Bronze (raw CDC) → Silver (cleaned, joined) → Gold (aggregated metrics); layer-specific naming conventions
- **BigQuery client patterns**: Query execution, schema introspection, dry-run inference, table creation with partitioning/clustering, MERGE upserts
- **Temp table staging pattern**: Load to temp → MERGE to main → cleanup; atomic upserts with timestamp-based conflict resolution
- **LoadJobConfig options**: `ignore_unknown_values`, `write_disposition`, `job_id_prefix`, schema building for nested RECORD fields
- **GCS client patterns**: Blob upload/download, existence checks, wildcard patterns for bulk loads
- **pandas transform pipelines**: GCS↔BigQuery data movement with DataFrame transformations (inferred pattern, not directly observed)
- **Temporal activity-based I/O**: Heavy I/O (BQ queries, GCS ops, pandas) in activities; workflows orchestrate only
- **Partitioning/clustering conventions**: Date partitioning + clustering by high-cardinality dimensions (org_id, site, product_id)
- **CDC deduplication**: `QUALIFY ROW_NUMBER()` pattern for Datastream bronze tables

## Provenance

Derived from real-world production Python/FastAPI services implementing data pipelines with BigQuery, GCS, Temporal, and medallion architecture patterns.

## How to apply

1. **For medallion architecture**: Create three BigQuery datasets (`da_bronze`, `da_silver`, `da_gold`). Bronze ingests raw CDC with deduplication; Silver cleans and joins; Gold aggregates.
2. **For BigQuery schemas**: Always partition by date column (`metric_date`, `event_date`). Cluster by high-cardinality dimensions used in filters (`org_id`, `site`).
3. **For incremental sync jobs**: Use temp table + MERGE pattern — Load GCS → temp table with `WRITE_TRUNCATE`, MERGE temp → main with timestamp check, track MAX(timestamp), cleanup temp.
4. **For Temporal orchestration**: Put all BigQuery queries, GCS blob operations, and pandas transforms inside `@activity.defn` functions. Workflows orchestrate via `workflow.execute_activity()`.
5. **For multi-tenant data**: Add `org_id STRING NOT NULL` to every Silver and Gold table; cluster by `org_id` first.
6. **For CDC bronze tables**: Use `QUALIFY ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY created_at DESC, datastream_metadata.source_timestamp DESC) = 1` to keep the latest event.
7. **For evolving schemas**: Set `ignore_unknown_values=True` in LoadJobConfig to tolerate extra fields from source systems.

## Pattern Sources

- **Codebase-derived**: Medallion layer structure, CDC deduplication logic, BigQuery client usage, GCS client upload/download, Temporal activity/workflow pattern, parent-child workflow chaining with rollback.
- **Inferred patterns**: pandas transform pipelines (standard pattern for GCS↔BQ data movement; common in batch ETL), partitioning/clustering conventions (derived from multi-tenancy patterns and BigQuery best practices).
- **API documentation**: BigQuery `PARTITION BY` and `CLUSTER BY` syntax (GCP BigQuery documentation), `google.cloud.bigquery.Client` and `google.cloud.storage.Client` APIs (google-cloud-bigquery and google-cloud-storage library docs), Temporal activity/workflow separation (Temporal Python SDK documentation on replay safety and determinism).
