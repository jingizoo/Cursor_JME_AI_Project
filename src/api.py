import os
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .db_store import connect
from .ingest import ingest_folder
from .planner_agent import plan_sql, get_schema, validate_sql
from .quick_excel import quick_excel_query
from .report_service import generate_report_pack

def df_to_records_safe(df: pd.DataFrame):
    """Convert DataFrame to records, replacing NaN/Inf with None for JSON serialization."""
    # Make a copy to avoid modifying original
    df = df.copy()
    # Replace +/-inf with NaN first
    df = df.replace([np.inf, -np.inf], np.nan)
    # Replace all NaN values with None (more robust than where/notnull)
    df = df.fillna(value=None)
    # Convert to dict - any remaining NaN will be caught by explicit None replacement
    records = df.to_dict(orient="records")
    # Final pass: recursively replace any remaining NaN/Inf in nested structures
    def clean_value(v):
        # Check for NaN/Inf in float or numpy numeric types
        try:
            if isinstance(v, (float, np.floating, np.number)):
                if np.isnan(v) or np.isinf(v):
                    return None
        except (TypeError, ValueError):
            pass  # Not a numeric type, continue
        if isinstance(v, dict):
            return {k: clean_value(val) for k, val in v.items()}
        elif isinstance(v, (list, tuple)):
            return [clean_value(item) for item in v]
        return v
    return [clean_value(r) for r in records]

_DB_MTIME_CACHE: float | None = None
_TABLE_INFO_CACHE: dict[str, list[dict[str, str]]] = {}
_PLAN_CACHE: dict[tuple[str, str], dict[str, str]] = {}  # Cache SQL plans by (question, model)

def _maybe_invalidate_schema_cache() -> None:
    global _DB_MTIME_CACHE, _TABLE_INFO_CACHE, _PLAN_CACHE
    try:
        mtime = DB_PATH.stat().st_mtime
    except Exception:
        mtime = None
    if _DB_MTIME_CACHE != mtime:
        _DB_MTIME_CACHE = mtime
        _TABLE_INFO_CACHE = {}
        _PLAN_CACHE = {}  # Invalidate plan cache when DB changes

def _get_table_info_cached(con, table: str, max_cols: int = None) -> list[dict[str, str]]:
    """
    Get table info with optional column limit to reduce prompt size.
    If max_cols is None, includes all columns.
    For very large tables, set max_cols to limit to first N columns.
    """
    _maybe_invalidate_schema_cache()
    cache_key = (table, max_cols)
    cached = _TABLE_INFO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cols = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    # Limit columns to reduce prompt size (most important columns are usually first)
    if max_cols:
        cols = cols[:max_cols]
    out = [{"name": c[1], "type": c[2]} for c in cols]
    _TABLE_INFO_CACHE[cache_key] = out
    return out

def _schema_for_llm(con, question: str, max_tables: int = None, max_cols_per_table: int = None) -> dict:
    """
    Build schema payload for the LLM. Includes ALL tables dynamically by default.
    Can be limited via environment variables for performance.
    
    Args:
        con: DuckDB connection
        question: User question (used for relevance matching)
        max_tables: Maximum number of tables to include (None = all tables, configurable via JME_MAX_TABLES env var)
        max_cols_per_table: Maximum columns per table (None = all columns, configurable via JME_MAX_COLS env var)
    """
    import os
    
    # Get limits from environment variables or use defaults
    if max_tables is None:
        max_tables = int(os.getenv("JME_MAX_TABLES", "0"))  # 0 means unlimited/all tables
        if max_tables == 0:
            max_tables = None  # None means include all
    
    if max_cols_per_table is None:
        max_cols_per_table = int(os.getenv("JME_MAX_COLS", "50"))  # Default 50 columns per table
    
    # Get all existing tables
    existing_tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    existing_set = set(existing_tables)
    
    # Filter out registry/metadata tables (keep them separate, don't send to LLM)
    registry_tables = {"schema_registry", "raw_sheet_registry"}
    data_tables = [t for t in existing_tables if t not in registry_tables]
    
    question_lower = (question or "").lower()
    
    # Check if question explicitly mentions any table names
    explicitly_mentioned = []
    for tname in data_tables:
        if tname.lower() in question_lower:
            explicitly_mentioned.append(tname)
    
    # If max_tables is set, prioritize: explicitly mentioned > raw tables > canonical tables
    if max_tables and len(data_tables) > max_tables:
        # Always include explicitly mentioned tables
        selected = list(explicitly_mentioned)
        
        # Then add raw tables (most recent first)
        raw_tables = [t for t in data_tables if t.startswith("raw_") and t not in selected]
        if "raw_sheet_registry" in existing_set:
            try:
                rows = con.execute(
                    "SELECT raw_table FROM raw_sheet_registry ORDER BY updated_ts DESC"
                ).fetchall()
                ordered_raw = [r[0] for r in rows if r and r[0] and r[0] in raw_tables]
                # Add ordered raw tables
                for t in ordered_raw:
                    if t not in selected and len(selected) < max_tables:
                        selected.append(t)
            except Exception:
                pass
        
        # Then add canonical tables
        canonical_tables = ["invoices", "payments", "expenses", "bank_txns"]
        for t in canonical_tables:
            if t in existing_set and t not in selected and len(selected) < max_tables:
                selected.append(t)
        
        # Finally, add any remaining tables
        for t in data_tables:
            if t not in selected and len(selected) < max_tables:
                selected.append(t)
    else:
        # Include ALL tables (no limit)
        selected = data_tables
    
    # Build schema with all selected tables
    tables: dict[str, list[dict[str, str]]] = {}
    for t in selected:
        # For explicitly mentioned tables, include more columns if limit is set
        if t.lower() in question_lower and max_cols_per_table:
            # Include more columns for tables mentioned in question
            tables[t] = _get_table_info_cached(con, t, max_cols=max_cols_per_table * 2)
        else:
            # Use configured limit or None (all columns)
            tables[t] = _get_table_info_cached(con, t, max_cols=max_cols_per_table)

    return {"tables": tables}

