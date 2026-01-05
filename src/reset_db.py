"""
Utility script to drop all tables and recreate only the necessary ones.
Run this to reset the database to a clean state.

Usage:
    python -m src.reset_db
    # Or from Python:
    from src.reset_db import reset_database
    reset_database(db_path)
"""

from pathlib import Path
from .db_store import connect, CANON_DDL

def reset_database(db_path: Path, keep_raw_tables: bool = False, drop_canonical: bool = True) -> dict:
    """
    Drop tables and recreate only the necessary registry tables.
    
    Args:
        db_path: Path to the DuckDB database file
        keep_raw_tables: If True, keep raw__* tables (only drop canonical/registry tables)
        drop_canonical: If True, drop canonical tables (invoices, payments, expenses, bank_txns)
        
    Returns:
        dict with status and information about what was dropped/recreated
    """
    import duckdb
    
    # Use direct connection to avoid DDL auto-execution in connect()
    con = duckdb.connect(str(db_path))
    try:
        # Get all existing tables
        existing_tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        
        # Determine which tables to drop
        canonical_tables = ["invoices", "payments", "expenses", "bank_txns"]
        registry_tables = ["schema_registry", "raw_sheet_registry"]
        
        if keep_raw_tables:
            # Only drop canonical and registry tables, keep raw__* tables
            tables_to_drop = [t for t in existing_tables if not t.startswith("raw__")]
        else:
            # Drop ALL tables
            tables_to_drop = existing_tables
        
        # Drop tables
        dropped = []
        for table in tables_to_drop:
            try:
                con.execute(f'DROP TABLE IF EXISTS "{table}"')
                dropped.append(table)
            except Exception as e:
                print(f"Warning: Could not drop table {table}: {e}")
        
        # Only recreate registry tables (schema_registry, raw_sheet_registry)
        # Skip canonical tables if drop_canonical is True
        ddl_to_execute = []
        if not drop_canonical:
            # Recreate canonical tables if requested
            ddl_to_execute.extend(CANON_DDL[:4])  # First 4 are canonical tables
        
        # Always recreate registry tables
        ddl_to_execute.extend(CANON_DDL[4:])  # Last 2 are registry tables
        
        for ddl in ddl_to_execute:
            try:
                con.execute(ddl)
            except Exception as e:
                print(f"Warning: Could not create table: {e}")
        
        # Verify tables were created
        recreated = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        
        # Expected tables based on drop_canonical flag
        if drop_canonical:
            expected_tables = registry_tables
        else:
            expected_tables = canonical_tables + registry_tables
        
        missing = [t for t in expected_tables if t not in recreated]
        
        return {
            "ok": True,
            "dropped_tables": dropped,
            "recreated_tables": recreated,
            "expected_tables": expected_tables,
            "missing_tables": missing,
            "message": f"Dropped {len(dropped)} tables and recreated {len(recreated)} tables. Expected: {expected_tables}. Missing: {missing if missing else 'none'}"
        }
    finally:
        con.close()

if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    
    CACHE_DIR = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
    DB_PATH = CACHE_DIR / "pipeline.duckdb"
    
    # Parse command line args
    keep_raw = "--keep-raw" in sys.argv
    keep_canonical = "--keep-canonical" in sys.argv
    drop_canonical = not keep_canonical
    
    print(f"Resetting database at: {DB_PATH}")
    print(f"Options: keep_raw={keep_raw}, drop_canonical={drop_canonical}")
    result = reset_database(DB_PATH, keep_raw_tables=keep_raw, drop_canonical=drop_canonical)
    print(f"\n{result['message']}")
    print(f"\nDropped tables: {result['dropped_tables']}")
    print(f"Recreated tables: {result['recreated_tables']}")
    if result.get('missing_tables'):
        print(f"WARNING: Missing tables: {result['missing_tables']}")

