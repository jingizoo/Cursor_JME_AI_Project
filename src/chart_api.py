"""
Chart API - Question answering with automatic chart visualization
This API extends the main API with chart generation capabilities.
"""
import base64
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .db_store import connect
from .planner_agent import plan_sql, get_schema, validate_sql
from .utils_df import df_to_records_safe

# Reuse configuration from main API
DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data"))
CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pipeline.duckdb"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")  # CPU-friendly default

app = FastAPI(title="JME AI Finance Pipeline - Chart API")

_DB_MTIME_CACHE: float | None = None
_TABLE_INFO_CACHE: dict[str, list[dict[str, str]]] = {}

def _maybe_invalidate_schema_cache() -> None:
    global _DB_MTIME_CACHE, _TABLE_INFO_CACHE
    try:
        mtime = DB_PATH.stat().st_mtime
    except Exception:
        mtime = None
    if _DB_MTIME_CACHE != mtime:
        _DB_MTIME_CACHE = mtime
        _TABLE_INFO_CACHE = {}

def _get_table_info_cached(con, table: str, max_cols: int = None) -> list[dict[str, str]]:
    _maybe_invalidate_schema_cache()
    cache_key = (table, max_cols)
    cached = _TABLE_INFO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cols = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    # Limit columns if max_cols is specified
    if max_cols:
        cols = cols[:max_cols]
    out = [{"name": c[1], "type": c[2]} for c in cols]
    _TABLE_INFO_CACHE[cache_key] = out
    return out

def _schema_for_llm(con, question: str, max_tables: int = None, max_cols_per_table: int = None) -> dict:
    """
    Build schema payload for the LLM. Includes ALL tables dynamically by default.
    Can be limited via environment variables for performance.
    """
    import os
    
    # Get limits from environment variables or use defaults
    if max_tables is None:
        env = int(os.getenv("JME_MAX_TABLES", "12"))
        max_tables = None if env <= 0 else env
    
    if max_cols_per_table is None:
        env = int(os.getenv("JME_MAX_COLS", "25"))
        max_cols_per_table = None if env <= 0 else env
    
    # Get all existing tables
    existing_tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    existing_set = set(existing_tables)
    
    # Filter out registry/metadata tables
    registry_tables = {"schema_registry", "raw_sheet_registry"}
    data_tables = [t for t in existing_tables if t not in registry_tables]
    
    question_lower = (question or "").lower()
    
    # Check if question explicitly mentions any table names
    explicitly_mentioned = []
    for tname in data_tables:
        if tname.lower() in question_lower:
            explicitly_mentioned.append(tname)
    
    # If max_tables is set, prioritize: explicitly mentioned > raw tables (most recent first)
    if max_tables and len(data_tables) > max_tables:
        selected = list(explicitly_mentioned)
        
        raw_tables = [t for t in data_tables if t.startswith("raw_") and t not in selected]
        if "raw_sheet_registry" in existing_set:
            try:
                rows = con.execute(
                    "SELECT raw_table FROM raw_sheet_registry ORDER BY updated_ts DESC"
                ).fetchall()
                ordered_raw = [r[0] for r in rows if r and r[0] and r[0] in raw_tables]
                for t in ordered_raw:
                    if t not in selected and len(selected) < max_tables:
                        selected.append(t)
            except Exception:
                pass
        
        # Finally, add any remaining tables
        for t in data_tables:
            if t not in selected and len(selected) < max_tables:
                selected.append(t)
    else:
        # Include ALL tables (no limit)
        selected = data_tables
    
    # Fast path: use cached column lists from raw_sheet_registry when available
    registry_cols: dict[str, list[str]] = {}
    if "raw_sheet_registry" in existing_set:
        try:
            rows = con.execute("SELECT raw_table, columns_json FROM raw_sheet_registry ORDER BY updated_ts DESC").fetchall()
            for r in rows:
                tname = r[0]
                if not tname or tname in registry_cols:
                    continue
                try:
                    cols = json.loads(r[1] or "null")
                    if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
                        registry_cols[tname] = cols
                except Exception:
                    continue
        except Exception:
            pass

    # ✅ Names-only schema payload (smaller + easier for LLM)
    tables: dict[str, list[str]] = {}
    for t in selected:
        # For explicitly mentioned tables, include more columns if limit is set
        col_limit = max_cols_per_table * 2 if (t.lower() in question_lower and max_cols_per_table) else max_cols_per_table
        cols_list = registry_cols.get(t)
        if cols_list is not None:
            tables[t] = cols_list[:col_limit] if col_limit else cols_list
            continue
        cols = _get_table_info_cached(con, t, max_cols=col_limit)
        tables[t] = [c["name"] for c in cols]

    return {"tables": tables}

