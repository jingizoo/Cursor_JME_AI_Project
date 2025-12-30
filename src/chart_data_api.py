"""
Chart Data API (no matplotlib)

Purpose: Provide fast "question -> SQL -> data" response so the webapp can render
interactive charts client-side (Plotly) without requiring matplotlib on the server.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

from .db_store import connect
from .planner_agent import plan_sql, get_schema


DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data"))
CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pipeline.duckdb"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")


app = FastAPI(title="JME AI Finance Pipeline - Chart Data API")


def df_to_records_safe(df: pd.DataFrame):
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def detect_chart_type(question: str, df: pd.DataFrame) -> str:
    q = (question or "").lower()
    if any(w in q for w in ["top", "most", "highest", "largest", "biggest", "best"]):
        return "bar"
    if any(w in q for w in ["trend", "over time", "monthly", "daily", "weekly"]):
        return "line"
    if any(w in q for w in ["distribution", "percentage", "share", "proportion"]):
        return "pie"
    if len(df.columns) == 2:
        return "bar"
    return "table"


class AskDataReq(BaseModel):
    question: str
    chart_type: Optional[str] = None  # bar/line/pie/auto


@app.post("/ask-data")
def ask_data(req: AskDataReq):
    con = connect(DB_PATH)
    try:
        # Reuse compact schema selection already used in main API by letting planner see full schema.
        # For best speed, you can switch this to a compact schema builder similar to src/api.py.
        schema = get_schema(con)
        plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)
        if not plan.get("ok"):
            return plan
        sql = plan["sql"]
        try:
            df = con.execute(sql).df()
        except Exception as e:
            return {"ok": False, "error": f"SQL execution failed: {e}", "sql": sql, "plan_raw": plan.get("raw", "")}

        rows = df_to_records_safe(df)
        ctype = req.chart_type or detect_chart_type(req.question, df)
        return {
            "ok": True,
            "sql": sql,
            "data": rows,
            "chart": {"type": ctype},
            "notes": plan.get("notes", ""),
        }
    finally:
        con.close()


@app.get("/health")
def health():
    return {"ok": True, "service": "Chart Data API", "data_dir": str(DATA_DIR), "db_path": str(DB_PATH)}


