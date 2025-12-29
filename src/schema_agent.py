import json
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
        "If unsure: sheet_type=unknown, mapping={}, confidence low."
    )
    user = json.dumps({"file": file, "sheet": sheet, "schema": schema}, ensure_ascii=False)

    text = ollama_chat(base_url=base_url, model=model, messages=[
        {"role":"system","content":system},
        {"role":"user","content":user},
    ])
    obj = extract_json(text) or {}
    st = obj.get("sheet_type","unknown")
    if st not in SHEET_TYPES:
        st = "unknown"
    mapping = obj.get("mapping") if isinstance(obj.get("mapping"), dict) else {}
    conf = float(obj.get("confidence", 0.0) or 0.0)
    notes = str(obj.get("notes",""))[:500]
    return {"sheet_type": st, "confidence": conf, "mapping": mapping, "notes": notes, "raw": text[:800]}
