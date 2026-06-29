---
name: gcs-file-storage-patterns
description: Google Cloud Storage patterns — credential refresh, single/bulk uploads, signed URLs, CSV/Excel reads, gs URI parsing. Use when implementing file upload/download endpoints. Distinct from batch ETL.
---

Standardize Google Cloud Storage file operations following production service patterns for uploads, downloads, signed URLs, and tabular data reads.

## When to use

- Implementing file upload endpoints (single or bulk) for user-generated content
- Generating time-limited signed URLs for secure file downloads
- Reading CSV or Excel files from GCS buckets for data processing
- Building a file storage utility layer for a FastAPI or Flask service
- Migrating local file storage to cloud object storage
- Implementing a CDN-backed asset serving pattern with GCS
- Parsing gs:// URIs to extract bucket and blob path components
- Setting up credential refresh for long-running services
- Uploading configuration files (YAML, JSON) to GCS for centralized config storage
- Implementing base64-encoded image upload from client applications

## Core conventions

1. **Storage client initialization with credential refresh**: initialize `storage.Client(credentials=_auth())` where `_auth()` calls `google.auth.default()` and refreshes credentials if expired using `credentials.refresh(google.auth.transport.requests.Request())`. For realm-scoped services, pass `credentials` and `project_id` from `auth.default(scopes=SCOPES)` in `__init__`.

2. **Single file upload**: `bucket.blob(blob_path).upload_from_file(file.file)` for file objects (e.g., FastAPI `UploadFile`), or `blob.upload_from_string(data=file_content, content_type=content_type)` for in-memory data. For base64-encoded uploads, decode first: `file_content = base64.b64decode(file["data"])`.

3. **Bulk upload with transfer_manager**: for multiple files, build `file_blob_pairs = [(file.file, bucket.blob(path)) for file in files]` and call `transfer_manager.upload_many(file_blob_pairs=file_blob_pairs, worker_type=transfer_manager.THREAD)`. Returns a list of errors (None for success); check each result to track which uploads succeeded. Significantly faster than sequential uploads for 5+ files.

4. **Signed URL generation with impersonated credentials**: to generate signed URLs from a service account in a GKE/Cloud Run environment, create `Credentials(source_credentials=source_credentials, target_principal=SERVICE_ACCOUNT_EMAIL, target_scopes=["https://www.googleapis.com/auth/cloud-platform"])` and use `blob.generate_signed_url(expiration=datetime.now() + timedelta(seconds=exp), credentials=target_credentials)`. For v4 signed URLs with direct service account credentials, pass `version="v4"`, `service_account_email=creds.service_account_email`, `access_token=creds.token`, `expiration=exp_time`, `method=sign_method` (GET/PUT/POST).

5. **CSV reading from GCS**: `client.bucket(bucket_name).get_blob(file_path).download_as_string()` then `pd.read_csv(io.BytesIO(csv_data), keep_default_na=False)`. Strip "Unnamed" columns: `df.columns = ["" if col.startswith("Unnamed") else col for col in df.columns]`. For reading multiple CSVs, use `bucket.list_blobs(prefix=prefix)` to list all blobs, filter `.endswith(".csv")`, read each, and `pd.concat(dataframes, ignore_index=True)`.

6. **Excel reading from GCS**: `blob.download_as_bytes()` then `pd.read_excel(io.BytesIO(excel_data), sheet_name=None, engine="openpyxl")` which returns a dict of sheet_name → DataFrame. For single-sheet reads, pass `sheet_name="SheetName"`.

7. **Async upload wrapper**: for FastAPI async endpoints, wrap the blocking upload in `asyncio.get_event_loop().run_in_executor(None, blob.upload_from_string, data_to_upload, content_type)` to avoid blocking the event loop. Prepare data before executor: for CSV, `data.to_csv(index=False)`; for JSON, `json.dumps(data)`; for Excel, `data.getvalue()` from a BytesIO buffer.

8. **gs:// URI parsing**: to extract bucket and blob path from `gs://bucket/path/to/file`, check `uri.startswith("gs://")`, then `no_scheme = uri[len("gs://"):]` and split on `/` once: `bucket_name, blob_path = no_scheme.split("/", 1)`. Validate both parts are non-empty.

9. **CDN path builder**: construct public CDN URLs from bucket and blob: `f"https://assets.{DOMAIN}/{bucket_name}/{blob_name}"`. For internal gs:// paths, use `f"gs://{bucket_name}/{blob_path.strip('/')}"`.

10. **File download as bytes or base64**: `blob.download_as_bytes()` returns raw bytes; for API responses, encode with `base64.b64encode(image_bytes).decode('utf-8')`. For text files, use `blob.download_as_text()` or `blob.download_as_string().decode('utf-8')`.

11. **Blob existence check**: before downloading, check `blob.exists()` to avoid exceptions. Return `None` or an empty dict entry for missing files rather than raising.

