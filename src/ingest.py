import re
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .db_store import connect, upsert_mapping, find_mapping, append_rows, upsert_raw_sheet, find_raw_sheet
from .schema_agent import summarize_schema, infer_sheet_mapping

def parse_num(x) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in {"nan","none","null"}:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    m = re.search(r"-?\d[\d,]*\.?\d*", s)
    if not m:
        return None
    num = m.group(0).replace(",", "")
    try:
        v = float(num)
        return -v if neg else v
    except Exception:
        return None

def detect_header_row(xf: Path, sheet: str, max_scan: int = 25) -> int:
    preview = pd.read_excel(str(xf), sheet_name=sheet, header=None, nrows=max_scan, engine="openpyxl")
    best_row = 0
    best_score = -1
    for i in range(min(max_scan, len(preview))):
        score = int(preview.iloc[i].notna().sum())
        if score > best_score:
            best_score = score
            best_row = i
    return best_row

def read_sheet(xf: Path, sheet: str) -> pd.DataFrame:
    hdr = detect_header_row(xf, sheet)
    df = pd.read_excel(str(xf), sheet_name=sheet, header=hdr, engine="openpyxl")
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    return df

def _safe_ident(s: str) -> str:
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

def materialize_raw_sheet(con, *, file: str, sheet: str, df: pd.DataFrame) -> str:
    """
    Create/replace a raw DuckDB table for the sheet so it can be queried later via /ask.
    Table name is deterministic per (file, sheet) so re-ingests overwrite the same table.
    """
    base = f"raw__{_safe_ident(Path(file).stem)}__{_safe_ident(sheet)}__{_short_hash(file + '|' + sheet)}"
    # Quote identifier to be safe even if it contains odd characters (shouldn't after _safe_ident).
    con.register("df_tmp", df)
    con.execute(f'CREATE OR REPLACE TABLE "{base}" AS SELECT * FROM df_tmp')
    con.unregister("df_tmp")
    return base

def normalize_and_insert(con, file: str, sheet: str, sheet_type: str, mapping: Dict[str, Any], df: pd.DataFrame):
    df2 = df.copy()
    cols = {str(c): c for c in df2.columns}
    def col(name):
        if name is None: return None
        return cols.get(str(name))

    if sheet_type == "invoices":
        out = pd.DataFrame({
            "source_file": file,
            "source_sheet": sheet,
            "invoice_id": df2[col(mapping.get("invoice_id"))] if col(mapping.get("invoice_id")) else None,
            "invoice_date": pd.to_datetime(df2[col(mapping.get("invoice_date"))], errors="coerce") if col(mapping.get("invoice_date")) else None,
            "due_date": pd.to_datetime(df2[col(mapping.get("due_date"))], errors="coerce") if col(mapping.get("due_date")) else None,
            "client": df2[col(mapping.get("client"))] if col(mapping.get("client")) else None,
            "taxable_value": df2[col(mapping.get("taxable_value"))].apply(parse_num) if col(mapping.get("taxable_value")) else None,
            "gst_amount": df2[col(mapping.get("gst_amount"))].apply(parse_num) if col(mapping.get("gst_amount")) else None,
            "invoice_total": df2[col(mapping.get("invoice_total"))].apply(parse_num) if col(mapping.get("invoice_total")) else None,
        }).dropna(subset=["invoice_id"], how="all")
        append_rows(con, "invoices", out)

    elif sheet_type == "payments":
        out = pd.DataFrame({
            "source_file": file,
            "source_sheet": sheet,
            "payment_date": pd.to_datetime(df2[col(mapping.get("payment_date"))], errors="coerce") if col(mapping.get("payment_date")) else None,
            "invoice_id": df2[col(mapping.get("invoice_id"))] if col(mapping.get("invoice_id")) else None,
            "client": df2[col(mapping.get("client"))] if col(mapping.get("client")) else None,
            "amount": df2[col(mapping.get("amount"))].apply(parse_num) if col(mapping.get("amount")) else None,
            "bank_ref": df2[col(mapping.get("bank_ref"))] if col(mapping.get("bank_ref")) else None,
            "mode": df2[col(mapping.get("mode"))] if col(mapping.get("mode")) else None,
        }).dropna(subset=["amount"], how="all")
        append_rows(con, "payments", out)

    elif sheet_type == "expenses":
        out = pd.DataFrame({
            "source_file": file,
            "source_sheet": sheet,
            "expense_date": pd.to_datetime(df2[col(mapping.get("expense_date"))], errors="coerce") if col(mapping.get("expense_date")) else None,
            "vendor": df2[col(mapping.get("vendor"))] if col(mapping.get("vendor")) else None,
            "category": df2[col(mapping.get("category"))] if col(mapping.get("category")) else None,
            "taxable_value": df2[col(mapping.get("taxable_value"))].apply(parse_num) if col(mapping.get("taxable_value")) else None,
            "gst_amount": df2[col(mapping.get("gst_amount"))].apply(parse_num) if col(mapping.get("gst_amount")) else None,
            "tds_amount": df2[col(mapping.get("tds_amount"))].apply(parse_num) if col(mapping.get("tds_amount")) else None,
            "paid_amount": df2[col(mapping.get("paid_amount"))].apply(parse_num) if col(mapping.get("paid_amount")) else None,
        }).dropna(subset=["paid_amount"], how="all")
        append_rows(con, "expenses", out)

    elif sheet_type == "bank_txns":
        credit_col = col(mapping.get("credit"))
        debit_col = col(mapping.get("debit"))
        amount_col = col(mapping.get("amount"))

        if amount_col is not None:
            amt = df2[amount_col].apply(parse_num)
            direction = df2[col(mapping.get("direction"))] if col(mapping.get("direction")) else np.where(amt>=0, "IN", "OUT")
            amt_abs = amt.abs()
        else:
            credit = df2[credit_col].apply(parse_num) if credit_col is not None else None
            debit = df2[debit_col].apply(parse_num) if debit_col is not None else None
            amt_abs = (credit.fillna(0) + debit.fillna(0)).replace(0, np.nan)
            direction = np.where(credit.fillna(0)>0, "IN", np.where(debit.fillna(0)>0, "OUT", None))

        out = pd.DataFrame({
            "source_file": file,
            "source_sheet": sheet,
            "txn_date": pd.to_datetime(df2[col(mapping.get("txn_date"))], errors="coerce") if col(mapping.get("txn_date")) else None,
            "description": df2[col(mapping.get("description"))] if col(mapping.get("description")) else None,
            "amount": amt_abs,
            "direction": direction,
            "reference": df2[col(mapping.get("reference"))] if col(mapping.get("reference")) else None,
        }).dropna(subset=["amount"], how="all")
        append_rows(con, "bank_txns", out)

