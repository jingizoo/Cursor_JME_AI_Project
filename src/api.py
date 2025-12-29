import os
import tempfile
from pathlib import Path
from typing import List

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
    # Replace +/-inf with NaN, then convert NaN to None
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None).to_dict(orient="records")

DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data"))
CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pipeline.duckdb"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

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
    return ingest_folder(data_dir=DATA_DIR, db_path=DB_PATH, base_url=OLLAMA_URL, model=OLLAMA_MODEL, force=req.force)

@app.get("/catalog")
def catalog():
    con = connect(DB_PATH)
    rows = con.execute("SELECT file, sheet, sheet_type, confidence, notes, updated_ts FROM schema_registry ORDER BY updated_ts DESC").fetchall()
    out = []
    for r in rows:
        out.append({"file": r[0], "sheet": r[1], "sheet_type": r[2], "confidence": float(r[3] or 0), "notes": r[4] or "", "updated_ts": r[5]})
    return {"ok": True, "mappings": out}

@app.post("/ask")
def ask(req: AskReq):
    con = connect(DB_PATH)
    schema = get_schema(con)
    plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)
    if not plan.get("ok"):
        return plan
    sql = plan["sql"]
    try:
        df = con.execute(sql).df()
    except Exception as e:
        return {"ok": False, "error": f"SQL execution failed: {e}", "sql": sql, "plan_raw": plan.get("raw","")}
    return {"ok": True, "sql": sql, "rows": df_to_records_safe(df), "notes": plan.get("notes","")}

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
    con = connect(DB_PATH)
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
    con = connect(DB_PATH)
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
    con = connect(DB_PATH)
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
    con = connect(DB_PATH)
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
    con = connect(DB_PATH)
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
