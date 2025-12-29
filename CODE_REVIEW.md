# Code Review - JME AI Finance Pipeline

## Executive Summary

**Overall Assessment:** ✅ **Good** - The codebase is well-structured and functional, with solid architecture and security practices. Several areas for improvement identified.

**Key Strengths:**
- Clean separation of concerns
- Good SQL injection protection
- Proper error handling in most places
- Well-organized module structure

**Areas for Improvement:**
- Resource management (database connections, file handles)
- Error handling consistency
- Input validation
- Performance optimizations
- Type hints completeness

---

## 1. Architecture & Design

### ✅ Strengths
- **Modular design**: Clear separation between API, ingestion, schema mapping, and reporting
- **Single Responsibility**: Each module has a focused purpose
- **Dependency injection**: Configuration via environment variables

### ⚠️ Issues

#### 1.1 Database Connection Management
**Location:** `src/api.py`, `src/report_service.py`

**Issue:** Database connections are not explicitly closed, relying on DuckDB's automatic cleanup.

```python
# api.py:48, 57, 59
con = connect(DB_PATH)
# Connection never explicitly closed
```

**Recommendation:** Use context managers or ensure connections are closed:
```python
from contextlib import contextmanager

@contextmanager
def db_connection(db_path: Path):
    con = connect(db_path)
    try:
        yield con
    finally:
        con.close()
```

#### 1.2 Temporary File Cleanup
**Location:** `src/api.py:87`

**Issue:** Temporary directories created for reports are never cleaned up.

```python
out_dir = Path(tempfile.mkdtemp(prefix="jme_ai_reports_"))
# Directory persists after file is served
```

**Recommendation:** Use `tempfile.TemporaryDirectory` or schedule cleanup.

---

## 2. Security

### ✅ Strengths
- **SQL Injection Protection**: Uses parameterized queries throughout
- **SQL Validation**: Comprehensive validation prevents dangerous SQL operations
- **Safe SQL Deny List**: Blocks INSERT, UPDATE, DELETE, DROP, etc.

### ⚠️ Issues

#### 2.1 SQL Injection Risk (Low)
**Location:** `src/db_store.py:109`, `src/quick_excel.py:153`

**Issue:** Table names are inserted via f-strings, though they're sanitized.

```python
# db_store.py:109
con.execute(f"INSERT INTO {table} SELECT * FROM df_tmp")
# table is from internal code, but still risky

# quick_excel.py:153
con.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM df_tmp')
# tname is sanitized via _safe_name, but could be improved
```

**Recommendation:** Use DuckDB's identifier quoting or validation:
```python
def safe_table_name(name: str) -> str:
    # Validate against whitelist or use strict regex
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid table name: {name}")
    return name
```

#### 2.2 File Upload Security
**Location:** `src/api.py:70-76`

**Issue:** No file size limits or file type validation for uploads.

**Recommendation:**
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'.xlsx', '.xlsm'}

@app.post("/quick-excel")
async def quick_excel(...):
    for f in files:
        if f.size > MAX_FILE_SIZE:
            raise HTTPException(400, "File too large")
        if not Path(f.filename).suffix.lower() in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Invalid file type")
```

#### 2.3 Path Traversal Risk (Low)
**Location:** `src/api.py:42`

**Issue:** `DATA_DIR` could potentially be manipulated if environment variable is compromised.

**Recommendation:** Validate and resolve paths:
```python
DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data")).resolve()
if not DATA_DIR.is_absolute() or ".." in str(DATA_DIR):
    raise ValueError("Invalid DATA_DIR path")
```

---

## 3. Error Handling

### ✅ Strengths
- Good error collection in `ingest_folder`
- Try-except blocks in critical paths
- Error messages returned to API consumers

### ⚠️ Issues

#### 3.1 Inconsistent Error Handling
**Location:** Multiple files

**Issue:** Some functions return error dicts, others raise exceptions.

**Examples:**
- `plan_sql()` returns `{"ok": False, "error": "..."}`
- `ollama_chat()` raises exceptions (caught in `plan_sql_one`)
- `normalize_and_insert()` raises exceptions (caught in `ingest_folder`)

**Recommendation:** Standardize error handling pattern or use custom exceptions:
```python
class PipelineError(Exception):
    pass

