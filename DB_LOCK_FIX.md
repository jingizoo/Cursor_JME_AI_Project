# Database Lock Fix for Concurrent Access

## Problem
When running the application on multiple ports (8010 and 8012), DuckDB database locks occurred because:
- Multiple processes were trying to access the same database file simultaneously
- DuckDB doesn't handle concurrent writes well
- Connections weren't properly configured for concurrent reads

## Solution Implemented

### 1. Read-Only Connections for Queries
Updated `src/db_store.py` to support read-only connections:

```python
def connect(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Create a DuckDB connection with proper configuration for concurrent access.
    
    Args:
        db_path: Path to DuckDB database file
        read_only: If True, opens in read-only mode (allows concurrent reads)
    """
    if read_only:
        con = duckdb.connect(db_str, config={'access_mode': 'READ_ONLY'})
    else:
        con = duckdb.connect(db_str, config={
            'access_mode': 'AUTOMATIC',
            'threads': 1,  # Single thread per connection
        })
```

### 2. Updated All Read Operations
All query/read endpoints now use `read_only=True`:

- `/ask` - Read-only connection
- `/catalog` - Read-only connection
- `/api/v1/tables` - Read-only connection
- `/api/v1/schema` - Read-only connection
- `/api/v1/table/{table_name}` - Read-only connection
- `/api/v1/query` - Read-only connection
- `/api/v1/table/{table_name}/columns` - Read-only connection
- `/ask-data` (chart_data_api) - Read-only connection
- Chart API queries - Read-only connection

### 3. Write Operations
Write operations (like `/ingest`) continue to use write connections:
- `/ingest` - Write connection (needed for data ingestion)

## How It Works

### Read-Only Mode Benefits
- **Concurrent Reads**: Multiple processes can read simultaneously
- **No Locks**: Read-only connections don't acquire write locks
- **Better Performance**: Reduced contention between services

### Write Operations
- Write operations use standard connections
- DuckDB handles write locks internally
- Only one write operation at a time (by design)

## Testing

After this fix, you should be able to:
1. Run API on port 8010: `python -m uvicorn src.api:app --host 0.0.0.0 --port 8010`
2. Run WebApp on port 8012: `python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012`
3. Make queries to both simultaneously without database locks

## Additional Notes

- **Connection Closing**: All connections are properly closed in `finally` blocks
- **Thread Safety**: Each connection uses single thread to reduce contention
- **Error Handling**: Proper error handling ensures connections are always closed

## If Issues Persist

If you still experience locks:

1. **Check for long-running queries**: Ensure queries complete quickly
2. **Verify connection closing**: All endpoints should close connections in `finally` blocks
3. **Consider connection pooling**: For high concurrency, consider implementing a connection pool
4. **Check DuckDB version**: Ensure you're using a recent version of DuckDB (0.9.0+)

## Files Modified

- `src/db_store.py` - Added read-only connection support
- `src/api.py` - Updated all read endpoints to use read-only connections
- `src/chart_data_api.py` - Updated to use read-only connections
- `src/chart_api.py` - Updated to use read-only connections

