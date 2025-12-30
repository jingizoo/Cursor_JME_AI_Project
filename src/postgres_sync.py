"""
DuckDB -> Postgres sync

Copies canonical tables and ingested raw sheet tables from the DuckDB file
(`.cache/pipeline.duckdb`) into a Postgres schema for Superset.

Why:
- Superset works best when it can query Postgres directly.
- DuckDB file can stay as your pipeline store; Postgres becomes the analytics/BI layer.

Notes:
- Postgres identifier length is 63 bytes. Raw table names can exceed this.
  We create a deterministic Postgres table name for each raw table and store a mapping table.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import duckdb
import pandas as pd
from sqlalchemy import create_engine, text


CANONICAL_TABLES = ["invoices", "payments", "expenses", "bank_txns", "schema_registry", "raw_sheet_registry"]


@dataclass(frozen=True)
class SyncConfig:
    duckdb_path: Path
    pg_url: str
    pg_schema: str = "jme"
    include_raw: bool = True
    raw_limit: int = 2000  # max raw tables to sync
    chunksize: int = 5000


def _short_hash(s: str, n: int = 16) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def _pg_safe_table_name(name: str) -> str:
    """
    Return a deterministic Postgres-safe name <= 63 chars.
    If name is already short, keep it.
    Otherwise shorten using a hash suffix.
    """
    if len(name) <= 60:
        return name
    # Keep prefix for readability, add hash for uniqueness
    prefix = name[:35].rstrip("_")
    return f"{prefix}__{_short_hash(name, 18)}"


def _duckdb_tables(con: duckdb.DuckDBPyConnection) -> List[str]:
    return [r[0] for r in con.execute("SHOW TABLES").fetchall()]


def _raw_tables_from_registry(con: duckdb.DuckDBPyConnection, limit: int) -> List[Tuple[str, str, str]]:
    """
    Returns list of (raw_table, file, sheet) from raw_sheet_registry (most recent first).
    """
    tables = _duckdb_tables(con)
    if "raw_sheet_registry" not in set(tables):
        return []
    rows = con.execute(
        "SELECT raw_table, file, sheet FROM raw_sheet_registry ORDER BY updated_ts DESC LIMIT ?",
        [int(limit)],
    ).fetchall()
    out: List[Tuple[str, str, str]] = []
    for r in rows:
        if not r or not r[0]:
            continue
        out.append((str(r[0]), str(r[1] or ""), str(r[2] or "")))
    return out


def ensure_pg_schema(engine, schema: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def write_df_to_pg(engine, *, df: pd.DataFrame, schema: str, table: str, if_exists: str = "replace", chunksize: int = 5000) -> None:
    df.to_sql(
        name=table,
        con=engine,
        schema=schema,
        if_exists=if_exists,
        index=False,
        chunksize=int(chunksize) if chunksize else None,
        method="multi",
    )


def sync_to_postgres(cfg: SyncConfig) -> Dict[str, object]:
    """
    Full refresh sync (replace) into Postgres schema.
    Returns summary dict.
    """
    if not cfg.pg_url:
        raise ValueError("pg_url is required (e.g. postgresql+psycopg2://user:pass@host:5432/dbname)")

    duck_con = duckdb.connect(str(cfg.duckdb_path))
    engine = create_engine(cfg.pg_url, future=True)

    ensure_pg_schema(engine, cfg.pg_schema)

    duck_tables = set(_duckdb_tables(duck_con))

    synced: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    # 1) Canonical tables
    for t in CANONICAL_TABLES:
        if t not in duck_tables:
            skipped.append({"table": t, "reason": "not found in duckdb"})
            continue
        df = duck_con.execute(f'SELECT * FROM "{t}"').df()
        write_df_to_pg(engine, df=df, schema=cfg.pg_schema, table=t, if_exists="replace", chunksize=cfg.chunksize)
        synced.append({"duckdb_table": t, "pg_table": f"{cfg.pg_schema}.{t}", "rows": int(df.shape[0])})

    # 2) Raw tables + mapping table
    raw_map_rows: List[Dict[str, str]] = []
    if cfg.include_raw:
        raw = _raw_tables_from_registry(duck_con, cfg.raw_limit)
        for raw_table, file, sheet in raw:
            if raw_table not in duck_tables:
                skipped.append({"table": raw_table, "reason": "missing raw table in duckdb"})
                continue
            pg_table = _pg_safe_table_name(raw_table)
            df = duck_con.execute(f'SELECT * FROM "{raw_table}"').df()
            write_df_to_pg(engine, df=df, schema=cfg.pg_schema, table=pg_table, if_exists="replace", chunksize=cfg.chunksize)
            synced.append({"duckdb_table": raw_table, "pg_table": f"{cfg.pg_schema}.{pg_table}", "rows": int(df.shape[0])})
            raw_map_rows.append({"duckdb_table": raw_table, "pg_table": pg_table, "file": file, "sheet": sheet})

    # Mapping table (helps users find the right raw table in Superset)
    map_df = pd.DataFrame(raw_map_rows)
    write_df_to_pg(engine, df=map_df, schema=cfg.pg_schema, table="raw_table_map", if_exists="replace", chunksize=cfg.chunksize)

    duck_con.close()
    engine.dispose()

    return {
        "ok": True,
        "duckdb_path": str(cfg.duckdb_path),
        "pg_schema": cfg.pg_schema,
        "synced_count": len(synced),
        "skipped_count": len(skipped),
        "synced": synced[:50],
        "skipped": skipped[:50],
    }


def config_from_env() -> SyncConfig:
    """
    Env vars:
      - JME_CACHE_DIR (optional, default ./.cache)
      - JME_PG_URL (required)
      - JME_PG_SCHEMA (optional, default jme)
      - JME_PG_INCLUDE_RAW (optional, default true)
      - JME_PG_RAW_LIMIT (optional, default 2000)
      - JME_PG_CHUNKSIZE (optional, default 5000)
    """
    cache_dir = Path(os.environ.get("JME_CACHE_DIR", "./.cache"))
    duckdb_path = cache_dir / "pipeline.duckdb"
    pg_url = os.environ.get("JME_PG_URL", "")
    schema = os.environ.get("JME_PG_SCHEMA", "jme")
    include_raw = os.environ.get("JME_PG_INCLUDE_RAW", "true").strip().lower() in {"1", "true", "yes", "y"}
    raw_limit = int(os.environ.get("JME_PG_RAW_LIMIT", "2000"))
    chunksize = int(os.environ.get("JME_PG_CHUNKSIZE", "5000"))
    return SyncConfig(
        duckdb_path=duckdb_path,
        pg_url=pg_url,
        pg_schema=schema,
        include_raw=include_raw,
        raw_limit=raw_limit,
        chunksize=chunksize,
    )


