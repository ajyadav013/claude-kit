# Client Initialization and Uploads

## Client initialization with credential refresh

Production services initialize the GCS client with explicit credential refresh to handle token expiration in long-running processes:

```python
import google.auth
import google.auth.transport.requests
from google.cloud import storage

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

class GCSClient:
    @staticmethod
    def _auth():
        """Get default credentials and refresh if expired."""
        credentials, _ = google.auth.default(scopes=SCOPES)
        if not credentials.valid:
            credentials.refresh(google.auth.transport.requests.Request())
        return credentials
    
    @classmethod
    def get_client(cls):
        """Get a storage client with fresh credentials."""
        return storage.Client(credentials=cls._auth())
```

For realm-scoped services, credentials are initialized once in `__init__`:

```python
from google import auth

class CloudStorageUtil:
    def __init__(self, realm: str):
        self.credentials, self.project_id = auth.default(scopes=SCOPES)
        self._refresh_credentials()
        self.bucket_name = f"{realm}-storage"
    
    def _refresh_credentials(self):
        if not self.credentials.valid:
            self.credentials.refresh(auth.transport.requests.Request())
        self.client = storage.Client(credentials=self.credentials)
```

## Single file upload from file object

For file uploads from web endpoints (e.g., FastAPI `UploadFile`):

```python
def upload(self, file: UploadFile, sub_path: str):
    """Upload a single file to GCS."""
    blob_path = f"{self.parent_folder}/{sub_path.strip('/')}/{file.filename}"
    bucket = self.client.bucket(self.bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_file(file.file)
    return blob_path
```

## Upload from string or bytes (base64-encoded content)

For base64-encoded uploads (common in image upload APIs):

```python
import base64

def upload_files_to_gcs(bucket_name: str, files: list):
    """Upload base64-encoded files to GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    uploaded_files = []
    
    for file in files:
        destination_blob_name = file["filename"]
        blob = bucket.blob(destination_blob_name)
        file_content = base64.b64decode(file["data"])
        blob.upload_from_string(data=file_content, content_type=file["contentType"])
        
        uploaded_files.append({
            "filename": destination_blob_name,
            "url": f"https://assets.example.com/{bucket_name}/{destination_blob_name}"
        })
    
    return uploaded_files
```

## Bulk upload with transfer_manager

For uploading multiple files in parallel (5+ files):

```python
from google.cloud.storage import transfer_manager

def bulk_upload(files: List[UploadFile], sub_path: str) -> List[str]:
    """Bulk upload using transfer_manager for parallelism."""
    bucket = client.bucket(bucket_name)
    
    # Build file-blob pairs
    file_blob_pairs = [
        (file.file, bucket.blob(f"{sub_path}/{file.filename}"))
        for file in files
    ]
    
    # Upload in parallel using worker threads
    response = transfer_manager.upload_many(
        file_blob_pairs=file_blob_pairs,
        worker_type=transfer_manager.THREAD
    )
    
    # Track successes and failures
    file_paths = []
    for idx, (error, file) in enumerate(zip(response, files)):
        if error is None:
            file_paths.append(f"{sub_path}/{file.filename}")
        else:
            file_paths.append(None)  # Mark failed uploads
    
    return file_paths
```

The `transfer_manager.upload_many` response is a list of exceptions (or `None` for success). Always check each result to track which uploads succeeded.

## Async upload wrapper for FastAPI

To avoid blocking the event loop in async endpoints:

```python
import asyncio
import json
from datetime import datetime

async def upload_to_gcs(
    data: Union[pd.DataFrame, dict],
    destination_blob_name: str,
    file_name: str,
    format: str = "csv",
    bucket_name: str = "my-bucket",
) -> str:
    """Upload data to GCS in CSV or JSON format (async wrapper)."""
    current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_stem, ext = file_name.rsplit(".", 1)
    
    client = storage.Client(credentials=_auth())
    bucket = client.bucket(bucket_name)
    full_blob_name = f"{destination_blob_name}/{file_stem}_{current_timestamp}.{ext}"
    blob = bucket.blob(full_blob_name)
    
    # Prepare data and content type based on format
    if format == "csv":
        data_to_upload = data.to_csv(index=False)
        content_type = "text/csv"
    elif format == "json":
        data_to_upload = json.dumps(data)
        content_type = "application/json"
    else:
        raise ValueError("Unsupported format")
    
    # Upload in executor to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, blob.upload_from_string, data_to_upload, content_type)
    
    return full_blob_name
```

## Timestamped file naming

For versioned uploads, append a timestamp to avoid overwriting:

```python
from datetime import datetime

def upload_with_timestamp(data, folder: str, file_name: str):
    """Upload file with timestamp suffix for versioning."""
    current_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_stem, ext = file_name.rsplit(".", 1)
    destination_blob_name = f"{folder}/{file_stem}_{current_timestamp}.{ext}"
    
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(data, content_type="text/csv")
    
    return destination_blob_name
```

## Error handling

Production services wrap GCS operations in try/except for graceful degradation:

```python
def upload_files_to_gcs(bucket_name: str, files: list):
    """Upload files with error handling."""
    try:
        # ... upload logic ...
        return True, uploaded_files
    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        return False, "Exception in uploading file to cloud"
```

Return a tuple `(success: bool, result_or_error_message)` so callers can handle failures gracefully.
