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
    # Keep prompt SHORT to reduce LLM processing time
    # CRITICAL: Emphasize JSON-only output with no explanatory text
    system_parts = [
        "You are a SQL generator. Your response must be ONLY valid JSON.\n",
        "CRITICAL RULES:\n",
        "1. Start your response with { (opening brace)\n",
        "2. End your response with } (closing brace)\n",
        "3. NO text before the opening brace\n",
        "4. NO text after the closing brace\n",
        "5. NO explanations, NO comments, NO markdown\n",
        "6. ALWAYS generate SQL - even if unsure, make your best attempt\n",
        "7. If column name is unclear, use common patterns (e.g., 'user', 'users', 'user_name', 'user_id')\n",
        "8. Output ONLY: {\"sql\":\"SELECT ...\",\"notes\":\"...\"}\n",
        "Example: {\"sql\":\"SELECT COUNT(*) as count FROM table_name LIMIT 200\",\"notes\":\"\"}\n",
        "Rules: SELECT/CTE only. Add LIMIT 200. Always provide SQL, never leave sql field empty.\n"
    ]
    
    if pdf_context:
        # Keep PDF context brief to reduce prompt size
        system_parts.append("\nPDF context:")
        for i, ctx in enumerate(pdf_context[:2], 1):  # Limit to 2 contexts
            system_parts.append(f"\n[{i}] {ctx.get('text', '')[:150]}...")  # Reduced from 300 to 150
    
    system = "".join(system_parts)
    
    # Build user message with schema and question
    # Keep it compact - only essential info
    user_data = {"schema": schema, "question": question}
    if pdf_context:
        # Limit PDF context in user message too
        user_data["pdf_context"] = [{"text": c.get("text", "")[:100]} for c in pdf_context[:2]]  # Reduced size
    
    user = json.dumps(user_data, ensure_ascii=False, separators=(',', ':'))  # Compact JSON (no spaces)
    
    # Use num_predict to limit generation and speed up (SQL is usually short)
    # Make it configurable via environment variable, default to 2048 for safety
    num_predict_limit = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))  # Default 2048, was 1024
    
    try:
        text = ollama_chat(base_url=base_url, model=model, messages=[
            {"role":"system","content":system},
            {"role":"user","content":user}
        ], num_predict=num_predict_limit)
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to get response from LLM: {e}",
            "hint": "Check Ollama connection, model availability, or try a smaller model.",
            "raw": ""
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
    
    # Enforce LIMIT even if LLM forgets (performance optimization)
    sql = ensure_limit(sql, limit=200)
    
    result = {"ok": True, "sql": sql, "notes": obj.get("notes",""), "raw": text[:800]}
    if pdf_context:
        result["pdf_context_used"] = len(pdf_context)
    
    return result
