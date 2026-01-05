import re
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, List

import numpy as np
import pandas as pd

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from .db_store import connect, upsert_mapping, find_mapping, append_rows, upsert_raw_sheet, find_raw_sheet
from .schema_agent import summarize_schema, infer_sheet_mapping
from .vector_db import store_pdf_embeddings, store_wiki_embeddings
from .wiki_extractor import extract_wiki_from_url
from .utils_columns import normalize_columns

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
    df = normalize_columns(df)  # ✅ normalize here
    return df

def extract_pdf_tables(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extract tables from PDF file.
    Returns list of {page_num, table_df} for each table found.
    """
    if not PDF_AVAILABLE:
        return []
    
    tables = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables()
                for table_idx, table in enumerate(page_tables):
                    if table and len(table) > 1:  # At least header + 1 row
                        # Convert to DataFrame
                        df = pd.DataFrame(table[1:], columns=table[0] if table[0] else None)
                        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
                        df = normalize_columns(df)  # ✅ normalize here too
                        if df.shape[0] > 0 and df.shape[1] > 0:
                            tables.append({
                                "page": page_num,
                                "table_idx": table_idx,
                                "df": df,
                                "sheet_name": f"page_{page_num}_table_{table_idx + 1}"
                            })
    except Exception as e:
        # Return empty list on error, will be caught by caller
        pass
    
    return tables

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
    df = normalize_columns(df)  # ✅ enforce before writing to DuckDB
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

def ingest_folder(*, data_dir: Path, db_path: Path, base_url: str, model: str, force: bool = False, wiki_urls: Optional[List[str]] = None, wiki_api_key: Optional[str] = None, exclude_files: Optional[List[str]] = None):
    con = connect(db_path)
    ingested = 0
    skipped = 0
    errors = []
    
    # Normalize exclude list (case-insensitive matching)
    exclude_set = set(f.lower() for f in (exclude_files or []))

    # Process Excel files
    for xf in sorted(list(data_dir.glob("*.xlsx")) + list(data_dir.glob("*.xlsm"))):
        # Skip excluded files
        if xf.name.lower() in exclude_set:
            skipped += 1
            continue
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

                # Note: normalize_and_insert is no longer used - we only create raw tables
                # The raw table is already created above via materialize_raw_sheet()
                ingested += 1

            except Exception as e:
                errors.append({"file": xf.name, "sheet": sheet, "error": str(e)})

    # Process PDF files
    if PDF_AVAILABLE:
        for pdf_path in sorted(data_dir.glob("*.pdf")):
            # Skip excluded files
            if pdf_path.name.lower() in exclude_set:
                skipped += 1
                continue
                
            st = pdf_path.stat()
            file_size, file_mtime = int(st.st_size), int(st.st_mtime)

            # Extract and store PDF text in vector DB (for semantic search)
            # Note: Uses embedding model, not the LLM model
            try:
                vec_result = store_pdf_embeddings(pdf_path, base_url=base_url, embedding_model="nomic-embed-text")
                if vec_result.get("ok"):
                    print(f"✓ Stored {vec_result.get('chunks_stored', 0)} text chunks from {pdf_path.name} in vector DB")
            except Exception as e:
                print(f"Warning: Failed to store PDF embeddings for {pdf_path.name}: {e}")

            try:
                pdf_tables = extract_pdf_tables(pdf_path)
                if not pdf_tables:
                    errors.append({"file": pdf_path.name, "error": "No tables found in PDF"})
                    continue
            except Exception as e:
                errors.append({"file": pdf_path.name, "error": f"Failed to read PDF: {e}"})
                continue

            for table_info in pdf_tables:
                sheet = table_info["sheet_name"]
                df = table_info["df"]

                if not force:
                    existing = find_mapping(con, pdf_path.name, sheet, file_size, file_mtime)
                    existing_raw = find_raw_sheet(con, file=pdf_path.name, sheet=sheet, file_size=file_size, file_mtime=file_mtime)
                    if existing and existing_raw:
                        skipped += 1
                        continue

                try:
                    if df is None or df.shape[0] == 0:
                        skipped += 1
                        continue

                    # Always create a raw table for the sheet
                    raw_table = materialize_raw_sheet(con, file=pdf_path.name, sheet=sheet, df=df)
                    upsert_raw_sheet(
                        con,
                        file=pdf_path.name,
                        sheet=sheet,
                        file_size=file_size,
                        file_mtime=file_mtime,
                        raw_table=raw_table,
                        n_rows=int(df.shape[0]),
                        n_cols=int(df.shape[1]),
                    )

                    schema = summarize_schema(df)
                    mapping_rec = infer_sheet_mapping(base_url=base_url, model=model, file=pdf_path.name, sheet=sheet, schema=schema)

                    upsert_mapping(con, {
                        "file": pdf_path.name,
                        "sheet": sheet,
                        "file_size": file_size,
                        "file_mtime": file_mtime,
                        "sheet_type": mapping_rec["sheet_type"],
                        "mapping": mapping_rec["mapping"],
                        "confidence": mapping_rec["confidence"],
                        "notes": mapping_rec.get("notes",""),
                    })

                    # Note: normalize_and_insert is no longer used - we only create raw tables
                    # The raw table is already created above via materialize_raw_sheet()
                    ingested += 1

                except Exception as e:
                    errors.append({"file": pdf_path.name, "sheet": sheet, "error": str(e)})
    else:
        # If PDF support not available, add a note
        errors.append({"file": "system", "error": "PDF support not available (install pdfplumber)"})

    # Process Wiki pages
    wiki_ingested = 0
    if wiki_urls:
        print(f"\n📚 Processing {len(wiki_urls)} wiki page(s)...")
        for wiki_url in wiki_urls:
            try:
                # Extract wiki content
                wiki_result = extract_wiki_from_url(wiki_url, api_key=wiki_api_key)
                if not wiki_result.get("ok"):
                    errors.append({"file": f"wiki:{wiki_url}", "error": wiki_result.get("error", "Unknown error")})
                    continue
                
                # Store in vector DB
                vec_result = store_wiki_embeddings(
                    title=wiki_result.get("title", "Wiki Page"),
                    content=wiki_result.get("content", ""),
                    url=wiki_result.get("url", wiki_url),
                    base_url=base_url,
                    embedding_model="nomic-embed-text"
                )
                
                if vec_result.get("ok"):
                    wiki_ingested += 1
                    print(f"✓ Stored {vec_result.get('chunks_stored', 0)} chunks from wiki: {wiki_result.get('title', wiki_url)}")
                else:
                    errors.append({"file": f"wiki:{wiki_url}", "error": vec_result.get("error", "Failed to store embeddings")})
            except Exception as e:
                errors.append({"file": f"wiki:{wiki_url}", "error": f"Failed to process wiki: {e}"})

    return {"ok": True, "ingested_sheets": ingested, "wiki_pages": wiki_ingested, "skipped": skipped, "errors": errors}
