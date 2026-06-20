# pandas Transform Pipelines for GCS/BigQuery

Patterns for reading data from GCS, transforming with pandas, and writing to BigQuery.

## Status: Inferred Pattern

**Note**: Direct pandas usage was **not observed** in production examples. However, this is a standard pattern for GCS↔BigQuery ETL pipelines in the Python ecosystem. Production services use GCS client + BigQuery client separately; pandas would be the natural bridge for in-memory transformations.

## Typical Flow

```
GCS (CSV/Parquet/JSON)
  ↓ read
pandas DataFrame
  ↓ transform (filter, join, aggregate, dtype casts)
BigQuery table (via to_gbq)
  OR
GCS (Parquet, for BigQuery load)
```

## Reading from GCS

### Option 1: Direct GCS URI (requires `gcsfs`)

```python
import pandas as pd

# Read CSV from GCS
df = pd.read_csv("gs://my-bucket/data/file.csv")

# Read Parquet from GCS
df = pd.read_parquet("gs://my-bucket/data/file.parquet")
```

**Dependencies**: `pip install gcsfs`

### Option 2: Download Blob to Memory

```python
from google.cloud import storage
import pandas as pd
from io import BytesIO

storage_client = storage.Client()
bucket = storage_client.bucket("my-bucket")
blob = bucket.blob("data/file.csv")

csv_bytes = blob.download_as_bytes()
df = pd.read_csv(BytesIO(csv_bytes))
```

**Pattern basis**: Blob download pattern from production GCS utilities. Reading into pandas is the standard next step for in-memory processing.

## Transform Patterns

```python
# Filter rows
df_filtered = df[df["status"] == "completed"]

# Join with another DataFrame
df_joined = df_filtered.merge(df_customers, on="customer_id", how="left")

# Aggregate
df_agg = df_joined.groupby(["org_id", "metric_date"]).agg({
    "order_id": "count",
    "total_amount": "sum",
}).reset_index()

# Rename columns
df_agg.rename(columns={"order_id": "order_count", "total_amount": "total_sales"}, inplace=True)

# Type casts
df_agg["metric_date"] = pd.to_datetime(df_agg["metric_date"])
df_agg["org_id"] = df_agg["org_id"].astype(str)
```

## Writing to BigQuery

### Option 1: Direct `to_gbq()`

```python
import pandas_gbq

df.to_gbq(
    destination_table="my_project.my_dataset.my_table",
    project_id="my-gcp-project",
    if_exists="append",  # or "replace"
    chunksize=10000,     # Batch size for large DataFrames
)
```

**Best practice**: Always specify `chunksize` for DataFrames with >100k rows to avoid memory exhaustion.

### Option 2: Write to GCS Parquet, then BigQuery Load

```python
# Write to GCS as Parquet
df.to_parquet("gs://my-bucket/staging/data_2026_06_20.parquet", index=False)

# Then load to BigQuery via load job (see bigquery-gcs-io.md)
from google.cloud import bigquery

client = bigquery.Client(project="my-gcp-project")
job_config = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.PARQUET)

load_job = client.load_table_from_uri(
    "gs://my-bucket/staging/data_2026_06_20.parquet",
    "my_project.my_dataset.my_table",
    job_config=job_config,
)
load_job.result()
```

**When to use**: For large DataFrames (>1M rows), writing to Parquet and using BigQuery's native load is faster and more reliable than `to_gbq()`.

## Example End-to-End Pipeline

```python
from google.cloud import storage, bigquery
import pandas as pd
from io import BytesIO

# 1. Download CSV from GCS
storage_client = storage.Client()
bucket = storage_client.bucket("my-bucket")
blob = bucket.blob("exports/orders_2026_06_20.csv")

csv_bytes = blob.download_as_bytes()
df = pd.read_csv(BytesIO(csv_bytes))

# 2. Transform
df_cleaned = df[df["status"] == "completed"]
df_cleaned["order_date"] = pd.to_datetime(df_cleaned["order_date"])
df_cleaned["org_id"] = df_cleaned["org_id"].astype(str)

# 3. Load to BigQuery
df_cleaned.to_gbq(
    destination_table="my_project.da_bronze.br_orders",
    project_id="my-gcp-project",
    if_exists="append",
    chunksize=10000,
)
```

## Anti-Patterns

- **Loading entire GCS blob into memory for large files** — use streaming or BigQuery native load for files >1GB.
- **Not specifying `chunksize` in `to_gbq()`** — can exhaust memory on large DataFrames.
- **Not specifying `if_exists`** — ambiguous behavior; always use `"append"` or `"replace"`.
- **Running pandas transforms in Temporal workflow code** — this is blocking I/O; must be in an activity (see [medallion-architecture.md](./medallion-architecture.md) Temporal section).

## Why pandas is not directly observed in production examples

Production services often use:
- **BigQuery native load jobs** for GCS → BigQuery ingestion (via `load_table_from_uri()`)
- **SQLX/Dataform** for in-warehouse transformations (Silver and Gold layers are materialized as BigQuery views/tables)
- **Vertex AI LLMs** for description generation (not data transformation)

pandas would be used for **pre-processing** data before load (e.g., cleaning raw CSV, enriching with external APIs, complex Python logic), but many production services lean on BigQuery's SQL engine for transformations. This is a valid architectural choice (SQL-first data warehouse pattern).

If pandas is needed, the pattern above is the standard approach for Python-based ETL.
