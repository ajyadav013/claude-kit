---
name: file-export-and-reporting
description: Excel/CSV generation and download endpoints in FastAPI — pandas to_excel, multi-sheet workbooks, CSV streaming, presigned GCS URLs, UploadFile parsing. Use when building report exports or file downloads.
---

Production patterns for generating and serving Excel and CSV file downloads from FastAPI endpoints, plus reading uploaded spreadsheets.

## When to use

- Building report export endpoints that return Excel (.xlsx) or CSV files
- Creating formatted multi-sheet Excel workbooks with auto-sized columns
- Implementing CSV streaming downloads for large datasets
- Handling file uploads (UploadFile) and reading Excel/CSV data from user uploads
- Returning file content as base64-encoded JSON responses
- Generating presigned GCS URLs for secure file downloads
- Building download endpoints with proper Content-Disposition headers
- Converting database query results or pandas DataFrames into downloadable reports
- Creating Excel templates with specific formatting for user downloads

## Core conventions

1. **Excel generation with openpyxl**: use `pd.ExcelWriter(output, engine='openpyxl')` with `BytesIO()` buffer. Write DataFrame via `df.to_excel(writer, sheet_name='..', index=False)`, access `writer.sheets['SheetName']` for formatting, auto-adjust column widths using `openpyxl.utils.get_column_letter()` and `worksheet.column_dimensions[letter].width`. Alternative: `engine='xlsxwriter'` for advanced formatting (charts, conditional formatting). Always `seek(0)` before reading bytes.

2. **StreamingResponse for file downloads**: return `StreamingResponse(BytesIO_content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment; filename="{filename}"'})` for Excel, or `media_type='text/csv'` for CSV. The Content-Disposition header triggers browser download with the specified filename.

3. **CSV streaming with generators**: for large CSV exports, use `io.StringIO()` with `csv.writer()` or `df.to_csv(output, index=False)`, then `output.seek(0)` and return `StreamingResponse(iter([output.getvalue()]), media_type='text/csv', headers={'Content-Disposition': ...})`. For true streaming (row-by-row), yield CSV lines from a generator function.

4. **BytesIO pattern for Excel bytes**: create `output = io.BytesIO()`, write Excel via ExcelWriter context manager, call `output.seek(0)`, then either read bytes with `output.read()` for in-memory processing or pass `output` directly to StreamingResponse. The seek(0) rewinds the buffer to the start.

5. **Base64 encoding for JSON API responses**: when returning file content in JSON (not as a download), read bytes and encode: `base64_encoded = base64.b64encode(excel_stream.read()).decode("utf-8")`, then include in response body. Set `Content-Disposition` header if the client should still trigger a download.

6. **UploadFile reading pattern**: accept `file: UploadFile = File(...)` in route, await `file_bytes = await file.read()`, then parse via `df = pd.read_excel(BytesIO(file_bytes), header=0, engine='openpyxl')` or `pd.read_csv(BytesIO(file_bytes))`. Validate required columns and handle parse errors with HTTPException. For multi-sheet workbooks, use `pd.ExcelFile(BytesIO(file_bytes))` to iterate sheets.

7. **Presigned GCS URLs**: for large files stored in GCS, generate time-limited signed URLs via `blob.generate_signed_url(version='v4', expiration=timedelta(seconds=900), method='GET', service_account_email=..., access_token=...)`. Parse `gs://bucket/path` into bucket and blob, use google.auth.default() credentials, refresh if not valid, return presigned_url to client for direct download.

8. **Content-Type headers**: Excel `.xlsx` uses `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, CSV uses `text/csv`, generic binary uses `application/octet-stream`. Always include `Content-Disposition: attachment; filename="..."` to trigger browser download (omit `attachment;` for inline display).

9. **Multi-sheet Excel workbooks**: write multiple DataFrames to separate sheets in one workbook by calling `df1.to_excel(writer, sheet_name='Sheet1')`, `df2.to_excel(writer, sheet_name='Sheet2')` within the same ExcelWriter context. Access individual sheets via `writer.sheets['SheetName']` for per-sheet formatting.

10. **Auto-adjusting column widths in openpyxl**: after writing DataFrame, iterate `for col_idx in range(1, len(df.columns) + 1)`, get column letter via `get_column_letter(col_idx)`, calculate max_length from header and cell values, set `worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)` to prevent excessive widths.

11. **Exporter factory pattern**: define `BaseExporter` abstract class with `export(records) -> bytes`, `get_content_type() -> str`, `generate_filename(count, is_all) -> str` methods. Implement `ExcelExporter`, `CSVExporter` subclasses. Use `ExporterFactory.get_exporter(format_type='excel')` to return appropriate exporter instance, allowing easy format extension.

12. **Timestamp-based filenames**: generate unique filenames with `timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")`, then `f"report_{timestamp}.xlsx"` to avoid cache collisions and track report generation time.

