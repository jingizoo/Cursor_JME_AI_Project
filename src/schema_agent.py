import json
import os
from typing import Any, Dict

import pandas as pd

from .llm_client import ollama_chat, extract_json

SHEET_TYPES = ["unknown"]  # No predefined types - all data is analyzed dynamically

def summarize_schema(df: pd.DataFrame, max_cols: int = 30, samples_per_col: int = 5) -> Dict[str, Any]:
    cols = [str(c) for c in df.columns][:max_cols]
    out_cols = []
    for c in cols:
        series = df[c].astype(str).head(50)
        samples = []
        for v in series:
            v = str(v).strip()
            if v and v.lower() not in {"nan","none"}:
                samples.append(v)
            if len(samples) >= samples_per_col:
                break
        out_cols.append({"name": c, "samples": samples})
    return {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1]), "columns": out_cols}

def infer_sheet_mapping(*, base_url: str, model: str, file: str, sheet: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    system = (
        "You are a data schema analysis agent. Return ONLY JSON.\n"
        "Analyze the provided schema and describe what type of data it contains.\n"
        "JSON format:\n"
        "{\"sheet_type\":\"unknown\",\"confidence\":0-1,\"mapping\":{},\"notes\":\"description of data content\"}\n"
        "Since this is a dynamic data analysis app, always use sheet_type=\"unknown\".\n"
        "The 'mapping' field should be empty {} - we don't map to predefined schemas.\n"
        "The 'notes' field should describe what the data appears to contain (e.g., 'Sales data with dates and amounts', 'Employee records', etc.).\n"
        "Confidence guidelines:\n"
        "- 0.7-1.0: Clear understanding of data structure and content\n"
        "- 0.4-0.6: Partial understanding of data\n"
        "- 0.0-0.3: Unclear or minimal data\n"
        "Always return sheet_type=\"unknown\" and focus on describing the data in 'notes'."
    )
    user = json.dumps({"file": file, "sheet": sheet, "schema": schema}, ensure_ascii=False)

    # Use configurable num_predict limit
    num_predict_limit = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
    text = ollama_chat(base_url=base_url, model=model, messages=[
        {"role":"system","content":system},
        {"role":"user","content":user},
    ], num_predict=num_predict_limit)
    obj = extract_json(text)
    if obj is None:
        # If JSON extraction fails, return empty dict (schema agent can handle this)
        obj = {}
    st = obj.get("sheet_type","unknown")
    # Always use "unknown" for dynamic data analysis
    st = "unknown"
    # Mapping is not used for dynamic tables - always empty
    mapping = {}
    conf = float(obj.get("confidence", 0.5) or 0.5)  # Default to 0.5 if not provided
    notes = str(obj.get("notes",""))[:500]
    return {"sheet_type": st, "confidence": conf, "mapping": mapping, "notes": notes, "raw": text[:800]}
