"""
CLI: Sync DuckDB -> Postgres for Superset.

Usage (Linux):
  export JME_PG_URL="postgresql+psycopg2://user:pass@localhost:5432/dbname"
  export JME_PG_SCHEMA="jme"
  python sync_to_postgres.py
"""

from src.postgres_sync import config_from_env, sync_to_postgres


if __name__ == "__main__":
    cfg = config_from_env()
    out = sync_to_postgres(cfg)
    print(out)


