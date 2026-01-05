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

def reset_database(db_path: Path, keep_raw_tables: bool = False) -> dict:
    """
    Drop tables and recreate only the necessary registry tables.
    All data tables are created at runtime from ingested files.
    
    Args:
        db_path: Path to the DuckDB database file
        keep_raw_tables: If True, keep raw__* tables (only drop registry tables)
        
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
        registry_tables = ["schema_registry", "raw_sheet_registry"]
        
        if keep_raw_tables:
            # Only drop registry tables, keep raw__* tables
            tables_to_drop = [t for t in existing_tables if t in registry_tables]
        else:
            # Drop ALL tables (including all raw__* tables)
            tables_to_drop = existing_tables
        
        # Drop tables
        dropped = []
        for table in tables_to_drop:
            try:
                con.execute(f'DROP TABLE IF EXISTS "{table}"')
                dropped.append(table)
            except Exception as e:
                print(f"Warning: Could not drop table {table}: {e}")
        
        # Recreate only registry tables (schema_registry, raw_sheet_registry)
        # All data tables are created at runtime from ingested files
        for ddl in CANON_DDL:
            try:
                con.execute(ddl)
            except Exception as e:
                print(f"Warning: Could not create table: {e}")
        
        # Verify tables were created
        recreated = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        
        # Expected tables: only registry tables
        expected_tables = registry_tables
        
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
    
    print(f"Resetting database at: {DB_PATH}")
    print(f"Options: keep_raw={keep_raw}")
    result = reset_database(DB_PATH, keep_raw_tables=keep_raw)
    print(f"\n{result['message']}")
    print(f"\nDropped tables: {result['dropped_tables']}")
    print(f"Recreated tables: {result['recreated_tables']}")
    if result.get('missing_tables'):
        print(f"WARNING: Missing tables: {result['missing_tables']}")

