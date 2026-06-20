# Streaming and Download Patterns

Production patterns for serving file downloads via FastAPI StreamingResponse.

## Excel download with StreamingResponse

```python
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import io
import pandas as pd

router = APIRouter()

@router.get("/export/report")
async def download_report(
    start_date: str,
    end_date: str,
) -> StreamingResponse:
    """Download formatted Excel report."""
    # Fetch and transform data
    records = await fetch_records(start_date, end_date)
    df = pd.DataFrame(records)
    
    # Generate Excel bytes
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Report', index=False)
    
    output.seek(0)
    
    # Timestamp-based filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.xlsx"
    
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

## CSV download with StringIO

```python
from io import StringIO

@router.get("/export/products/csv")
async def download_products_csv() -> StreamingResponse:
    """Download products as CSV."""
    products = await fetch_products()
    df = pd.DataFrame(products)
    
    output = StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="products.csv"'}
    )
```

## CSV streaming with generator (row-by-row)

```python
import csv
from io import StringIO

async def generate_csv_rows(records: list[dict]):
    """Generate CSV rows one at a time."""
    if not records:
        return
    
    # Yield header
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=records[0].keys())
    writer.writeheader()
    yield output.getvalue()
    
    # Yield data rows
    for record in records:
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=record.keys())
        writer.writerow(record)
        yield output.getvalue()

@router.get("/export/large-dataset")
async def stream_large_csv():
    """Stream large CSV file row by row."""
    records = await fetch_large_dataset()
    
    return StreamingResponse(
        generate_csv_rows(records),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="dataset.csv"'}
    )
```

## Content-Type and Content-Disposition headers

### Content-Type (media_type)

- Excel `.xlsx`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- CSV: `text/csv`
- Generic binary: `application/octet-stream`
- JSON: `application/json`

### Content-Disposition

- **Attachment (triggers download)**: `attachment; filename="report.xlsx"`
- **Inline (display in browser)**: `inline; filename="report.pdf"`
- Filename encoding for special chars: `attachment; filename*=UTF-8''report%20file.xlsx`

```python
# Force download
headers={'Content-Disposition': 'attachment; filename="report.xlsx"'}

# Display inline (PDFs, images)
headers={'Content-Disposition': 'inline; filename="document.pdf"'}
```

## Presigned GCS URLs for large files

```python
from google.auth import default as google_auth_default
from google.cloud import storage
from datetime import timedelta
from google.auth.transport import requests as google_auth_requests

def generate_signed_url_from_gcs_uri(gcs_uri: str, expires_seconds: int = 900) -> str:
    """
    Generate presigned download URL for a GCS object.
    
    Args:
        gcs_uri: GCS path in format gs://bucket/path/to/file
        expires_seconds: URL expiration time (default 15 minutes)
    
    Returns:
        Presigned URL string
    """
    # Parse gs://bucket/path
    parts = gcs_uri[5:].split("/", 1)
    bucket_name, blob_name = parts
    
    # Get credentials
    creds, project = google_auth_default()
    if not creds.valid:
        creds.refresh(google_auth_requests.Request())
    
    # Generate signed URL
    client = storage.Client(credentials=creds, project=project)
    blob = client.bucket(bucket_name).blob(blob_name)
    
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=expires_seconds),
        method="GET",
        service_account_email=creds.service_account_email,
        access_token=creds.token,
    )
```

### Presigned URL endpoint pattern

```python
from pydantic import BaseModel

class PresignedUrlResponse(BaseModel):
    filename: str
    gcs_uri: str
    presigned_url: str
    expires_in: int

@router.get("/download/report/{report_id}")
async def get_report_download_url(report_id: str) -> PresignedUrlResponse:
    """Return presigned URL for report download."""
    report = await fetch_report(report_id)
    
    if not report or not report.gcs_uri:
        raise HTTPException(404, "Report not found")
    
    presigned_url = generate_signed_url_from_gcs_uri(
        report.gcs_uri,
        expires_seconds=900
    )
    
    return PresignedUrlResponse(
        filename=report.filename,
        gcs_uri=report.gcs_uri,
        presigned_url=presigned_url,
        expires_in=900,
    )
```

## Base64 encoding for JSON API responses

```python
import base64

@router.post("/export/base64")
async def export_as_base64() -> dict:
    """Return Excel file as base64-encoded JSON."""
    records = await fetch_records()
    df = pd.DataFrame(records)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Data', index=False)
    
    output.seek(0)
    base64_content = base64.b64encode(output.read()).decode("utf-8")
    
    return {
        "filename": "export.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "base64_content": base64_content,
    }
```

## Server-Sent Events (SSE) for progress streaming

```python
import json

@router.get("/export/stream-progress")
async def export_with_progress():
    """Stream export progress via SSE."""
    async def event_stream():
        total = await get_total_count()
        processed = 0
        
        for chunk in fetch_chunks():
            # Process chunk
            await process_chunk(chunk)
            processed += len(chunk)
            
            # Yield progress event
            progress = {
                "processed": processed,
                "total": total,
                "percent": (processed / total) * 100
            }
            yield f"data: {json.dumps(progress)}\n\n"
        
        # Final event
        yield f"data: {json.dumps({'status': 'complete'})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

## Timestamp-based filenames

```python
from datetime import datetime

def generate_filename(prefix: str, extension: str, suffix: str = "") -> str:
    """Generate timestamped filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if suffix:
        return f"{prefix}_{suffix}_{timestamp}.{extension}"
    return f"{prefix}_{timestamp}.{extension}"

# Usage
filename = generate_filename("sales_report", "xlsx", suffix="Q1")
# Result: sales_report_Q1_20260620_143022.xlsx
```

## Response patterns comparison

| Pattern | Use Case | Pros | Cons |
|---------|----------|------|------|
| **StreamingResponse with BytesIO** | Small-medium files (<50MB) | Simple, direct download | Memory overhead |
| **Presigned GCS URL** | Large files (>50MB) | No service memory/bandwidth, scalable | Requires GCS, two-step (upload + URL) |
| **Base64 in JSON** | Browser-based apps, small files | Works with JSON APIs | 33% size overhead, not for large files |
| **Row-by-row CSV streaming** | Very large datasets | Constant memory | More complex, limited to CSV |

## When to use presigned URLs vs direct streaming

**Use presigned URLs when:**
- File size >50MB
- High concurrent download load
- File is already in GCS
- Download bandwidth costs matter
- Client can handle redirect/two-step flow

**Use direct streaming when:**
- File size <50MB
- File generated on-the-fly
- Simpler client implementation needed
- Download authentication required at request time
- Low concurrent download volume

## Common pitfalls

1. **Missing `seek(0)`**: always rewind buffer before reading or passing to StreamingResponse
2. **Wrong Content-Type**: use full MIME type for Excel, not generic `application/octet-stream`
3. **No timestamp in filename**: causes cache collisions and makes tracking difficult
4. **Streaming large files through service**: use presigned URLs instead to avoid memory/bandwidth issues
5. **Not handling expired presigned URLs**: client should handle 403 and request new URL
