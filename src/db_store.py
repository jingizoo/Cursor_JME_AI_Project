import json
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb
import pandas as pd

# Connection lock to prevent concurrent access issues
_db_lock = threading.Lock()

# Only registry tables - all data tables are created at runtime from ingested files
CANON_DDL = [
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
    """
    CREATE TABLE IF NOT EXISTS raw_sheet_registry (
        file TEXT,
        sheet TEXT,
        file_size BIGINT,
        file_mtime BIGINT,
        raw_table TEXT,
        n_rows BIGINT,
        n_cols BIGINT,
        updated_ts DOUBLE,
        PRIMARY KEY (file, sheet, file_size, file_mtime)
    )
    """,
]

def connect(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Create a DuckDB connection with proper configuration for concurrent access.
    
    Args:
        db_path: Path to DuckDB database file
        read_only: If True, opens in read-only mode (allows concurrent reads)
    
    Returns:
        DuckDB connection object
    """
    db_str = str(db_path)
    
    # DuckDB supports concurrent reads natively, but we need to:
    # 1. Use separate connections for each request (already done)
    # 2. Close connections quickly (done in finally blocks)
    # 3. For writes, use locking to prevent conflicts
    
    if read_only:
        # For read-only, try to use read_only mode if supported
        # DuckDB allows multiple read connections simultaneously
        try:
            # Try read_only parameter (available in DuckDB 0.9.0+)
            con = duckdb.connect(db_str, read_only=True)
        except Exception:
            # Fallback to regular connection if read_only not supported
            # Still works for concurrent reads, just not explicitly read-only
            con = duckdb.connect(db_str)
    else:
        # For write operations, use standard connection
        # DuckDB handles write locks internally
        con = duckdb.connect(db_str)
    
    # Execute DDL only for write connections
    if not read_only:
        with _db_lock:
            for ddl in CANON_DDL:
                try:
                    con.execute(ddl)
                except Exception:
                    # Table might already exist, ignore
                    pass
    
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

def upsert_raw_sheet(
    con,
    *,
    file: str,
    sheet: str,
    file_size: int,
    file_mtime: int,
    raw_table: str,
    n_rows: int,
    n_cols: int,
) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO raw_sheet_registry
        (file, sheet, file_size, file_mtime, raw_table, n_rows, n_cols, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [file, sheet, int(file_size), int(file_mtime), raw_table, int(n_rows), int(n_cols), time.time()],
    )

def find_raw_sheet(
    con,
    *,
    file: str,
    sheet: str,
    file_size: int,
    file_mtime: int,
) -> Optional[Dict[str, Any]]:
    row = con.execute(
        "SELECT raw_table, n_rows, n_cols, updated_ts FROM raw_sheet_registry WHERE file=? AND sheet=? AND file_size=? AND file_mtime=?",
        [file, sheet, int(file_size), int(file_mtime)],
    ).fetchone()
    if not row:
        return None
    return {"raw_table": row[0], "n_rows": int(row[1] or 0), "n_cols": int(row[2] or 0), "updated_ts": row[3]}
