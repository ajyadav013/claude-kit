# File Export and Reporting

Production patterns for generating Excel and CSV file downloads from FastAPI services, handling spreadsheet uploads, and serving formatted reports.

## What this covers

- **Excel generation**: pandas `to_excel` with openpyxl/xlsxwriter, multi-sheet workbooks, auto-sized columns, cell formatting
- **CSV streaming**: StreamingResponse with generators, StringIO buffering, row-by-row streaming
- **File downloads**: Content-Disposition headers, timestamp-based filenames, proper MIME types
- **File uploads**: UploadFile handling, reading Excel/CSV data, validation, error handling
- **Binary responses**: BytesIO buffering, base64 encoding for JSON APIs
- **Presigned URLs**: GCS signed URLs for large file downloads, time-limited access
- **Exporter patterns**: Factory pattern for format-agnostic export, BaseExporter abstraction

## Origin

This skill derives from real production FastAPI services handling reporting, data export, and file upload workflows. All patterns are genericized—no internal service names, repository paths, or proprietary details are included.

## When to use

Use this skill when:
- Building report export endpoints that return Excel or CSV files
- Creating formatted multi-sheet Excel reports with auto-adjusted columns
- Implementing file upload endpoints that read and validate spreadsheet data
- Generating presigned download URLs for large files stored in GCS
- Converting database query results into downloadable reports
- Setting up data import workflows from user-uploaded Excel files

## Cross-links

- **fastapi-service-patterns**: for ResponseData envelope, ConnectionHandler DI, route structure
- **gcs-file-storage-patterns**: for uploading generated reports to GCS before returning presigned URLs
- **api-pagination-filtering-sorting**: for paginating large datasets before export

## Not covered

- Binary file formats other than Excel/CSV (PDFs, images, zip archives)
- Real-time streaming of very large datasets (consider chunked downloads or background jobs)
- Excel advanced features (charts, pivot tables, macros)
- Authentication/authorization for download endpoints (see auth patterns in fastapi-service-patterns)