def _tables_preview(con, max_tables: int = 30) -> List[str]:
    try:
        rows = con.execute("SHOW TABLES").fetchall()
        names = [r[0] for r in rows]
        return names[:max_tables]
    except Exception:
        return []

def _build_no_answer_hint(*, con, question: str, sql: str = "", error: str = "", empty: bool = False) -> str:
    tables = _tables_preview(con)
    raw_tables = [t for t in tables if t.startswith("raw__")]

    if empty:
        msg = "Query ran but returned 0 rows. Your filters may be too strict (dates/joins), or the data isn't in the expected table yet."
        if raw_tables:
            msg += f" I also see raw ingested sheet tables available (example: `{raw_tables[0]}`)."
        if tables:
            msg += " Check available tables via `/api/v1/tables` and columns via `/api/v1/schema`."
        return msg

    err = (error or "").lower()
    if "does not exist" in err or "table with name" in err:
        msg = "It looks like the SQL referenced a table that doesn't exist in DuckDB yet."
        if raw_tables:
            msg += f" You *do* have raw ingested sheet tables (example: `{raw_tables[0]}`), so try asking using the exact column names from those tables."
        msg += " You can inspect tables via `/api/v1/tables` and columns via `/api/v1/table/<table>/columns`."
        return msg

    if "column" in err and ("not found" in err or "binder" in err):
        msg = "It looks like the SQL referenced a column that doesn't exist (or needs quoting)."
        msg += " Inspect columns via `/api/v1/table/<table>/columns` (or `/api/v1/schema`) and then re-ask using the exact column names."
        return msg

    msg = "The query failed to run. Check that ingestion created the needed tables/columns, then re-ask with more specific column/table hints."
    if tables:
        msg += f" Available tables (preview): {tables[:10]}"
    return msg

DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data"))
CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pipeline.duckdb"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))  # Default 5 minutes (300 seconds)

app = FastAPI(title="JME AI Finance Pipeline (Dynamic Excel)")

# Enable CORS for Superset integration
# Configure allowed origins based on your environment
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IngestReq(BaseModel):
    force: bool = False
    wiki_urls: Optional[List[str]] = None  # List of wiki page URLs to ingest
    wiki_api_key: Optional[str] = None  # Optional API key for private wikis

class AskReq(BaseModel):
    question: str

class ReportReq(BaseModel):
    period: str  # YYYY-MM
    opening_cash: float = 1500000.0

@app.get("/health")
def health():
    return {"ok": True, "data_dir": str(DATA_DIR), "ollama_url": OLLAMA_URL, "ollama_model": OLLAMA_MODEL}

@app.post("/ingest")
def ingest(req: IngestReq):
    if not DATA_DIR.exists():
        return {"ok": False, "error": f"DATA_DIR not found: {DATA_DIR.resolve()}"}
    return ingest_folder(
        data_dir=DATA_DIR,
        db_path=DB_PATH,
        base_url=OLLAMA_URL,
        model=OLLAMA_MODEL,
        force=req.force,
        wiki_urls=req.wiki_urls,
        wiki_api_key=req.wiki_api_key
    )