12. **Timestamped file naming**: for versioned uploads, generate `current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")` and construct `destination_blob_name = f"{folder}/{file_stem}_{timestamp}.{ext}"`.

13. **Upload return values**: return the blob path (not the full gs:// URI or CDN URL) from upload functions so callers can construct either format. For multi-file uploads, return `List[str]` with `None` entries for failed uploads.

14. **YAML/JSON config from GCS**: `blob.download_as_string().decode('utf-8')` then `yaml.safe_load(content)` or `json.loads(content)`. Cache the result in memory if reading frequently; refresh on TTL or cache invalidation signal.

15. **Error handling**: wrap GCS operations in try/except, catch generic `Exception`, log the error with structured logging (include `bucket_name`, `file_path`, `time_taken`), and return a tuple `(success: bool, result_or_error_message)` for graceful degradation.

## Skeleton / example

```python
# utils/cloud_storage.py
import io
import json
import time
from datetime import datetime, timedelta
from typing import List, Union

import pandas as pd
from google import auth
from google.auth.impersonated_credentials import Credentials
from google.cloud import storage
from google.cloud.storage import transfer_manager

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GCSClient:
    """Google Cloud Storage client for file operations with credential refresh."""

    @staticmethod
    def _auth():
        """Get and refresh credentials if needed."""
        credentials, _ = auth.default(scopes=SCOPES)
        if not credentials.valid:
            credentials.refresh(auth.transport.requests.Request())
        return credentials

    @classmethod
    def read_csv_from_gcs(cls, bucket_name: str, file_path: str) -> pd.DataFrame:
        """Read a CSV file from GCS and return as DataFrame."""
        client = storage.Client(credentials=cls._auth())
        bucket = client.bucket(bucket_name)
        blob = bucket.get_blob(file_path)
        if not blob:
            raise ValueError(f"File {file_path} not found in bucket {bucket_name}")
        
        csv_data = blob.download_as_string()
        df = pd.read_csv(io.BytesIO(csv_data), keep_default_na=False)
        # Clean unnamed columns
        df.columns = ["" if col.startswith("Unnamed") else col for col in df.columns]
        return df

    @classmethod
    def read_excel_from_gcs(cls, bucket_name: str, file_path: str) -> dict:
        """Read an Excel file from GCS and return dict of sheet_name -> DataFrame."""
        client = storage.Client(credentials=cls._auth())
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        
        excel_data = blob.download_as_bytes()
        with io.BytesIO(excel_data) as excel_buffer:
            excel_sheets = pd.read_excel(excel_buffer, sheet_name=None, engine="openpyxl")
        return excel_sheets

    @classmethod
    async def upload_to_gcs(
        cls,
        data: Union[pd.DataFrame, dict, list, io.BytesIO],
        destination_blob_name: str,
        file_name: str,
        format: str = "csv",
        bucket_name: str = "my-bucket",
    ) -> str:
        """Upload data to GCS in CSV, JSON, or XLSX format (async wrapper)."""
        current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_stem, ext = file_name.rsplit(".", 1)
        
        client = storage.Client(credentials=cls._auth())
        bucket = client.bucket(bucket_name)
        full_blob_name = f"{destination_blob_name}/{file_stem}_{current_timestamp}.{ext}"
        blob = bucket.blob(full_blob_name)

        # Prepare data and content type
        if format == "csv":
            if not isinstance(data, pd.DataFrame):
                raise ValueError("For CSV format, data should be a DataFrame.")
            data_to_upload = data.to_csv(index=False)
            content_type = "text/csv"
        elif format == "json":
            if not isinstance(data, (dict, list)):
                raise ValueError("For JSON format, data should be a dict or list.")
            data_to_upload = json.dumps(data)
            content_type = "application/json"
        elif format == "xlsx":
            data_to_upload = data.getvalue()  # BytesIO buffer
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise ValueError("Unsupported format. Use 'csv', 'json', or 'xlsx'.")

        # Upload in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, blob.upload_from_string, data_to_upload, content_type)
        
        return full_blob_name

    @classmethod
    def bulk_upload(cls, files: List, sub_path: str, bucket_name: str) -> List[str]:
        """Bulk upload files using transfer_manager for parallel upload."""
        client = storage.Client(credentials=cls._auth())
        bucket = client.bucket(bucket_name)
        
        file_blob_pairs = [
            (file.file, bucket.blob(f"{sub_path}/{file.filename}"))
            for file in files
        ]
        
        response = transfer_manager.upload_many(
            file_blob_pairs=file_blob_pairs,
            worker_type=transfer_manager.THREAD
        )
        
        # Build result list with None for failures
        file_paths = []
        for idx, (error, file) in enumerate(zip(response, files)):
            if error is None:
                file_paths.append(f"{sub_path}/{file.filename}")
            else:
                file_paths.append(None)
        
        return file_paths

    @classmethod
    def generate_signed_url(
        cls,
        bucket_name: str,
        file_name: str,
        service_account_email: str,
        exp_minutes: int = 60,
    ) -> str:
        """Generate a signed URL with impersonated credentials for time-limited access."""
        source_credentials = cls._auth()
        
        target_credentials = Credentials(
            source_credentials=source_credentials,
            target_principal=service_account_email,
            target_scopes=SCOPES,
        )
        
        client = storage.Client(credentials=target_credentials)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        signed_url = blob.generate_signed_url(
            expiration=datetime.now() + timedelta(minutes=exp_minutes),
            credentials=target_credentials,
        )
        
        return signed_url

    @staticmethod
    def parse_gcs_uri(uri: str) -> tuple[str, str]:
        """Parse gs://bucket/path URI into (bucket_name, blob_path)."""
        if not uri.startswith("gs://"):
            raise ValueError("URI must start with gs://")
        
        no_scheme = uri[len("gs://"):]
        parts = no_scheme.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("Invalid GCS URI format: must be gs://bucket/path")
        
        return parts[0], parts[1]

    @staticmethod
    def build_gcs_path(bucket_name: str, file_path: str) -> str:
        """Build gs:// URI from bucket and blob path."""
        return f"gs://{bucket_name}/{file_path.strip('/')}"

    @staticmethod
    def build_cdn_url(bucket_name: str, file_path: str, domain: str) -> str:
        """Build public CDN URL from bucket and blob path."""
        return f"https://assets.{domain}/{bucket_name}/{file_path}"
```

```python
# Example: FastAPI endpoint with file upload
from fastapi import APIRouter, UploadFile, File, Depends
from typing import List

router = APIRouter()

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a single file to GCS."""
    blob_path = f"uploads/{file.filename}"
    client = storage.Client(credentials=GCSClient._auth())
    bucket = client.bucket("my-bucket")
    blob = bucket.blob(blob_path)
    blob.upload_from_file(file.file)
    
    cdn_url = GCSClient.build_cdn_url("my-bucket", blob_path, "example.com")
    return {"success": True, "url": cdn_url}

@router.post("/bulk-upload")
async def bulk_upload_files(files: List[UploadFile] = File(...)):
    """Upload multiple files in parallel using transfer_manager."""
    file_paths = GCSClient.bulk_upload(files, sub_path="uploads", bucket_name="my-bucket")
    
    results = [
        {"filename": file.filename, "path": path, "success": path is not None}
        for file, path in zip(files, file_paths)
    ]
    return {"success": True, "results": results}

@router.get("/signed-url/{file_path:path}")
async def get_signed_url(file_path: str):
    """Generate a time-limited signed URL for secure file download."""
    signed_url = GCSClient.generate_signed_url(
        bucket_name="my-bucket",
        file_name=file_path,
        service_account_email="my-service@example.iam.gserviceaccount.com",
        exp_minutes=15,
    )
    return {"url": signed_url}
```

## Anti-patterns to avoid

1. **Not refreshing credentials in long-running services**: credentials expire; always check `credentials.valid` and refresh before creating a new client.
2. **Sequential uploads for multiple files**: use `transfer_manager.upload_many` for 5+ files to leverage parallelism.
3. **Blocking the event loop in async endpoints**: wrap synchronous GCS operations in `run_in_executor` or use async wrappers.
4. **Missing blob existence check before download**: check `blob.exists()` to avoid exceptions on missing files.
5. **Hardcoded bucket names**: load from settings/env (e.g., `settings.GCS_BUCKET`).
6. **Ignoring upload errors in bulk operations**: check the `transfer_manager.upload_many` response list for errors and track failures.
7. **Not stripping "Unnamed" columns from CSV reads**: pandas adds these for empty headers; clean them before processing.
8. **Using generate_signed_url without impersonated credentials in GKE/Cloud Run**: the default application credentials may not have signing permissions; use `impersonated_credentials.Credentials` with a service account that has `iam.serviceAccounts.signBlob` permission.
9. **Returning full CDN URLs from upload functions**: return the blob path so callers can construct either gs:// or CDN URLs as needed.
10. **Not timestamping versioned uploads**: for files that change over time, append a timestamp to avoid overwriting and enable versioned retrieval.

## References

- [client-and-uploads.md](references/client-and-uploads.md) — client initialization, credential refresh, single and bulk uploads
- [signed-urls-and-reads.md](references/signed-urls-and-reads.md) — signed URL generation, CSV/Excel reads, gs:// parsing, CDN paths
- [repo-evidence.md](references/repo-evidence.md) — source patterns and snippets
- [data-engineering-bigquery-gcs](../data-engineering-bigquery-gcs/SKILL.md) — for batch ETL and BigQuery integration
- [file-export-and-reporting](../file-export-and-reporting/SKILL.md) — for HTTP download endpoints and report generation