class LLMError(PipelineError):
    pass
```

#### 3.2 Silent Failures
**Location:** `src/ingest.py:147-149`

**Issue:** Empty sheets are silently skipped without logging.

```python
if df is None or df.shape[0] == 0:
    skipped += 1
    continue  # No indication why skipped
```

**Recommendation:** Include reason in skipped count or errors list.

#### 3.3 Missing Error Context
**Location:** `src/api.py:65-66`

**Issue:** SQL execution errors don't include the full context.

**Recommendation:** Include more debugging info:
```python
except Exception as e:
    return {
        "ok": False,
        "error": f"SQL execution failed: {e}",
        "sql": sql,
        "plan_raw": plan.get("raw", ""),
        "schema": schema  # Add schema for debugging
    }
```

---

## 4. Performance

### ⚠️ Issues

#### 4.1 Inefficient DataFrame Operations
**Location:** `src/ingest.py:48-120`

**Issue:** Multiple DataFrame copies and operations could be optimized.

**Example:**
```python
df2 = df.copy()  # Full copy
# Then creates new DataFrame with column lookups
```

**Recommendation:** Use vectorized operations where possible, avoid unnecessary copies.

#### 4.2 No Connection Pooling
**Location:** All database operations

**Issue:** New connection created for each request.

**Recommendation:** Consider connection pooling for high-traffic scenarios (though DuckDB is file-based, so less critical).

#### 4.3 Large File Handling
**Location:** `src/quick_excel.py:148`

**Issue:** `max_rows_per_sheet` defaults to 20000, but entire file is read first.

**Recommendation:** Stream or read in chunks for very large files.

#### 4.4 No Caching
**Location:** `src/api.py:46-53`

**Issue:** `/catalog` endpoint queries database every time.

**Recommendation:** Add caching for frequently accessed, rarely-changing data.

---

## 5. Code Quality

### ✅ Strengths
- Consistent naming conventions
- Good use of type hints (though incomplete)
- Readable code structure

### ⚠️ Issues

#### 5.1 Missing Type Hints
**Location:** Multiple functions

**Examples:**
- `normalize_and_insert()` - missing type hints for `con` parameter
- `period_range()` - return type not specified
- `parse_num()` - has return type, but parameter type missing

**Recommendation:** Add complete type hints:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import duckdb

def normalize_and_insert(
    con: duckdb.DuckDBPyConnection,
    file: str,
    sheet: str,
    sheet_type: str,
    mapping: Dict[str, Any],
    df: pd.DataFrame
) -> None:
```

#### 5.2 Magic Numbers
**Location:** Multiple files

**Examples:**
- `max_scan: int = 25` - why 25?
- `limit: int = 200` - why 200?
- `opening_cash: float = 1500000.0` - what currency?

**Recommendation:** Use named constants:
```python
DEFAULT_HEADER_SCAN_ROWS = 25
DEFAULT_QUERY_LIMIT = 200
DEFAULT_OPENING_CASH_INR = 1500000.0
```

#### 5.3 Code Duplication
**Location:** `src/planner_agent.py` and `src/quick_excel.py`

**Issue:** `get_schema()` and `validate_sql()` are duplicated.

**Recommendation:** Extract to shared utility module.

#### 5.4 Inconsistent String Formatting
**Location:** Various files

**Issue:** Mix of f-strings and `.format()` or `%` formatting.

**Recommendation:** Standardize on f-strings (Python 3.6+).

---

## 6. Data Validation

### ⚠️ Issues

#### 6.1 Missing Input Validation
**Location:** `src/api.py:32-34`

**Issue:** No validation for `period` format or `opening_cash` range.

```python
class ReportReq(BaseModel):
    period: str  # Should validate YYYY-MM format
    opening_cash: float = 1500000.0  # No min/max validation
```

**Recommendation:**
```python
from pydantic import validator, Field

class ReportReq(BaseModel):
    period: str = Field(..., regex=r'^\d{4}-\d{2}$')
    opening_cash: float = Field(1500000.0, ge=0, le=1e10)
```

