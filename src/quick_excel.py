# src/quick_excel.py
import io
import json
import os
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

import duckdb
import numpy as np
import pandas as pd

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from .llm_client import ollama_chat, extract_json

SAFE_SQL_DENY = ["insert", "update", "delete", "drop", "alter", "create", "attach", "detach", "copy", "pragma", "call"]

def _safe_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9a-zA-Z_]", "_", s)
    s = s.strip("_")
    if not s:
        s = "sheet"
    if s[0].isdigit():
        s = "t_" + s
    return s

def _short_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]

def detect_header_row(xbytes: bytes, sheet: str, max_scan: int = 25) -> int:
    preview = pd.read_excel(io.BytesIO(xbytes), sheet_name=sheet, header=None, nrows=max_scan, engine="openpyxl")
    best_row = 0
    best_score = -1
    for i in range(min(max_scan, len(preview))):
        score = int(preview.iloc[i].notna().sum())
        if score > best_score:
            best_score = score
            best_row = i
    return best_row

def read_sheet(xbytes: bytes, sheet: str) -> pd.DataFrame:
    hdr = detect_header_row(xbytes, sheet)
    df = pd.read_excel(io.BytesIO(xbytes), sheet_name=sheet, header=hdr, engine="openpyxl")
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    # Ensure column names are strings and unique
    cols = [str(c) for c in df.columns]
    seen = {}
    fixed = []
    for c in cols:
        base = c.strip() or "col"
        if base not in seen:
            seen[base] = 0
            fixed.append(base)
        else:
            seen[base] += 1
            fixed.append(f"{base}_{seen[base]}")
    df.columns = fixed
    return df

def validate_sql(sql: str) -> bool:
    if not sql:
        return False
    s = sql.strip()
    # Disallow multiple statements
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        if len(parts) != 1:
            return False
        s = parts[0]

    s_low = s.lower()
    if not (s_low.startswith("select") or s_low.startswith("with")):
        return False

    for bad in SAFE_SQL_DENY:
        if bad in s_low:
            return False

    return True

def ensure_limit(sql: str, limit: int = 200) -> str:
    s = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\b", s, flags=re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {int(limit)}"