def _tables_preview(con, max_tables: int = 30):
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
        msg = "Query ran but returned 0 rows. Try loosening filters (month/date text), or verify the ingested raw sheet table/columns."
        if raw_tables:
            msg += f" Raw ingested sheet tables exist (example: `{raw_tables[0]}`)."
        msg += " Tip: re-ask using the exact column names from the ingested table."
        return msg

    err = (error or "").lower()
    if "does not exist" in err or "table with name" in err:
        msg = "The SQL referenced a table that doesn't exist in the DB. This usually means ingestion didn't create a table for that sheet yet."
        if raw_tables:
            msg += f" I can see raw ingested sheet tables available (example: `{raw_tables[0]}`)."
        msg += " Re-ask using the raw table + exact column names."
        return msg

    if "column" in err and ("not found" in err or "binder" in err):
        return "The SQL referenced a column that doesn't exist (or needs quoting). Re-ask using the exact column names from your ingested table."

    msg = "The query failed. Verify ingestion, then re-ask with more specific details (table/column names, month format)."
    if tables:
        msg += f" Available tables (preview): {tables[:10]}"
    return msg

def detect_chart_type(question: str, df: pd.DataFrame) -> str:
    """
    Detect the appropriate chart type based on question and data.
    Returns: 'bar', 'line', 'pie', 'scatter', or 'table'
    """
    question_lower = question.lower()
    
    # Check for specific chart keywords
    if any(word in question_lower for word in ['top', 'most', 'highest', 'largest', 'biggest', 'best']):
        return 'bar'
    if any(word in question_lower for word in ['trend', 'over time', 'monthly', 'daily', 'weekly']):
        return 'line'
    if any(word in question_lower for word in ['distribution', 'percentage', 'share', 'proportion']):
        return 'pie'
    if any(word in question_lower for word in ['correlation', 'relationship', 'compare']):
        return 'scatter'
    
    # Default based on data shape
    if len(df.columns) == 2:
        # Two columns - likely bar chart
        return 'bar'
    elif len(df.columns) > 2:
        # Multiple columns - table view
        return 'table'
    
    return 'bar'  # Default

