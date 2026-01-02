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

_DB_MTIME_CACHE: float | None = None
_TABLE_INFO_CACHE: dict[str, list[dict[str, str]]] = {}
_PLAN_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def df_to_records_safe(df: pd.DataFrame):
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None).to_dict(orient="records")

def _maybe_invalidate_schema_cache() -> None:
    global _DB_MTIME_CACHE, _TABLE_INFO_CACHE, _PLAN_CACHE
    try:
        mtime = DB_PATH.stat().st_mtime
    except Exception:
        mtime = None
    if _DB_MTIME_CACHE != mtime:
        _DB_MTIME_CACHE = mtime
        _TABLE_INFO_CACHE = {}
        _PLAN_CACHE = {}

def _get_table_info_cached(con, table: str, max_cols: int = 20) -> list[dict[str, str]]:
    """Get table info with column limit to reduce prompt size."""
    _maybe_invalidate_schema_cache()
    cache_key = (table, max_cols)
    cached = _TABLE_INFO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cols = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    cols = cols[:max_cols]  # Limit columns
    out = [{"name": c[1], "type": c[2]} for c in cols]
    _TABLE_INFO_CACHE[cache_key] = out
    return out

def _schema_for_llm(con, question: str) -> dict:
    """
    Compact schema payload -> improves speed and SQL accuracy by reducing noise.
    Includes canonical tables + a small set of relevant/recent raw__ tables.
    """
    base_tables = ["invoices", "payments", "expenses", "bank_txns", "schema_registry", "raw_sheet_registry"]
    existing_tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    existing_set = set(existing_tables)

    recent_raw: list[str] = []
    if "raw_sheet_registry" in existing_set:
        try:
            rows = con.execute(
                "SELECT raw_table FROM raw_sheet_registry ORDER BY updated_ts DESC LIMIT 25"
            ).fetchall()
            recent_raw = [r[0] for r in rows if r and r[0]]
        except Exception:
            recent_raw = []

    tokens = [t for t in "".join([c.lower() if c.isalnum() else " " for c in (question or "")]).split() if len(t) >= 3]
    matched = []
    if tokens and recent_raw:
        for tname in recent_raw:
            tlow = tname.lower()
            if any(tok in tlow for tok in tokens):
                matched.append(tname)

    selected_raw = (matched + recent_raw)[:8]
    selected = []
    for t in base_tables + selected_raw:
        if t in existing_set and t not in selected:
            selected.append(t)

    tables: dict[str, list[dict[str, str]]] = {}
    for t in selected:
        tables[t] = _get_table_info_cached(con, t)
    return {"tables": tables}

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
    retry_on_error: bool = False


@app.post("/ask-data")
def ask_data(req: AskDataReq):
    con = connect(DB_PATH, read_only=True)
    try:
        schema = _schema_for_llm(con, req.question)
        # Cache SQL plan by (question, model) for speed on repeat queries.
        cache_key = (req.question.strip(), OLLAMA_MODEL)
        cached = _PLAN_CACHE.get(cache_key)
        if cached and cached.get("sql"):
            sql = cached["sql"]
            plan = {"ok": True, "sql": sql, "notes": cached.get("notes", "")}
        else:
            plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)
            if plan.get("ok") and plan.get("sql"):
                _PLAN_CACHE[cache_key] = {"sql": plan["sql"], "notes": plan.get("notes", "")}
        if not plan.get("ok"):
            return plan
        sql = plan["sql"]
        try:
            df = con.execute(sql).df()
        except Exception as e:
            # Optional one-shot retry with error context to improve SQL accuracy
            if req.retry_on_error:
                q2 = (
                    f"{req.question}\n\n"
                    f"Previous SQL failed with error: {e}\n"
                    f"Generate corrected SQL using ONLY the provided schema. SELECT/CTE only."
                )
                plan2 = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=q2)
                if plan2.get("ok"):
                    sql2 = plan2["sql"]
                    try:
                        df = con.execute(sql2).df()
                        sql = sql2
                        plan = plan2
                        _PLAN_CACHE[cache_key] = {"sql": sql2, "notes": plan2.get("notes", "")}
                    except Exception as e2:
                        return {"ok": False, "error": f"SQL execution failed: {e2}", "sql": sql2, "plan_raw": plan2.get("raw", "")}
                else:
                    return {"ok": False, "error": f"SQL execution failed: {e}", "sql": sql, "plan_raw": plan.get("raw", ""), "retry_error": plan2.get("error")}
            else:
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