def get_schema(con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    tables = {}
    for (t,) in con.execute("SHOW TABLES").fetchall():
        cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
        tables[t] = [{"name": c[1], "type": c[2]} for c in cols]
    return {"tables": tables}

def plan_sql_one(*, base_url: str, model: str, schema: Dict[str, Any], question: str) -> Dict[str, Any]:
    system = (
        "You are a data analyst.\n"
        "Return ONLY JSON with EXACTLY ONE SQL statement.\n"
        "Rules:\n"
        "- One statement only (no multiple SELECTs, no semicolons).\n"
        "- SELECT or WITH only.\n"
        "- No writes (no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/etc).\n"
        "- Always include LIMIT 200 (or less).\n"
        "JSON format: {\"sql\":\"...\",\"notes\":\"...\"}\n"
    )
    user = json.dumps({"schema": schema, "question": question}, ensure_ascii=False)

    try:
        # Use configurable num_predict limit
        num_predict_limit = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
        text = ollama_chat(base_url=base_url, model=model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], temperature=0.0, num_predict=num_predict_limit)
    except Exception as e:
        return {"ok": False, "error": f"Ollama call failed: {e}"}

    # Handle empty response
    if not text or not text.strip():
        return {
            "ok": False,
            "error": "LLM returned empty response",
            "raw": text or "(empty)"
        }
    
    obj = extract_json(text)
    
    # Better error handling for JSON extraction failures
    if obj is None:
        # Try to extract SQL directly if JSON extraction failed
        sql_match = re.search(r'```(?:sql)?\s*(SELECT.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql = sql_match.group(1).strip()
            obj = {"sql": sql, "notes": "Extracted from markdown code block"}
        else:
            sql_match = re.search(r'(?:sql|query):\s*(SELECT.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                obj = {"sql": sql, "notes": "Extracted from text response"}
            else:
                return {
                    "ok": False, 
                    "error": "LLM response is not valid JSON and no SQL found",
                    "raw": text[:1000]
                }
    else:
        sql = obj.get("sql", "")
        if not sql:
            return {
                "ok": False,
                "error": "LLM returned JSON but no SQL field found",
                "raw": text[:1000],
                "parsed_json": obj
            }

    sql = (sql or "").strip()
    if not validate_sql(sql):
        return {
            "ok": False, 
            "error": "LLM produced unsafe/invalid SQL", 
            "raw": text[:1000],
            "sql_attempted": sql[:200]
        }

    sql = ensure_limit(sql, 200)
    return {"ok": True, "sql": sql, "notes": obj.get("notes",""), "raw": text[:500]}

def extract_pdf_tables_from_bytes(fbytes: bytes) -> List[Dict[str, Any]]:
    """Extract tables from PDF bytes. Returns list of {page, table_idx, df, sheet_name}."""
    if not PDF_AVAILABLE:
        return []
    
    tables = []
    try:
        with pdfplumber.open(io.BytesIO(fbytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables()
                for table_idx, table in enumerate(page_tables):
                    if table and len(table) > 1:
                        df = pd.DataFrame(table[1:], columns=table[0] if table[0] else None)
                        df.columns = [str(c).strip() if c else f"col_{i}" for i, c in enumerate(df.columns)]
                        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
                        if df.shape[0] > 0 and df.shape[1] > 0:
                            tables.append({
                                "page": page_num,
                                "table_idx": table_idx,
                                "df": df,
                                "sheet_name": f"page_{page_num}_table_{table_idx + 1}"
                            })
    except Exception:
        pass
    return tables

def quick_excel_query(
    *,
    files: List[Tuple[str, bytes]],   # [(filename, bytes), ...]
    question: str,
    base_url: str,
    model: str,
    max_rows_per_sheet: int = 20000,
) -> Dict[str, Any]:
    con = duckdb.connect(":memory:")

    created_tables = []
    # Load each sheet of each file into temp DuckDB tables
    for fname, fbytes in files:
        fname_lower = fname.lower()
        
        # Handle PDF files
        if fname_lower.endswith('.pdf'):
            if not PDF_AVAILABLE:
                created_tables.append({"file": fname, "error": "PDF support not available (install pdfplumber)"})
                continue
            try:
                pdf_tables = extract_pdf_tables_from_bytes(fbytes)
                if not pdf_tables:
                    created_tables.append({"file": fname, "error": "No tables found in PDF"})
                    continue
                
                for table_info in pdf_tables:
                    sheet = table_info["sheet_name"]
                    df = table_info["df"]
                    if df is None or df.shape[0] == 0:
                        continue
                    if max_rows_per_sheet:
                        df = df.head(int(max_rows_per_sheet))
                    
                    tname = f"{_safe_name(Path(fname).stem)}__{_safe_name(sheet)}__{_short_hash(fname+'|'+sheet)}"
                    con.register("df_tmp", df)
                    con.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM df_tmp')
                    con.unregister("df_tmp")
                    
                    created_tables.append({
                        "file": fname,
                        "sheet": sheet,
                        "table": tname,
                        "rows": int(df.shape[0]),
                        "cols": int(df.shape[1]),
                    })
            except Exception as e:
                created_tables.append({"file": fname, "error": f"Cannot read PDF: {e}"})
            continue
        
        # Handle Excel files
        try:
            xls = pd.ExcelFile(io.BytesIO(fbytes), engine="openpyxl")
        except Exception as e:
            created_tables.append({"file": fname, "error": f"Cannot read excel: {e}"})
            continue

        for sheet in xls.sheet_names:
            try:
                df = read_sheet(fbytes, sheet)
                if df is None or df.shape[0] == 0:
                    continue
                if max_rows_per_sheet:
                    df = df.head(int(max_rows_per_sheet))

                tname = f"{_safe_name(Path(fname).stem)}__{_safe_name(sheet)}__{_short_hash(fname+'|'+sheet)}"
                con.register("df_tmp", df)
                con.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM df_tmp')
                con.unregister("df_tmp")

                created_tables.append({
                    "file": fname,
                    "sheet": sheet,
                    "table": tname,
                    "rows": int(df.shape[0]),
                    "cols": int(df.shape[1]),
                })
            except Exception as e:
                created_tables.append({"file": fname, "sheet": sheet, "error": str(e)})

    schema = get_schema(con)

    plan = plan_sql_one(base_url=base_url, model=model, schema=schema, question=question)
    if not plan.get("ok"):
        return {"ok": False, "error": plan.get("error"), "created_tables": created_tables, "debug": plan.get("raw")}

    sql = plan["sql"]
    try:
        df = con.execute(sql).df()
    except Exception as e:
        return {
            "ok": False,
            "error": f"SQL execution failed: {e}",
            "sql": sql,
            "created_tables": created_tables,
            "debug": plan.get("raw"),
        }

    # Replace +/-inf with NaN, then convert NaN to None for JSON serialization
    df = df.copy()
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.fillna(None)
    records = df.to_dict(orient="records")
    # Final pass: recursively replace any remaining NaN/Inf
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
    rows = [clean_value(r) for r in records]

    return {
        "ok": True,
        "sql": sql,
        "rows": rows,
        "created_tables": created_tables,
        "notes": plan.get("notes",""),
    }
