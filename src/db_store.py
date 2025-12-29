import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb
import pandas as pd

CANON_DDL = [
    """
    CREATE TABLE IF NOT EXISTS invoices (
        source_file TEXT,
        source_sheet TEXT,
        invoice_id TEXT,
        invoice_date DATE,
        due_date DATE,
        client TEXT,
        taxable_value DOUBLE,
        gst_amount DOUBLE,
        invoice_total DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        source_file TEXT,
        source_sheet TEXT,
        payment_date DATE,
        invoice_id TEXT,
        client TEXT,
        amount DOUBLE,
        bank_ref TEXT,
        mode TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS expenses (
        source_file TEXT,
        source_sheet TEXT,
        expense_date DATE,
        vendor TEXT,
        category TEXT,
        taxable_value DOUBLE,
        gst_amount DOUBLE,
        tds_amount DOUBLE,
        paid_amount DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bank_txns (
        source_file TEXT,
        source_sheet TEXT,
        txn_date DATE,
        description TEXT,
        amount DOUBLE,
        direction TEXT,
        reference TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_registry (
        file TEXT,
        sheet TEXT,
        file_size BIGINT,
        file_mtime BIGINT,
        sheet_type TEXT,
        mapping_json TEXT,
        confidence DOUBLE,
        notes TEXT,
        updated_ts DOUBLE,
        PRIMARY KEY (file, sheet, file_size, file_mtime)
    )
    """,
]

def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    for ddl in CANON_DDL:
        con.execute(ddl)
    return con

def upsert_mapping(con, rec: Dict[str, Any]) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO schema_registry
        (file, sheet, file_size, file_mtime, sheet_type, mapping_json, confidence, notes, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            rec["file"], rec["sheet"], int(rec["file_size"]), int(rec["file_mtime"]),
            rec.get("sheet_type","unknown"),
            json.dumps(rec.get("mapping",{}), ensure_ascii=False),
            float(rec.get("confidence",0.0)),
            rec.get("notes",""),
            time.time()
        ]
    )

def find_mapping(con, file: str, sheet: str, file_size: int, file_mtime: int) -> Optional[Dict[str, Any]]:
    row = con.execute(
        "SELECT sheet_type, mapping_json, confidence, notes FROM schema_registry WHERE file=? AND sheet=? AND file_size=? AND file_mtime=?",
        [file, sheet, int(file_size), int(file_mtime)]
    ).fetchone()
    if not row:
        return None
    return {"sheet_type": row[0], "mapping": json.loads(row[1] or "{}"), "confidence": float(row[2] or 0), "notes": row[3] or ""}

def append_rows(con, table: str, df: pd.DataFrame) -> None:
    con.register("df_tmp", df)
    con.execute(f"INSERT INTO {table} SELECT * FROM df_tmp")
    con.unregister("df_tmp")
