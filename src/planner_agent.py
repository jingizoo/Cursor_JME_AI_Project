import json
import os
import re
from typing import Any, Dict, Optional

import duckdb

from .llm_client import ollama_chat, extract_json
from .vector_db import search_pdf_context

SAFE_SQL_DENY = ["insert","update","delete","drop","alter","create","attach","detach","copy","pragma","call"]

def ensure_limit(sql: str, limit: int = 200) -> str:
    """
    Ensure SQL query has a LIMIT clause. If not present, append it.
    Handles CTEs and nested queries safely.
    """
    if not sql:
        return sql
    s = (sql or "").strip().rstrip(";").strip()
    # Check if LIMIT already exists (case-insensitive)
    if re.search(r"\blimit\s+\d+", s, flags=re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {int(limit)}"

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

def plan_sql(*, base_url: str, model: str, schema: Dict[str, Any], question: str, include_pdf_context: bool = True) -> Dict[str, Any]:
    """
    Plan SQL query from natural language question.
    
    Args:
        base_url: Ollama base URL
        model: LLM model name
        schema: Database schema (tables and columns)
        question: Natural language question
        include_pdf_context: Whether to search PDF vector DB for relevant context
            Can be overridden by JME_DISABLE_PDF_CONTEXT environment variable
    """
    # Check environment variable to disable PDF context (performance optimization)
    if os.getenv("JME_DISABLE_PDF_CONTEXT", "0").lower() in ("1", "true", "yes"):
        include_pdf_context = False
    
    # Retrieve relevant PDF context if enabled
    pdf_context = []
    if include_pdf_context:
        try:
            pdf_context = search_pdf_context(question, base_url=base_url, embedding_model="nomic-embed-text", top_k=3)
        except Exception as e:
            print(f"Warning: PDF context search failed: {e}")
    
    # Build system prompt with PDF context if available
    system_parts = [
        "You are a data analyst.\n",
        "Given DB schema and a question, output ONLY JSON with a SQL query.\n",
        "Rules: SELECT/CTE only (no writes). Add LIMIT 200.\n",
        "Format: {\"intent\":\"sql\",\"sql\":\"...\",\"notes\":\"...\"}"
    ]
    
    if pdf_context:
        system_parts.append("\n\nRelevant context from PDF documents:")
        for i, ctx in enumerate(pdf_context, 1):
            system_parts.append(f"\n[{i}] From {ctx.get('source_file', 'unknown')} (page {ctx.get('page', 0)}):")
            system_parts.append(f"   {ctx.get('text', '')[:300]}...")
        system_parts.append("\n\nUse this context to better understand the question and data structure.")
    
    system = "".join(system_parts)
    
    # Build user message with schema and question
    user_data = {"schema": schema, "question": question}
    if pdf_context:
        user_data["pdf_context"] = [{"source": c.get("source_file"), "text": c.get("text", "")[:200]} for c in pdf_context]
    
    user = json.dumps(user_data, ensure_ascii=False)
    
    text = ollama_chat(base_url=base_url, model=model, messages=[
        {"role":"system","content":system},
        {"role":"user","content":user}
    ])
    obj = extract_json(text)
    
    # Better error handling for JSON extraction failures
    if obj is None:
        # Try to extract SQL directly if JSON extraction failed
        # Look for SQL in markdown code blocks
        sql_match = re.search(r'```(?:sql)?\s*(SELECT.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql = sql_match.group(1).strip()
            obj = {"sql": sql, "notes": "Extracted from markdown code block"}
        else:
            # Look for SQL after common prefixes
            sql_match = re.search(r'(?:sql|query):\s*(SELECT.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                obj = {"sql": sql, "notes": "Extracted from text response"}
            else:
                return {
                    "ok": False, 
                    "error": "LLM response is not valid JSON and no SQL found. The response may contain explanatory text before/after the JSON.",
                    "raw": text[:1000],
                    "hint": "The LLM may have added text before/after the JSON. Check the 'raw' field for the full response."
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
    
    if not validate_sql(sql):
        return {
            "ok": False, 
            "error": "LLM produced unsafe/invalid SQL", 
            "raw": text[:1000],
            "sql_attempted": sql[:200]
        }
    
    # Enforce LIMIT even if LLM forgets (performance optimization)
    sql = ensure_limit(sql, limit=200)
    
    result = {"ok": True, "sql": sql, "notes": obj.get("notes",""), "raw": text[:800]}
    if pdf_context:
        result["pdf_context_used"] = len(pdf_context)
    
    return result