13. **Upload validation and error handling**: after reading uploaded file, validate expected columns with `missing = [col for col in required_columns if col not in df.columns]`, raise HTTPException(400, f"Missing columns: {missing}") if validation fails. Check `df.empty` before processing. Wrap `pd.read_excel()` in try/except to catch corrupt files.

14. **CSV from csv.writer for streaming**: when not using pandas, use `csv.writer(io.StringIO())` or yield rows via `csv.writer` over a generator. For row-by-row streaming, define `async def generate_csv(): yield header_line; for row in query: yield csv_line`, return `StreamingResponse(generate_csv(), media_type='text/csv')`.

15. **Cross-link gcs-file-storage-patterns and api-pagination-filtering-sorting**: for large reports, paginate queries before export (see api-pagination-filtering-sorting) and upload generated files to GCS (see gcs-file-storage-patterns) instead of direct streaming, then return presigned URL for download.

## Skeleton / example

```python
# Export pattern: Excel with formatting
import io
from datetime import datetime
import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl.utils import get_column_letter

router = APIRouter()

@router.get("/export/sales")
async def export_sales_report(
    start_date: str,
    end_date: str,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> StreamingResponse:
    """Export sales data as formatted Excel file."""
    dao = SalesDAO(connection_handler.session)
    records = await dao.get_sales_by_date_range(start_date, end_date)
    
    # Transform to DataFrame
    df = pd.DataFrame([
        {
            "Order ID": r.order_id,
            "Customer": r.customer_name,
            "Amount": r.total_amount,
            "Date": r.order_date.strftime("%Y-%m-%d"),
            "Status": r.status,
        }
        for r in records
    ])
    
    # Generate Excel with auto-sized columns
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Sales Report', index=False)
        
        worksheet = writer.sheets['Sales Report']
        
        # Auto-adjust column widths
        for col_idx in range(1, len(df.columns) + 1):
            column_letter = get_column_letter(col_idx)
            max_length = len(str(df.columns[col_idx - 1]))  # header length
            
            for cell in worksheet[column_letter][1:]:  # skip header
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    output.seek(0)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"sales_report_{timestamp}.xlsx"
    
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

```python
# CSV streaming download
from io import StringIO