@app.get("/catalog")
def catalog():
    con = connect(DB_PATH, read_only=True)
    try:
        rows = con.execute("SELECT file, sheet, sheet_type, confidence, notes, updated_ts FROM schema_registry ORDER BY updated_ts DESC").fetchall()
        out = []
        for r in rows:
            out.append({"file": r[0], "sheet": r[1], "sheet_type": r[2], "confidence": float(r[3] or 0), "notes": r[4] or "", "updated_ts": r[5]})
        return {"ok": True, "mappings": out}
    finally:
        con.close()

@app.post("/ask")
def ask(req: AskReq):
    """
    Ask a natural language question and get SQL results.
    Includes timing information and plan caching for performance.
    """
    start_time = time.time()
    timings = {}
    
    # Use read-only connection for queries to allow concurrent access
    con = connect(DB_PATH, read_only=True)
    try:
        # Build schema (with timing)
        t0 = time.time()
        schema = _schema_for_llm(con, req.question)
        timings["schema_build_ms"] = round((time.time() - t0) * 1000, 2)
        
        # Check plan cache first (performance optimization)
        cache_key = (req.question.strip(), OLLAMA_MODEL)
        cached = _PLAN_CACHE.get(cache_key)
        if cached and cached.get("sql"):
            sql = cached["sql"]
            plan = {"ok": True, "sql": sql, "notes": cached.get("notes", ""), "cached": True}
            timings["llm_ms"] = 0
            timings["embedding_ms"] = 0
        else:
            # Generate SQL plan (with timing)
            t1 = time.time()
            plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)
            timings["llm_ms"] = round((time.time() - t1) * 1000, 2)
            # Note: embedding time is included in llm_ms if PDF context is enabled
            timings["embedding_ms"] = 0  # Will be set if PDF context is used
            
            if plan.get("ok") and plan.get("sql"):
                # Cache the plan for future identical questions
                _PLAN_CACHE[cache_key] = {"sql": plan["sql"], "notes": plan.get("notes", "")}
            
        if not plan.get("ok"):
            # Provide a hint even when planning fails (often schema mismatch).
            plan["hint"] = _build_no_answer_hint(con=con, question=req.question, error=str(plan.get("error", "")))
            plan["timings_ms"] = timings
            plan["total_ms"] = round((time.time() - start_time) * 1000, 2)
            plan["model"] = OLLAMA_MODEL  # Show which model was used
            return plan

        sql = plan["sql"]
        
        # Execute SQL (with timing)
        t2 = time.time()
        try:
            df = con.execute(sql).df()
            timings["sql_exec_ms"] = round((time.time() - t2) * 1000, 2)
        except Exception as e:
            err = f"{e}"
            timings["sql_exec_ms"] = round((time.time() - t2) * 1000, 2)
            
            # Provide helpful hint for common errors
            hint = _build_no_answer_hint(con=con, question=req.question, sql=sql, error=err)
            if "conversion" in err.lower() or "could not convert" in err.lower() or "cast" in err.lower():
                hint += " TIP: The query tried to convert empty strings or invalid values to numbers. The LLM should use NULLIF(TRIM(REPLACE(col, ',', '')), '') or CASE statements to handle empty/null values before casting to DECIMAL/INTEGER."
            elif "syntax error" in err.lower() or "parser error" in err.lower():
                hint += " TIP: SQL syntax error detected. Common issues: 1) Using backticks instead of double quotes for identifiers (DuckDB uses double quotes), 2) Unclosed parentheses/quotes, 3) Missing commas in SELECT lists. The system will auto-fix backticks, but check for other syntax issues."
            
            return {
                "ok": False,
                "error": f"SQL execution failed: {err}",
                "hint": hint,
                "sql": sql,
                "plan_raw": plan.get("raw", ""),
                "timings_ms": timings,
                "total_ms": round((time.time() - start_time) * 1000, 2),
                "model": OLLAMA_MODEL,  # Show which model was used
            }

        # Convert to records (with timing)
        t3 = time.time()
        if df is None or df.shape[0] == 0:
            result = {
                "ok": True,
                "sql": sql,
                "rows": [],
                "notes": plan.get("notes", ""),
                "hint": _build_no_answer_hint(con=con, question=req.question, sql=sql, empty=True),
                "model": OLLAMA_MODEL,
            }
        else:
            rows = df_to_records_safe(df)
            result = {
                "ok": True, 
                "sql": sql, 
                "rows": rows, 
                "notes": plan.get("notes",""),
                "model": OLLAMA_MODEL,
            }
        
        timings["json_serialize_ms"] = round((time.time() - t3) * 1000, 2)
        timings["total_ms"] = round((time.time() - start_time) * 1000, 2)
        result["timings_ms"] = timings
        
        # Add cache indicator if plan was cached
        if plan.get("cached"):
            result["plan_cached"] = True
        
        return result
    finally:
        con.close()

