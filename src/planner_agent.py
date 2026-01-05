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
    
    # Build system prompt - shorter and schema-format-accurate
    system_parts = [
        "You are a DuckDB SQL generator. Return ONLY valid JSON.\n",
        "CRITICAL RULES:\n",
        "1) Response must start with '{' and end with '}'.\n",
        "2) No text outside the JSON.\n",
        "3) Output JSON: {\"sql\":\"...\",\"notes\":\"...\"}\n",
        "4) SQL must be ONE statement only. SELECT or WITH only.\n",
        "5) No writes (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/etc).\n",
        "6) ALWAYS add LIMIT 200.\n",
        "7) Use ONLY tables/columns that exist in schema.\n",
        "\n",
        "SCHEMA FORMAT:\n",
        "- schema.tables is an object: { table_name: [\"col1\",\"col2\", ...] }\n",
        "- Use ONLY those column strings.\n",
        "\n",
        "IMPORTANT (JSON SAFETY):\n",
        "- Do NOT use double-quotes for identifiers inside SQL (it breaks JSON escaping).\n",
        "- Prefer bare identifiers: SELECT col_0 FROM raw__... LIMIT 200\n",
        "- If you must quote identifiers, use backticks (`) not double quotes.\n",
        "\n",
        "Example:\n",
        "{\"sql\":\"SELECT col_0, col_1 FROM raw__table LIMIT 200\",\"notes\":\"\"}\n",
    ]
    
    system = "".join(system_parts)
    
    if pdf_context:
        # Keep PDF context brief to reduce prompt size
        system += "\nPDF context:\n"
        for i, ctx in enumerate(pdf_context[:2], 1):  # Limit to 2 contexts
            system += f"[{i}] {ctx.get('text', '')[:150]}...\n"  # Reduced from 300 to 150
    
    # Build user message with schema and question
    # Keep it compact - only essential info
    user_data = {"schema": schema, "question": question}
    if pdf_context:
        # Limit PDF context in user message too
        user_data["pdf_context"] = [{"text": c.get("text", "")[:100]} for c in pdf_context[:2]]  # Reduced size
    
    user = json.dumps(user_data, ensure_ascii=False, separators=(',', ':'))  # Compact JSON (no spaces)
    
    # Use num_predict to limit generation and speed up (SQL is usually short)
    # For smaller models (3b), use lower limits. For larger models (8b+), use higher limits.
    # Make it configurable via environment variable
    default_num_predict = 512 if ("3b" in model.lower() or "1b" in model.lower()) else 1024
    num_predict_limit = int(os.getenv("OLLAMA_NUM_PREDICT", str(default_num_predict)))
    
    # Timeout: smaller models might be slower, but also might hang. Use configurable timeout.
    timeout_sec = int(os.getenv("OLLAMA_TIMEOUT", "300"))  # Default 5 minutes
    
    try:
        print(f"[plan_sql] Using model: {model}, num_predict: {num_predict_limit}, timeout: {timeout_sec}s")
        text = ollama_chat(
            base_url=base_url, 
            model=model, 
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":user}
            ], 
            num_predict=num_predict_limit,
            timeout_sec=timeout_sec
        )
    except Exception as e:
        error_msg = str(e)
        hint = f"LLM call failed with model '{model}'. "
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            hint += f"Request timed out after {timeout_sec}s. Try: export OLLAMA_TIMEOUT=600 for longer timeout, or use a faster model."
        elif "connection" in error_msg.lower():
            hint += f"Connection error. Check if Ollama is running at {base_url} and model '{model}' is available (run: ollama list)."
        else:
            hint += f"Error: {error_msg}. Check Ollama logs or try a different model."
        return {
            "ok": False,
            "error": f"Failed to get response from LLM: {error_msg}",
            "hint": hint,
            "raw": "",
            "model": model  # Include model name in error response
        }
    
    # Handle empty response
    if not text or not text.strip():
        return {
            "ok": False,
            "error": "LLM returned empty response. Possible causes: 1) num_predict limit too low, 2) Model failed to generate, 3) Response was cut off, 4) Prompt too large.",
            "hint": "Try: 1) Using a smaller model (qwen3:4b), 2) Reducing schema size, 3) Checking Ollama logs, 4) Increasing num_predict limit",
            "raw": text if text else "(empty string)",
            "diagnostics": {
                "response_length": len(text) if text else 0,
                "model": model,
                "num_predict": num_predict_limit
            }
        }
    
    obj = extract_json(text)
    
    # Better error handling for JSON extraction failures
    if obj is None:
        # Try multiple strategies to extract SQL/JSON
        
        # Strategy 1: Try to find JSON after removing common prefixes
        # Remove common LLM prefixes like "Here's the SQL:", "The query is:", etc.
        cleaned_text = text.strip()
        prefixes_to_remove = [
            r'^(here\'?s?|the|this is|below is|following is|i\'?ll|let me).*?:\s*',
            r'^(json|sql|query|response|answer|result).*?:\s*',
            r'^```(?:json|sql)?\s*',
            r'```\s*$',
            r'^[^{]*',  # Remove everything before first {
        ]
        for pattern in prefixes_to_remove:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        
        # Remove everything after last }
        cleaned_text = re.sub(r'}[^}]*$', '}', cleaned_text, flags=re.DOTALL)
        cleaned_text = cleaned_text.strip()
        
        # Try to extract JSON from cleaned text
        if cleaned_text:
            obj = extract_json(cleaned_text)
        
        if obj is None:
            # Strategy 2: Extract SQL directly from markdown code blocks
            sql_match = re.search(r'```(?:sql)?\s*(SELECT.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                # Remove markdown formatting if present
                sql = re.sub(r'^```(?:sql)?\s*', '', sql, flags=re.IGNORECASE)
                sql = re.sub(r'\s*```\s*$', '', sql)
                sql = sql.rstrip(';').strip()
                if sql and sql.upper().startswith('SELECT'):
                    obj = {"sql": sql, "notes": "Extracted from markdown code block"}
        
        if obj is None:
            # Strategy 3: Look for SQL after common prefixes
            sql_match = re.search(r'(?:sql|query|select|here\'?s? the sql).*?:\s*(SELECT\s+.*?)(?:\n\n|$|\Z|```)', text, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                # Clean up SQL
                sql = sql.rstrip(';').strip()
                sql = re.sub(r'\s*```\s*$', '', sql)  # Remove trailing ```
                if sql and sql.upper().startswith('SELECT'):
                    obj = {"sql": sql, "notes": "Extracted from text response"}
        
        if obj is None:
            # Strategy 4: Try to find any SELECT statement (most permissive)
            sql_match = re.search(r'(SELECT\s+[^;]+)', text, re.DOTALL | re.IGNORECASE)
            if sql_match:
                sql = sql_match.group(1).strip()
                sql = sql.rstrip(';').strip()
                sql = re.sub(r'\s*```\s*$', '', sql)  # Remove trailing ```
                # Remove any trailing explanatory text
                sql = re.sub(r'\s+[^S].*$', '', sql, flags=re.DOTALL)  # Stop at non-SQL text
                if sql and sql.upper().startswith('SELECT') and len(sql) > 10:
                    obj = {"sql": sql, "notes": "Extracted SELECT statement from response"}
        
        if obj is None:
            # Strategy 5: Try to extract from JSON-like structure even if malformed
            # Look for {"sql": pattern
            json_like_match = re.search(r'\{\s*["\']?sql["\']?\s*:\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
            if json_like_match:
                sql = json_like_match.group(1).strip()
                if sql and sql.upper().startswith('SELECT'):
                    obj = {"sql": sql, "notes": "Extracted from JSON-like structure"}
        
        if obj is None:
            # Final fallback: return detailed error
            return {
                "ok": False, 
                "error": "LLM response is not valid JSON and no SQL found. The response may contain explanatory text before/after the JSON.",
                "raw": text[:2000],  # Show more context
                "hint": "The LLM may have added text before/after the JSON. Check the 'raw' field for the full response. Consider using a smaller model or adjusting the prompt.",
                "cleaned_attempt": cleaned_text[:500] if cleaned_text else "No cleaned text",  # Show cleaned version
                "extraction_attempts": "Tried: JSON extraction, markdown blocks, text patterns, SELECT statements, JSON-like structures"
            }
    else:
        sql = obj.get("sql", "")
        if not sql or not sql.strip():
            # If SQL is empty, try to generate a basic query based on the question
            # Extract table name from question if possible
            question_lower = question.lower()
            table_name = None
            for t in schema.get("tables", {}).keys():
                if t.lower() in question_lower:
                    table_name = t
                    break
            
            if table_name:
                # Generate a basic COUNT query as fallback
                sql = f"SELECT COUNT(*) as count FROM {table_name} LIMIT 200"
                return {
                    "ok": True,
                    "sql": sql,
                    "notes": f"Generated fallback query - LLM returned empty SQL. Original notes: {obj.get('notes', '')}",
                    "raw": text[:1000],
                    "fallback": True
                }
            else:
                return {
                    "ok": False,
                    "error": "LLM returned JSON but SQL field is empty. Could not determine table from question.",
                    "raw": text[:1000],
                    "parsed_json": obj,
                    "hint": "Try rephrasing your question to include the table name, or check if the table exists in the schema."
                }
    
    if not validate_sql(sql):
        return {
            "ok": False, 
            "error": "LLM produced unsafe/invalid SQL", 
            "raw": text[:1000],
            "sql_attempted": sql[:200]
        }
    
    # Fix common SQL syntax issues for DuckDB
    # Replace backticks with double quotes (DuckDB uses double quotes, not backticks)
    sql = sql.replace('`', '"')
    
    # Enforce LIMIT even if LLM forgets (performance optimization)
    sql = ensure_limit(sql, limit=200)
    
    result = {"ok": True, "sql": sql, "notes": obj.get("notes",""), "raw": text[:800]}
    if pdf_context:
        result["pdf_context_used"] = len(pdf_context)
    
    return result