#### 6.2 Question Length Validation
**Location:** `src/api.py:29-30`

**Issue:** No limit on question length for `/ask` endpoint.

**Recommendation:**
```python
class AskReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
```

---

## 7. Testing & Documentation

### ⚠️ Issues

#### 7.1 No Unit Tests
**Issue:** No test files found in project.

**Recommendation:** Add tests for:
- SQL validation logic
- Number parsing (`parse_num`)
- Schema mapping
- Error handling paths

#### 7.2 Missing Docstrings
**Location:** Most functions

**Issue:** Functions lack docstrings explaining parameters, returns, and behavior.

**Recommendation:** Add docstrings following Google or NumPy style:
```python
def parse_num(x: Any) -> Optional[float]:
    """
    Parse a numeric value from various string formats.
    
    Handles formats like:
    - Plain numbers: "1234.56"
    - With commas: "1,234.56"
    - Negative in parentheses: "(1234.56)"
    
    Args:
        x: Input value (string, number, or None)
        
    Returns:
        Parsed float value or None if parsing fails
    """
```

#### 7.3 API Documentation
**Issue:** FastAPI auto-generates docs, but request/response examples would help.

**Recommendation:** Add example values to Pydantic models:
```python
class AskReq(BaseModel):
    question: str
    
    class Config:
        schema_extra = {
            "example": {
                "question": "What is the total revenue for January 2024?"
            }
        }
```

---

## 8. Specific Bugs & Edge Cases

### 🐛 Potential Bugs

#### 8.1 Empty DataFrame Handling
**Location:** `src/ingest.py:147`

**Issue:** `df.shape[0] == 0` check happens after `read_sheet()`, but `read_sheet()` might return empty DataFrame with columns.

**Recommendation:** Check both rows and meaningful columns.

#### 8.2 Date Handling Edge Cases
**Location:** `src/report_service.py:18`

**Issue:** `prev = (pd.Period(period,'M')-1).strftime('%Y-%m')` - what if period is "0001-01"?

**Recommendation:** Add validation for valid date ranges.

#### 8.3 Bank Reconciliation Logic
**Location:** `src/report_service.py:104-113`

**Issue:** Matching by amount only (rounded to 2 decimals) could cause false matches.

**Recommendation:** Consider additional matching criteria (date proximity, reference).

#### 8.4 Column Name Collision
**Location:** `src/quick_excel.py:46-57`

**Issue:** Column name deduplication logic could still create collisions if base name ends with `_N`.

**Recommendation:** Use UUID suffix or better collision detection.

---

## 9. Recommendations Priority

### 🔴 High Priority
1. **Add input validation** for API endpoints (period format, file size, etc.)
2. **Close database connections** explicitly or use context managers
3. **Add file size limits** for uploads
4. **Clean up temporary files** after report generation

### 🟡 Medium Priority
1. **Standardize error handling** pattern across modules
2. **Add comprehensive type hints**
3. **Extract duplicate code** (`get_schema`, `validate_sql`)
4. **Add logging** for debugging and monitoring
5. **Add unit tests** for critical functions

### 🟢 Low Priority
1. **Performance optimizations** (caching, connection pooling)
2. **Enhanced documentation** (docstrings, API examples)
3. **Code style improvements** (constants, formatting)
4. **Enhanced error messages** with more context

---

## 10. Positive Highlights

### ✨ Excellent Practices

1. **SQL Safety**: Comprehensive validation prevents SQL injection
2. **Modularity**: Clean separation of concerns
3. **Configuration**: Environment-based configuration
4. **Error Reporting**: Good error collection and reporting
5. **Data Normalization**: Well-structured canonical schema
6. **LLM Integration**: Clean abstraction of Ollama calls
7. **Excel Handling**: Robust header detection and column normalization

---

## Conclusion

The codebase demonstrates **solid engineering practices** with a clean architecture and good security awareness. The main areas for improvement are **resource management**, **input validation**, and **error handling consistency**. With the recommended fixes, this would be production-ready.

**Estimated effort for fixes:**
- High priority: 4-6 hours
- Medium priority: 8-12 hours  
- Low priority: 4-8 hours

**Overall Grade: B+** (Good, with clear path to excellent)

