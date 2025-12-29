import json
from typing import Any, Dict

import duckdb

from .llm_client import ollama_chat, extract_json

SAFE_SQL_DENY = ["insert","update","delete","drop","alter","create","attach","detach","copy","pragma","call"]

def get_schema(con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    tables = {}
    for (t,) in con.execute("SHOW TABLES").fetchall():
        cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
        tables[t] = [{"name": c[1], "type": c[2]} for c in cols]
    return {"tables": tables}

def validate_sql(sql: str) -> bool:
    if not sql:
        return False
    s = sql.strip().lower()
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        if len(parts) != 1:
            return False
        s = parts[0]
    if not s.startswith("select") and not s.startswith("with"):
        return False
    for bad in SAFE_SQL_DENY:
        if bad in s:
            return False
    return True

def plan_sql(*, base_url: str, model: str, schema: Dict[str, Any], question: str) -> Dict[str, Any]:
    system = (
        "You are a data analyst.\n"
        "Given DB schema and a question, output ONLY JSON with a SQL query.\n"
        "Rules: SELECT/CTE only (no writes). Add LIMIT 200.\n"
        "Format: {\"intent\":\"sql\",\"sql\":\"...\",\"notes\":\"...\"}"
    )
    user = json.dumps({"schema": schema, "question": question}, ensure_ascii=False)
    text = ollama_chat(base_url=base_url, model=model, messages=[
        {"role":"system","content":system},
        {"role":"user","content":user}
    ])
    obj = extract_json(text) or {}
    sql = obj.get("sql","")
    if not validate_sql(sql):
        return {"ok": False, "error": "LLM produced unsafe/invalid SQL", "raw": text[:800]}
    return {"ok": True, "sql": sql, "notes": obj.get("notes",""), "raw": text[:800]}
