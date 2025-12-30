# PDF Support

The application now supports ingesting PDF files in addition to Excel files.

## Installation

Install the required dependency:

```bash
pip install pdfplumber
```

Or install all requirements:

```bash
pip install -r requirements.txt
```

## How It Works

### PDF Table Extraction

- PDFs are scanned for **tables** using `pdfplumber`
- Each table found in the PDF is treated as a separate "sheet" (similar to Excel sheets)
- Table names follow the pattern: `page_{N}_table_{M}` (e.g., `page_1_table_1`, `page_2_table_1`)

### Supported Operations

1. **Ingestion** (`POST /ingest`):
   - Place PDF files in your `data/` directory
   - Run `/ingest` - PDFs will be processed automatically
   - Each table becomes a queryable `raw__...` table in DuckDB

2. **Quick Upload** (`POST /quick-excel`):
   - Upload PDF files via the API
   - Tables are extracted and made available for immediate querying

## Usage

### Example: Ingest PDFs from data folder

```bash
# Place PDF files in data/ directory
cp my_report.pdf data/

# Run ingestion
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### Example: Upload PDF via API

```bash
curl -X POST http://localhost:8010/quick-excel \
  -F "question=show me top 5 items by amount" \
  -F "files=@report.pdf"
```

### Example: Query PDF data

After ingestion, you can query PDF tables like any other data:

```
Question: "show me data from page 1 table 1"
```

Or use the raw table name directly in SQL queries.

## Limitations

- **Table extraction only**: Currently extracts structured tables from PDFs
- **No text extraction**: Free-form text in PDFs is not extracted (only tabular data)
- **Table quality**: Extraction quality depends on PDF structure (works best with clearly defined tables)
- **Multi-page**: Tables spanning multiple pages may be split

## Troubleshooting

### "PDF support not available"
- Install `pdfplumber`: `pip install pdfplumber`

### "No tables found in PDF"
- The PDF may not contain structured tables
- Try opening the PDF in a viewer to verify table structure
- Some PDFs use images of tables (not extractable)

### Tables not extracting correctly
- PDFs with complex layouts or merged cells may not extract perfectly
- Consider converting PDF to Excel first if extraction fails

## Technical Details

- Uses `pdfplumber` library for table extraction
- Each extracted table becomes a DataFrame
- Same schema mapping logic applies (LLM determines sheet type)
- Raw tables are created with naming: `raw__{filename}__page_{N}_table_{M}__{hash}`