def ingest_folder(*, data_dir: Path, db_path: Path, base_url: str, model: str, force: bool = False):
    con = connect(db_path)
    ingested = 0
    skipped = 0
    errors = []

    for xf in sorted(list(data_dir.glob("*.xlsx")) + list(data_dir.glob("*.xlsm"))):
        st = xf.stat()
        file_size, file_mtime = int(st.st_size), int(st.st_mtime)

        try:
            xls = pd.ExcelFile(str(xf), engine="openpyxl")
        except Exception as e:
            errors.append({"file": xf.name, "error": str(e)})
            continue

        for sheet in xls.sheet_names:
            if not force:
                # Don't skip if we haven't materialized a raw table yet (supports backfilling after upgrade).
                existing = find_mapping(con, xf.name, sheet, file_size, file_mtime)
                existing_raw = find_raw_sheet(con, file=xf.name, sheet=sheet, file_size=file_size, file_mtime=file_mtime)
                if existing and existing_raw:
                    skipped += 1
                    continue

            try:
                df = read_sheet(xf, sheet)
                if df is None or df.shape[0] == 0:
                    skipped += 1
                    continue

                # Always create a raw table for the sheet (so it can be queried later).
                raw_table = materialize_raw_sheet(con, file=xf.name, sheet=sheet, df=df)
                upsert_raw_sheet(
                    con,
                    file=xf.name,
                    sheet=sheet,
                    file_size=file_size,
                    file_mtime=file_mtime,
                    raw_table=raw_table,
                    n_rows=int(df.shape[0]),
                    n_cols=int(df.shape[1]),
                )

                schema = summarize_schema(df)
                mapping_rec = infer_sheet_mapping(base_url=base_url, model=model, file=xf.name, sheet=sheet, schema=schema)

                upsert_mapping(con, {
                    "file": xf.name,
                    "sheet": sheet,
                    "file_size": file_size,
                    "file_mtime": file_mtime,
                    "sheet_type": mapping_rec["sheet_type"],
                    "mapping": mapping_rec["mapping"],
                    "confidence": mapping_rec["confidence"],
                    "notes": mapping_rec.get("notes",""),
                })

                normalize_and_insert(con, xf.name, sheet, mapping_rec["sheet_type"], mapping_rec["mapping"], df)
                ingested += 1

            except Exception as e:
                errors.append({"file": xf.name, "sheet": sheet, "error": str(e)})

    return {"ok": True, "ingested_sheets": ingested, "skipped": skipped, "errors": errors}
