"""
Chart API - Question answering with automatic chart visualization
This API extends the main API with chart generation capabilities.
"""
import base64
import io
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

# Reuse configuration from main API
DATA_DIR = Path(os.environ.get("JME_DATA_DIR", "./data"))
CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pipeline.duckdb"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

app = FastAPI(title="JME AI Finance Pipeline - Chart API")

def df_to_records_safe(df: pd.DataFrame):
    """Convert DataFrame to records, replacing NaN/Inf with None for JSON serialization."""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None).to_dict(orient="records")

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
    con = connect(DB_PATH)
    try:
        # Get schema and plan SQL
        schema = get_schema(con)
        plan = plan_sql(base_url=OLLAMA_URL, model=OLLAMA_MODEL, schema=schema, question=req.question)
        
        if not plan.get("ok"):
            plan["hint"] = _build_no_answer_hint(con=con, question=req.question, error=str(plan.get("error", "")))
            return plan
        
        sql = plan["sql"]
        
        # Execute query
        try:
            df = con.execute(sql).df()
        except Exception as e:
            err = f"{e}"
            return {
                "ok": False,
                "error": f"SQL execution failed: {err}",
                "hint": _build_no_answer_hint(con=con, question=req.question, sql=sql, error=err),
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