def create_bar_chart(df: pd.DataFrame, title: str = "Chart") -> str:
    """Create a bar chart and return as base64 encoded image."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Assume first column is x-axis, second is y-axis
    if len(df.columns) >= 2:
        x_col = df.columns[0]
        y_col = df.columns[1]
        
        # Sort by y-axis values (descending) for top N queries
        df_sorted = df.sort_values(by=y_col, ascending=False)
        
        # Limit to top 10 for readability
        if len(df_sorted) > 10:
            df_sorted = df_sorted.head(10)
        
        bars = ax.bar(range(len(df_sorted)), df_sorted[y_col], color='steelblue', alpha=0.7)
        ax.set_xticks(range(len(df_sorted)))
        ax.set_xticklabels(df_sorted[x_col], rotation=45, ha='right')
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(title, fontsize=14, fontweight='bold')
        
        # Add value labels on bars
        for i, (idx, row) in enumerate(df_sorted.iterrows()):
            value = row[y_col]
            if pd.notna(value):
                ax.text(i, value, f'{value:.1f}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
    else:
        # Single column - simple bar chart
        ax.bar(range(len(df)), df.iloc[:, 0], color='steelblue', alpha=0.7)
        ax.set_title(title, fontsize=14, fontweight='bold')
    
    # Convert to base64
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    
    return img_base64

def create_line_chart(df: pd.DataFrame, title: str = "Chart") -> str:
    """Create a line chart and return as base64 encoded image."""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    if len(df.columns) >= 2:
        x_col = df.columns[0]
        y_col = df.columns[1]
        
        # Try to convert x-axis to datetime if it looks like dates
        try:
            df[x_col] = pd.to_datetime(df[x_col])
            df_sorted = df.sort_values(by=x_col)
        except:
            df_sorted = df
        
        ax.plot(df_sorted[x_col], df_sorted[y_col], marker='o', linewidth=2, markersize=6)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
    else:
        ax.plot(df.iloc[:, 0], marker='o')
        ax.set_title(title, fontsize=14, fontweight='bold')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    
    return img_base64

def create_pie_chart(df: pd.DataFrame, title: str = "Chart") -> str:
    """Create a pie chart and return as base64 encoded image."""
    fig, ax = plt.subplots(figsize=(8, 8))
    
    if len(df.columns) >= 2:
        labels_col = df.columns[0]
        values_col = df.columns[1]
        
        # Limit to top 10 for readability
        df_sorted = df.sort_values(by=values_col, ascending=False).head(10)
        
        ax.pie(df_sorted[values_col], labels=df_sorted[labels_col], autopct='%1.1f%%', startangle=90)
        ax.set_title(title, fontsize=14, fontweight='bold')
    else:
        ax.pie(df.iloc[:, 0], autopct='%1.1f%%', startangle=90)
        ax.set_title(title, fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    
    return img_base64

def generate_chart(df: pd.DataFrame, chart_type: str, title: str = "Chart") -> str:
    """Generate chart based on type and return base64 encoded image."""
    if chart_type == 'bar':
        return create_bar_chart(df, title)
    elif chart_type == 'line':
        return create_line_chart(df, title)
    elif chart_type == 'pie':
        return create_pie_chart(df, title)
    else:
        # Default to bar chart
        return create_bar_chart(df, title)

class ChartQuestionReq(BaseModel):
    question: str
    chart_type: Optional[str] = None  # Optional: 'bar', 'line', 'pie', 'auto'

@app.post("/ask-chart")
def ask_with_chart(req: ChartQuestionReq):
    """
    Ask a question and get answer with automatic chart visualization.
    
    Example questions:
    - "top 5 who consumed most hours in september"
    - "show me revenue trends by month"
    - "what is the distribution of expenses by category"
    """
    con = connect(DB_PATH, read_only=True)
    try:
        # Get schema and plan SQL
        schema = _schema_for_llm(con, req.question)
        plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)

        # If token/length limit, retry once with smaller schema (faster than raising num_predict on CPU)
        if not plan.get("ok"):
            err_txt = str(plan.get("error", "")).lower()
            if ("token" in err_txt and "limit" in err_txt) or ("num_predict" in err_txt) or ("length" in err_txt):
                schema_small = _schema_for_llm(con, req.question, max_tables=6, max_cols_per_table=15)
                plan2 = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema_small, question=req.question)
                if plan2.get("ok") and plan2.get("sql"):
                    plan = plan2
        
        if not plan.get("ok"):
            plan["hint"] = _build_no_answer_hint(con=con, question=req.question, error=str(plan.get("error", "")))
            return plan
        
        sql = plan["sql"]
        
        # Execute query
        try:
            df = con.execute(sql).df()
        except Exception as e:
            err = f"{e}"
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
            }
        
        if df.empty:
            return {
                "ok": True,
                "message": "Query executed successfully but returned no results",
                "sql": sql,
                "data": [],
                "chart": None,
                "hint": _build_no_answer_hint(con=con, question=req.question, sql=sql, empty=True),
            }
        
        # Determine chart type
        chart_type = req.chart_type or detect_chart_type(req.question, df)
        
        # Generate chart
        try:
            chart_title = req.question[:50]  # Use question as title (truncated)
            chart_base64 = generate_chart(df, chart_type, chart_title)
        except Exception as e:
            return {
                "ok": False,
                "error": f"Chart generation failed: {e}",
                "sql": sql,
                "data": df_to_records_safe(df)
            }
        
        return {
            "ok": True,
            "sql": sql,
            "data": df_to_records_safe(df),
            "chart": {
                "type": chart_type,
                "image_base64": chart_base64,
                "format": "png"
            },
            "notes": plan.get("notes", "")
        }
    
    except Exception as e:
        return {"ok": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        con.close()

@app.get("/ask-chart")
def ask_with_chart_get(question: str, chart_type: Optional[str] = None):
    """
    GET version of ask-chart endpoint.
    
    Example: /ask-chart?question=top%205%20who%20consumed%20most%20hours%20in%20september
    """
    req = ChartQuestionReq(question=question, chart_type=chart_type)
    return ask_with_chart(req)

@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "ok": True,
        "service": "Chart API",
        "data_dir": str(DATA_DIR),
        "ollama_url": OLLAMA_URL,
        "ollama_model": OLLAMA_MODEL
    }

