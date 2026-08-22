# Signed URLs and Data Reads

## Signed URL generation with impersonated credentials

In GKE or Cloud Run environments, the default application credentials often lack signing permissions. Use impersonated credentials with a service account that has `iam.serviceAccounts.signBlob`:

```python
from datetime import datetime, timedelta
from google.auth.impersonated_credentials import Credentials
from google.cloud import storage

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

def generate_signed_url(
    bucket_name: str,
    file_name: str,
    service_account_email: str,
    exp_minutes: int = 60,
) -> str:
    """Generate a signed URL with impersonated credentials for time-limited access."""
    # Get source credentials
    source_credentials, _ = google.auth.default()
    if not source_credentials.valid:
        source_credentials.refresh(google.auth.transport.requests.Request())
    
    # Create impersonated credentials
    target_credentials = Credentials(
        source_credentials=source_credentials,
        target_principal=service_account_email,
        target_scopes=SCOPES,
    )
    
    # Generate signed URL
    client = storage.Client(credentials=target_credentials)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    
    signed_url = blob.generate_signed_url(
        expiration=datetime.now() + timedelta(minutes=exp_minutes),
        credentials=target_credentials,
    )
    
    return signed_url
```

## Signed URL generation with direct service account credentials (v4)

For environments with direct service account credentials:

```python
def generate_signed_urls(
    resource_urls: Union[List[str], str],
    bucket_name: str,
    credentials,
    expiration_time: int,  # seconds
    sign_method: str = "GET",
):
    """Generate v4 signed URLs for multiple resources."""
    if isinstance(resource_urls, str):
        resource_urls = [resource_urls]
    
    bucket = client.bucket(bucket_name)
    signed_urls = []
    
    for resource_url in resource_urls:
        blob = bucket.blob(resource_url)
        signed_url = blob.generate_signed_url(
            version="v4",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
            expiration=expiration_time,
            method=sign_method,  # GET, PUT, POST
        )
        signed_urls.append(signed_url)
    
    return signed_urls
```

## Reading CSV files from GCS

```python
import io
import pandas as pd
from google.cloud import storage

def read_csv_from_gcs(bucket_name: str, file_path: str) -> pd.DataFrame:
    """Read a CSV file from GCS and return as DataFrame."""
    client = storage.Client(credentials=_auth())
    bucket = client.bucket(bucket_name)
    blob = bucket.get_blob(file_path)
    
    if not blob:
        raise ValueError(f"File {file_path} not found in bucket {bucket_name}")
    
    csv_data = blob.download_as_string()
    df = pd.read_csv(io.BytesIO(csv_data), keep_default_na=False)
    
    # Clean unnamed columns (pandas adds these for empty headers)
    df.columns = ["" if col.startswith("Unnamed") else col for col in df.columns]
    
    return df
```

## Reading multiple CSV files with a prefix

```python
def read_csvs_with_prefix(
    bucket_name: str,
    prefix: str,
    dtype: Optional[Dict] = None,
) -> pd.DataFrame:
    """Read all CSV files from a GCS bucket with a given prefix and combine them."""
    client = storage.Client(credentials=_auth())
    bucket = client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix)
    
    dataframes = []
    for blob in blobs:
        if blob.name.endswith(".csv"):
            csv_data = blob.download_as_string()
            df = pd.read_csv(io.BytesIO(csv_data), dtype=dtype)
            dataframes.append(df)
    
    if not dataframes:
        raise ValueError(f"No CSV files found with prefix '{prefix}' in bucket '{bucket_name}'")
    
    combined_df = pd.concat(dataframes, ignore_index=True)
    return combined_df
```

## Reading Excel files from GCS

```python
def read_excel_from_gcs(bucket_name: str, file_path: str) -> dict:
    """Read an Excel file from GCS and return dict of sheet_name -> DataFrame."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    
    excel_data = blob.download_as_bytes()
    
    with io.BytesIO(excel_data) as excel_buffer:
        excel_sheets = pd.read_excel(excel_buffer, sheet_name=None, engine="openpyxl")
    
    return excel_sheets
```

## Downloading files as bytes or base64

For binary files (images, PDFs):

```python
import base64

def download_files_from_gcs(bucket_name: str, filenames: list):
    """Download files from GCS and return as base64-encoded strings."""
    bucket = storage_client.bucket(bucket_name)
    download_images = {}
    
    for filename in filenames:
        blob = bucket.blob(filename)
        if not blob.exists():
            download_images[filename] = None
        else:
            image_bytes = blob.download_as_bytes()
            download_images[filename] = base64.b64encode(image_bytes).decode('utf-8')
    
    return download_images
```

## gs:// URI parsing

To extract bucket and blob path from a gs:// URI:

```python
def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse gs://bucket/path URI into (bucket_name, blob_path)."""
    if not uri.startswith("gs://"):
        raise ValueError("URI must start with gs://")
    
    no_scheme = uri[len("gs://"):]
    parts = no_scheme.split("/", 1)
    
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid GCS URI format: must be gs://bucket/path")
    
    bucket_name, blob_path = parts[0], parts[1]
    return bucket_name, blob_path
```

Example usage:

```python
uri = "gs://my-bucket/data/file.csv"
bucket_name, blob_path = parse_gcs_uri(uri)  # ("my-bucket", "data/file.csv")
```

## Building gs:// paths

To construct a gs:// URI from bucket and blob path:

```python
def build_gcs_path(bucket_name: str, file_path: str) -> str:
    """Build gs:// URI from bucket and blob path."""
    return f"gs://{bucket_name}/{file_path.strip('/')}"
```

## Building CDN URLs

For public assets served via CDN:

```python
def build_cdn_url(bucket_name: str, file_path: str, domain: str) -> str:
    """Build public CDN URL from bucket and blob path."""
    return f"https://assets.{domain}/{bucket_name}/{file_path}"
```

Example:

```python
cdn_url = build_cdn_url("images-bucket", "uploads/photo.jpg", "example.com")
# "https://assets.example.com/images-bucket/uploads/photo.jpg"
```

## Reading text files (YAML, JSON, Markdown)

```python
import yaml
import json

def read_text_file_from_gcs(uri: str):
    """Read a text file from GCS given a gs:// URI."""
    bucket_name, blob_path = parse_gcs_uri(uri)
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    content = blob.download_as_text()
    return content

def read_yaml_from_gcs(uri: str):
    """Read and parse a YAML file from GCS."""
    content = read_text_file_from_gcs(uri)
    return yaml.safe_load(content)

def read_json_from_gcs(uri: str):
    """Read and parse a JSON file from GCS."""
    content = read_text_file_from_gcs(uri)
    return json.loads(content)
```

## Blob existence check

Before downloading, check if a blob exists to avoid exceptions:

```python
def download_if_exists(bucket_name: str, file_path: str):
    """Download a file only if it exists."""
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    
    if not blob.exists():
        return None
    
    return blob.download_as_bytes()
```
