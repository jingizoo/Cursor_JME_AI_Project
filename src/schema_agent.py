import json
import os
from typing import Any, Dict

import pandas as pd

from .llm_client import ollama_chat, extract_json

SHEET_TYPES = ["invoices", "payments", "expenses", "bank_txns", "unknown"]

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
        "You are a data schema mapping agent. Return ONLY JSON.\n"
        "Choose sheet_type from: invoices, payments, expenses, bank_txns, unknown.\n"
        "Output mapping from canonical fields to input column names.\n"
        "Canonical fields:\n"
        "- invoices: invoice_id, invoice_date, due_date, client, taxable_value, gst_amount, invoice_total\n"
        "- payments: payment_date, invoice_id, client, amount, bank_ref, mode\n"
        "- expenses: expense_date, vendor, category, taxable_value, gst_amount, tds_amount, paid_amount\n"
        "- bank_txns: txn_date, description, amount, direction, reference (or credit/debit columns)\n"
        "JSON format:\n"
        "{\"sheet_type\":\"...\",\"confidence\":0-1,\"mapping\":{...},\"notes\":\"...\"}\n"
        "Confidence guidelines:\n"
        "- 0.9-1.0: Clear match with multiple canonical fields found\n"
        "- 0.7-0.8: Good match with some canonical fields found\n"
        "- 0.5-0.6: Partial match with few canonical fields\n"
        "- 0.3-0.4: Weak match, uncertain classification\n"
        "- 0.0-0.2: No clear match, use 'unknown' type\n"
        "If you find 3+ matching canonical fields, use confidence >= 0.7. If unsure: sheet_type=unknown, mapping={}, confidence=0.2."
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
    if st not in SHEET_TYPES:
        st = "unknown"
    mapping = obj.get("mapping") if isinstance(obj.get("mapping"), dict) else {}
    conf = float(obj.get("confidence", 0.0) or 0.0)
    
    # If confidence is very low or missing, calculate based on mapping quality
    if conf < 0.3 and mapping:
        # Calculate confidence based on number of mapped fields
        canonical_fields = {
            "invoices": ["invoice_id", "invoice_date", "due_date", "client", "taxable_value", "gst_amount", "invoice_total"],
            "payments": ["payment_date", "invoice_id", "client", "amount", "bank_ref", "mode"],
            "expenses": ["expense_date", "vendor", "category", "taxable_value", "gst_amount", "tds_amount", "paid_amount"],
            "bank_txns": ["txn_date", "description", "amount", "direction", "reference"]
        }
        if st in canonical_fields:
            mapped_count = len([k for k in mapping.keys() if k in canonical_fields[st]])
            total_fields = len(canonical_fields[st])
            # Confidence = percentage of fields mapped, with minimum 0.3 for any mapping
            calculated_conf = max(0.3, min(0.95, mapped_count / total_fields))
            # Use the higher of LLM confidence or calculated confidence
            conf = max(conf, calculated_conf)
    
    notes = str(obj.get("notes",""))[:500]
    return {"sheet_type": st, "confidence": conf, "mapping": mapping, "notes": notes, "raw": text[:800]}