@app.post("/quick-excel")
async def quick_excel(
    question: str = Form(...),
    files: List[UploadFile] = File(...)
):
    payload = []
    for f in files:
        payload.append((f.filename, await f.read()))

    return quick_excel_query(
        files=payload,
        question=question,
        base_url=OLLAMA_URL,
        model=OLLAMA_MODEL,
    )

@app.post("/report-pack")
def report_pack(req: ReportReq):
    out_dir = Path(tempfile.mkdtemp(prefix="jme_ai_reports_"))
    xlsx = generate_report_pack(DB_PATH, out_dir, req.period, opening_cash=req.opening_cash)
    return FileResponse(path=str(xlsx), filename=xlsx.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================================
# Superset-Compatible REST API Endpoints
# ============================================================================

@app.get("/api/v1/tables")
def list_tables():
    """
    List all available tables for Superset.
    Returns: {"tables": [{"name": "...", "schema": "..."}, ...]}
    """
    con = connect(DB_PATH, read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        result = [{"name": t[0], "schema": "main"} for t in tables]
        return {"tables": result}
    finally:
        con.close()

@app.get("/api/v1/schema")
def get_schema_info():
    """
    Get schema information for all tables.
    Returns: {"schema": {"table_name": [{"name": "col", "type": "..."}, ...]}}
    """
    con = connect(DB_PATH, read_only=True)
    try:
        schema = get_schema(con)
        return {"schema": schema["tables"]}
    finally:
        con.close()

@app.get("/api/v1/table/{table_name}")
def get_table_data(
    table_name: str,
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of rows to return"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    where: str = Query(None, description="SQL WHERE clause (use with caution)"),
    order_by: str = Query(None, description="SQL ORDER BY clause"),
):
    """
    Get data from a specific table with pagination and filtering.
    Superset-compatible endpoint.
    """
    con = connect(DB_PATH, read_only=True)
    try:
        # Validate table name exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if table_name not in tables:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
        
        # Build safe SQL query
        query = f'SELECT * FROM "{table_name}"'
        where_clean = None
        
        # Add WHERE clause if provided (basic validation)
        if where:
            # Basic safety check - only allow simple WHERE clauses
            where_clean = where.strip()
            if where_clean.lower().startswith(('select', 'insert', 'update', 'delete', 'drop', 'alter', 'create')):
                raise HTTPException(status_code=400, detail="Invalid WHERE clause")
            query += f" WHERE {where_clean}"
        
        # Add ORDER BY if provided
        if order_by:
            order_clean = order_by.strip()
            if order_clean.lower().startswith(('select', 'insert', 'update', 'delete', 'drop', 'alter', 'create')):
                raise HTTPException(status_code=400, detail="Invalid ORDER BY clause")
            query += f" ORDER BY {order_clean}"
        
        # Add pagination
        query += f" LIMIT {limit} OFFSET {offset}"
        
        # Execute query
        df = con.execute(query).df()
        
        # Get total count for pagination info
        count_query = f'SELECT COUNT(*) as total FROM "{table_name}"'
        if where_clean:
            count_query += f" WHERE {where_clean}"
        total = con.execute(count_query).fetchone()[0]
        
        return {
            "data": df_to_records_safe(df),
            "count": len(df),
            "total": int(total),
            "limit": limit,
            "offset": offset
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")
    finally:
        con.close()

@app.get("/api/v1/query")
def execute_query(
    sql: str = Query(..., description="SQL SELECT query to execute"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of rows to return"),
):
    """
    Execute a SQL SELECT query.
    Superset-compatible endpoint that accepts SQL via query parameter.
    """
    con = connect(DB_PATH, read_only=True)
    try:
        # Validate SQL
        if not validate_sql(sql):
            raise HTTPException(status_code=400, detail="Invalid or unsafe SQL query. Only SELECT statements are allowed.")
        
        # Add LIMIT if not present
        sql_lower = sql.strip().lower()
        if "limit" not in sql_lower:
            sql = f"{sql.strip()} LIMIT {limit}"
        
        # Execute query
        df = con.execute(sql).df()
        
        return {
            "data": df_to_records_safe(df),
            "count": len(df)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")
    finally:
        con.close()

@app.get("/api/v1/table/{table_name}/columns")
def get_table_columns(table_name: str):
    """
    Get column information for a specific table.
    Superset-compatible endpoint.
    """
    con = connect(DB_PATH, read_only=True)
    try:
        # Validate table exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if table_name not in tables:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
        
        # Get column info
        cols = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        columns = [
            {
                "name": c[1],
                "type": c[2],
                "nullable": not c[3],  # DuckDB: 0 = nullable, 1 = not null
                "default": c[4],
                "primary_key": bool(c[5])
            }
            for c in cols
        ]
        
        return {"columns": columns}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get column info: {str(e)}")
    finally:
        con.close()
