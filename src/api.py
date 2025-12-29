import os
import tempfile
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .db_store import connect
from .ingest import ingest_folder
from .planner_agent import plan_sql, get_schema
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
