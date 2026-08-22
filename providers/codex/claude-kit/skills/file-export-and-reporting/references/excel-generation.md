# Excel Generation Patterns

Production patterns for generating Excel files with pandas, openpyxl, and xlsxwriter.

## Basic Excel export with openpyxl

```python
import io
import pandas as pd
from openpyxl.utils import get_column_letter

def generate_excel_report(records: list[dict]) -> bytes:
    """Generate Excel file from records with auto-sized columns."""
    df = pd.DataFrame(records)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Report', index=False)
        
        worksheet = writer.sheets['Report']
        
        # Auto-adjust column widths
        for col_idx in range(1, len(df.columns) + 1):
            column_letter = get_column_letter(col_idx)
            max_length = len(str(df.columns[col_idx - 1]))  # header
            
            for row in worksheet.iter_rows(min_col=col_idx, max_col=col_idx, min_row=2):
                for cell in row:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
            
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    return output.read()
```

## Multi-sheet workbooks

```python
def generate_multi_sheet_report(
    sales_data: list[dict],
    expense_data: list[dict],
    summary_data: list[dict],
) -> bytes:
    """Generate Excel workbook with multiple sheets."""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame(sales_data).to_excel(writer, sheet_name='Sales', index=False)
        pd.DataFrame(expense_data).to_excel(writer, sheet_name='Expenses', index=False)
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
    
    output.seek(0)
    return output.read()
```

## Engine choice: openpyxl vs xlsxwriter

- **openpyxl**: read and write .xlsx files, modify existing workbooks, access worksheet objects for post-write formatting
- **xlsxwriter**: write-only, better performance, richer formatting options (charts, conditional formatting, data validation)

```python
# openpyxl for formatting after write
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='Data', index=False)
    worksheet = writer.sheets['Data']
    worksheet.column_dimensions['A'].width = 20

# xlsxwriter for advanced features (write-only)
with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
    df.to_excel(writer, sheet_name='Data', index=False)
    workbook = writer.book
    worksheet = writer.sheets['Data']
    
    # Add chart, conditional formatting, etc.
    chart = workbook.add_chart({'type': 'column'})
    worksheet.insert_chart('F2', chart)
```

## BytesIO buffering pattern

```python
# Standard pattern
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='Sheet1', index=False)

output.seek(0)  # CRITICAL: rewind buffer to start
file_bytes = output.read()

# OR pass to StreamingResponse without reading
output.seek(0)
return StreamingResponse(output, media_type='...', headers={'Content-Disposition': '...'})
```

## Formatting patterns

### Auto-sized columns with max width cap

```python
for col_idx in range(1, len(df.columns) + 1):
    column_letter = get_column_letter(col_idx)
    
    # Start with header length
    max_length = len(df.columns[col_idx - 1])
    
    # Check all cell values in column
    for cell in worksheet[column_letter][1:]:  # skip header
        try:
            if cell.value is not None:
                cell_length = len(str(cell.value))
                max_length = max(max_length, cell_length)
        except:
            pass
    
    # Cap at 50 to prevent excessive widths
    adjusted_width = min(max_length + 2, 50)
    worksheet.column_dimensions[column_letter].width = adjusted_width
```

### Date formatting

```python
from openpyxl.styles import numbers

# Format date column
for row in worksheet.iter_rows(min_row=2, min_col=4, max_col=4):
    for cell in row:
        cell.number_format = numbers.FORMAT_DATE_XLSX14  # mm-dd-yy
```

## Reading uploaded Excel files

```python
from io import BytesIO
from fastapi import UploadFile, HTTPException

async def read_excel_upload(file: UploadFile) -> pd.DataFrame:
    """Read and validate uploaded Excel file."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Only Excel files allowed")
    
    try:
        file_bytes = await file.read()
        df = pd.read_excel(BytesIO(file_bytes), header=0, engine='openpyxl')
    except Exception as e:
        raise HTTPException(400, f"Failed to parse Excel: {str(e)}")
    
    if df.empty:
        raise HTTPException(400, "Excel file contains no data")
    
    return df
```

## Multi-sheet reading

```python
async def read_multi_sheet_excel(file: UploadFile) -> dict[str, pd.DataFrame]:
    """Read all sheets from uploaded Excel file."""
    file_bytes = await file.read()
    excel_file = pd.ExcelFile(BytesIO(file_bytes), engine='openpyxl')
    
    sheets = {}
    for sheet_name in excel_file.sheet_names:
        sheets[sheet_name] = excel_file.parse(sheet_name)
    
    return sheets
```

## Column validation

```python
def validate_excel_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    """Validate required columns exist."""
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise HTTPException(400, f"Missing columns: {', '.join(missing)}")
```

## Performance tips

1. Build list of dicts, then create DataFrame once: `pd.DataFrame(records)` instead of appending rows
2. Use `index=False` to skip writing row indices
3. For very large files (>100K rows), consider chunked processing or background jobs
4. openpyxl is slower but more flexible; xlsxwriter is faster for write-only operations

## Common issues

- **Deprecated xlrd for .xlsx**: use `engine='openpyxl'` for .xlsx files; xlrd only supports legacy .xls
- **Missing `seek(0)`**: reading from BytesIO without seek(0) returns empty bytes
- **Detached cells after context exit**: access `writer.sheets` inside the `with` block, not after
- **Column width not applied**: ensure you're iterating 1-based column indices and using correct sheet reference