@router.get("/export/products/csv")
async def export_products_csv(
    category: str | None = None,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> StreamingResponse:
    """Export products as CSV."""
    dao = ProductDAO(connection_handler.session)
    products = await dao.get_all_products(category=category)
    
    df = pd.DataFrame([
        {
            "SKU": p.sku,
            "Name": p.name,
            "Category": p.category,
            "Price": p.price,
            "Stock": p.stock_quantity,
        }
        for p in products
    ])
    
    output = StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"products_{timestamp}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

```python
# Upload and read Excel file
from fastapi import File, UploadFile, HTTPException
from io import BytesIO

@router.post("/upload/inventory")
async def upload_inventory(
    file: UploadFile = File(...),
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    """Process uploaded inventory Excel file."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Only Excel files (.xlsx, .xls) are allowed")
    
    try:
        file_bytes = await file.read()
        df = pd.read_excel(BytesIO(file_bytes), header=0, engine='openpyxl')
    except Exception as e:
        raise HTTPException(400, f"Failed to read Excel file: {str(e)}")
    
    # Validate required columns
    required_columns = ["sku", "quantity", "location"]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise HTTPException(400, f"Missing required columns: {', '.join(missing)}")
    
    if df.empty:
        raise HTTPException(400, "Excel file contains no data rows")
    
    # Process records
    dao = InventoryDAO(connection_handler.session)
    processed_count = 0
    
    for _, row in df.iterrows():
        await dao.update_inventory(
            sku=row['sku'],
            quantity=int(row['quantity']),
            location=row['location'],
        )
        processed_count += 1
    
    await connection_handler.session.commit()
    
    return ResponseData.ok(
        data={"processed_count": processed_count, "total_rows": len(df)},
        message="Inventory updated successfully"
    )
```

```python
# Multi-sheet Excel workbook
@router.get("/export/quarterly-report")
async def export_quarterly_report(
    quarter: str,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
) -> StreamingResponse:
    """Export quarterly report with multiple sheets."""
    sales_dao = SalesDAO(connection_handler.session)
    expense_dao = ExpenseDAO(connection_handler.session)
    
    sales_df = pd.DataFrame(await sales_dao.get_quarterly_sales(quarter))
    expense_df = pd.DataFrame(await expense_dao.get_quarterly_expenses(quarter))
    summary_df = pd.DataFrame({
        "Metric": ["Total Sales", "Total Expenses", "Profit"],
        "Amount": [
            sales_df['amount'].sum(),
            expense_df['amount'].sum(),
            sales_df['amount'].sum() - expense_df['amount'].sum(),
        ]
    })
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        sales_df.to_excel(writer, sheet_name='Sales', index=False)
        expense_df.to_excel(writer, sheet_name='Expenses', index=False)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
    
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="Q{quarter}_report.xlsx"'}
    )
```

```python
# Exporter factory pattern
from abc import ABC, abstractmethod

class BaseExporter(ABC):
    @abstractmethod
    def export(self, records: list[dict]) -> bytes:
        pass
    
    @abstractmethod
    def get_content_type(self) -> str:
        pass
    
    @abstractmethod
    def generate_filename(self, record_count: int) -> str:
        pass

class ExcelExporter(BaseExporter):
    def export(self, records: list[dict]) -> bytes:
        df = pd.DataFrame(records)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Data', index=False)
        output.seek(0)
        return output.read()
    
    def get_content_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    def generate_filename(self, record_count: int) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"export_{record_count}_records_{timestamp}.xlsx"

class CSVExporter(BaseExporter):
    def export(self, records: list[dict]) -> bytes:
        df = pd.DataFrame(records)
        output = io.StringIO()
        df.to_csv(output, index=False)
        return output.getvalue().encode('utf-8')
    
    def get_content_type(self) -> str:
        return "text/csv"
    
    def generate_filename(self, record_count: int) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"export_{record_count}_records_{timestamp}.csv"

class ExporterFactory:
    @staticmethod
    def get_exporter(format_type: str) -> BaseExporter:
        if format_type.lower() == "excel":
            return ExcelExporter()
        elif format_type.lower() == "csv":
            return CSVExporter()
        else:
            raise ValueError(f"Unsupported format: {format_type}")

# Usage in endpoint
@router.get("/export/data")
async def export_data(
    format: str = "excel",
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    records = await fetch_records(connection_handler)
    
    exporter = ExporterFactory.get_exporter(format)
    file_bytes = exporter.export(records)
    filename = exporter.generate_filename(len(records))
    
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=exporter.get_content_type(),
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
```

```python
# Presigned GCS URL for large file downloads
from google.auth import default as google_auth_default
from google.cloud import storage
from datetime import timedelta

def generate_signed_url_from_gcs_uri(gcs_uri: str, expires_seconds: int = 900) -> str:
    """Generate a presigned download URL for a GCS object."""
    # Parse gs://bucket/path
    parts = gcs_uri[5:].split("/", 1)
    bucket_name, blob_name = parts
    
    creds, project = google_auth_default()
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    
    client = storage.Client(credentials=creds, project=project)
    blob = client.bucket(bucket_name).blob(blob_name)
    
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=expires_seconds),
        method="GET",
        service_account_email=creds.service_account_email,
        access_token=creds.token,
    )

@router.get("/download/report/{report_id}")
async def get_report_download_url(
    report_id: str,
    connection_handler: ConnectionHandler = Depends(get_connection_handler),
):
    """Return presigned URL for large report download."""
    dao = ReportDAO(connection_handler.session)
    report = await dao.get_report_by_id(report_id)
    
    if not report or not report.gcs_uri:
        raise HTTPException(404, "Report not found")
    
    presigned_url = generate_signed_url_from_gcs_uri(report.gcs_uri, expires_seconds=900)
    
    return ResponseData.ok(
        data={
            "report_id": report_id,
            "filename": report.filename,
            "gcs_uri": report.gcs_uri,
            "presigned_url": presigned_url,
            "expires_in": 900,
        },
        message="Presigned URL generated"
    )
```

## Anti-patterns to avoid

1. **Forgetting `output.seek(0)` after writing**: BytesIO/StringIO buffer position is at the end after writing; read without seek(0) returns empty bytes.
2. **Not validating uploaded file columns**: always check for required columns and raise HTTPException(400) with clear error messages.
3. **Using synchronous file I/O in async routes**: all route handlers must be `async def`; use `await file.read()` for UploadFile, not blocking `.read()`.
4. **Hardcoding filenames without timestamps**: use timestamp-based filenames to avoid cache collisions and enable tracking.
5. **Missing Content-Disposition header**: omitting this header causes browser to display file inline instead of downloading.
6. **Incorrect Content-Type for Excel**: use full MIME type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, not generic `application/octet-stream`.
7. **Not handling parse errors on upload**: wrap `pd.read_excel()` in try/except and return 400 with clear error message.
8. **Returning large files directly instead of presigned URLs**: for files >10MB, upload to GCS and return presigned URL instead of streaming through the service.
9. **Using deprecated xlrd engine for .xlsx**: use `engine='openpyxl'` for .xlsx files; xlrd only supports legacy .xls format.
10. **Not limiting column width**: set `min(max_length + 2, 50)` to prevent excessively wide columns from user input.
11. **Creating DataFrames in a loop**: build list of dicts first, then create DataFrame once via `pd.DataFrame(records)` for better performance.
12. **Not setting `index=False` in to_excel/to_csv**: omitting this adds an unwanted index column to the output.

## References

- [excel-generation.md](references/excel-generation.md) — pandas ExcelWriter, openpyxl/xlsxwriter engines, multi-sheet workbooks, column formatting
- [streaming-and-downloads.md](references/streaming-and-downloads.md) — StreamingResponse patterns, CSV streaming, Content-Disposition headers, presigned URLs
- [repo-evidence.md](references/repo-evidence.md) — genericized code snippets from production services
