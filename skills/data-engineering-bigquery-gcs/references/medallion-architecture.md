# Medallion Architecture: Bronze, Silver, Gold

Three-layer data warehouse pattern derived from real-world production services.

## Overview

**Medallion** is a data lakehouse pattern with three layers:

1. **Bronze** — Raw ingestion from source systems (CDC, GCS exports, API dumps)
2. **Silver** — Cleaned, joined, business logic applied; unified schema
3. **Gold** — Aggregated metrics and KPIs for analytics and dashboards

Each layer is a separate BigQuery dataset.

## Layer Definitions

### Bronze Layer

**Purpose**: Ingest raw data with minimal transformation; preserve source fidelity.

**Schema**: `da_bronze`  
**Table prefix**: `br_`  
**Tags**: `["bronze", "cdc"]`

**Key conventions**:
- One bronze table per source table.
- For CDC sources (Datastream), deduplicate using `QUALIFY ROW_NUMBER()`.
- Exclude deleted rows: `WHERE datastream_metadata.change_type NOT LIKE '%DELETE%'`.
- `SELECT * EXCEPT(datastream_metadata)` to omit CDC metadata from final table.

**Example SQLX**:

```sql
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
```

**Example from bronze dataset generator:**

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

### Silver Layer

**Purpose**: Cleaned, joined, business logic applied; single source of truth for analytics.

**Schema**: `da_silver`  
**Table prefix**: `slv_`  
**Tags**: `["silver", "daily"]`

**Key conventions**:
- Reference bronze tables via `${ref("br_tablename")}` for Dataform lineage.
- Join multiple bronze tables as needed.
- Apply business rules (e.g., filter by status, enrich with lookups).
- Inject `org_id` for multi-tenant analytics.
- Dependencies: `dependencies: ["br_table1", "br_table2"]`

**Example SQLX**:

```sql
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
```

**Example from medallion generator:**

```python
silver_sql = f"""config {{
  type: "table",
  schema: "da_silver",
  name: "slv_{domain}_clean",
  tags: ["silver", "daily"],
  dependencies: [{deps_str}],
  description: "{self._escape_sqlx_string(descriptions['table_description'])}",
{columns_block}
}}

{modified_sql}"""
```

### Gold Layer

**Purpose**: Aggregated metrics and KPIs; optimized for BI tools and dashboards.

**Schema**: `da_gold`  
**Table prefix**: `gld_`  
**Tags**: `["gold", "daily"]`

**Key conventions**:
- Reference silver tables via `${ref("slv_domain_clean")}`.
- Aggregate by dimensions (e.g., `GROUP BY org_id, metric_date, site`).
- If silver already has aggregations, gold may pass through (`SELECT *`).
- Dependencies: `dependencies: ["slv_domain_clean"]`

**Example SQLX**:

```sql
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
```

**Example from medallion generator:**

```python
gold_sql = f"""config {{
  type: "table",
  schema: "da_gold",
  name: "gld_{domain}_metrics",
  tags: ["gold", "daily"],
  dependencies: ["slv_{domain}_clean"],
  description: "{self._escape_sqlx_string(descriptions['table_description'])}",
{columns_block}
}}



{select_clause}"""
```

## Layer Dependencies

**Never skip layers**. The medallion pattern requires:
- Bronze tables reference source systems.
- Silver tables reference bronze via `${ref("br_tablename")}`.
- Gold tables reference silver via `${ref("slv_domain_clean")}`.

**Anti-pattern**: Creating a gold table that directly references bronze (skips silver).

**Example from medallion generator:**

```python
return {
    "bronze_files": bronze_file_paths,
    "silver_file": silver_file,
    "gold_file": gold_file,
    # ... (layers are always created together)
}
```

## Multi-Tenant Data: org_id

Every Silver and Gold table MUST include `org_id STRING NOT NULL` for multi-org analytics.

**Partitioning**: `PARTITION BY metric_date`  
**Clustering**: `CLUSTER BY org_id, site, ...` (org_id first)

**Derived from**: Multi-tenancy conventions, medallion generator output schema handling, and BigQuery best practices for time-series multi-tenant data. The pattern assumes org_id is part of the schema for Silver and Gold tables.

## Temporal Orchestration Pattern

Silver layer materialization is orchestrated by a **parent workflow** that chains child workflows:

1. **ManualQueryWorkflow** — register usecase, detect query type, insert query
2. **MaterializeSilverQueryWorkflow** — create BQ table, insert silver layer metadata, generate descriptions
3. **SyncSilverDescriptionWorkflow** — sync descriptions to BigQuery
4. **SilverDataSyncWorkflow** — execute query and load data

If any child fails, the parent triggers a **rollback activity** to clean up DB records and BQ resources by `usecase_id`.

**Critical rule**: All BigQuery queries, GCS operations, and pandas transforms MUST run inside Temporal **activities**, not workflow code (workflows are replay-safe and should only orchestrate).

**Example workflow architecture:**

```
POST /create-query → ParentWorkflow
  try:
    ├── Child 1: ManualQueryWorkflow
    ├── Child 2: MaterializeSilverQueryWorkflow
    ├── Child 3: SyncSilverDescriptionWorkflow
    └── Child 4: SilverDataSyncWorkflow
  except:
    → rollback_silver_by_usecase_activity (cleanup by usecase_id)
```

**From Temporal workflow documentation:**

> "It also gives a clean boundary between **API code** (which triggers workflows and returns IDs) and **worker code** (which executes activities and updates DB/GCS/externals)."

## Automated Description Generation

The medallion generator uses **Vertex AI LLMs** to generate table and column descriptions from sample data and context.

**Pattern**:
1. Fetch sample rows from source table (limit 3-5).
2. Send to LLM with schema and business context.
3. LLM returns JSON with `table_description` and `column_descriptions` object.
4. Descriptions are inserted into SQLX config blocks.

**Example from medallion generator:**

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

## Directory Structure

Medallion SQLX files are saved under `definitions/`:

```
definitions/
  bronze/
    {domain}/
      br_table1.sqlx
      br_table2.sqlx
  silver/
    {domain}/
      slv_domain_clean.sqlx
      assertion_unique_order_id.sqlx  (assertions for silver)
      assertion_not_null_org_id.sqlx
  gold/
    {domain}/
      gld_domain_metrics.sqlx
```

**Example from medallion generator:**

```python
bronze_path = self._save_sqlx_file(
    bronze_content, 
    f"bronze/{domain}/{bronze_filename}",
    output_dir
)

silver_file = self._save_sqlx_file(
    silver_content,
    f"silver/{domain}/slv_{domain}_clean.sqlx",
    output_dir
)

gold_file = self._save_sqlx_file(
    gold_content,
    f"gold/{domain}/gld_{domain}_metrics.sqlx",
    output_dir
)
```
