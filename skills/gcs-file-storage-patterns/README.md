# gcs-file-storage-patterns

Production patterns for Google Cloud Storage blob operations: uploads, downloads, signed URLs, and tabular data reads.

## What this covers

- **Client initialization** with credential refresh for long-running services
- **Single file uploads** from file objects or base64-encoded strings
- **Bulk uploads** using `transfer_manager` for parallel multi-file operations
- **Signed URL generation** with impersonated credentials for time-limited access
- **CSV and Excel reading** from GCS buckets into pandas DataFrames
- **gs:// URI parsing** and path builders for GCS and CDN URLs
- **Async wrappers** for non-blocking uploads in FastAPI/async services
- **Error handling** and graceful degradation for storage operations

## Scope

This skill focuses on **file storage operations** — uploading, downloading, and generating access URLs for blob objects in Google Cloud Storage. It is distinct from:

- **data-engineering-bigquery-gcs**: batch ETL, BigQuery load jobs, and data pipelines
- **file-export-and-reporting**: HTTP download endpoints and report generation

## Origin

These patterns derive from real production services that handle user-generated content uploads, data file processing, and secure file sharing. All examples have been genericized for public use — no internal service names, bucket names, or credentials are included.

## Usage

Use this skill when:

- Building file upload/download endpoints in a web service
- Implementing secure, time-limited file access with signed URLs
- Reading data files (CSV, Excel) from GCS for processing
- Setting up a cloud storage layer for a FastAPI or Flask application
- Migrating from local file storage to cloud object storage

See `SKILL.md` for the full conventions, examples, and anti-patterns.
