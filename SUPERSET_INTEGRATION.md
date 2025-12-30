# Superset Integration (Postgres sync on same Linux server)

You said: Superset is running on a Linux machine (not Docker), using Postgres, and it’s on the same server as this pipeline.

Superset renders charts from datasets it can query. The clean pattern here is:

- This pipeline writes to **DuckDB** (`./.cache/pipeline.duckdb`)
- A sync job copies tables into **Postgres schema** (e.g. `jme`)
- Superset connects to Postgres and builds charts on those tables

---

## What gets synced

### Canonical tables (always)
- `invoices`
- `payments`
- `expenses`
- `bank_txns`
- `schema_registry`
- `raw_sheet_registry`

### Raw ingested sheet tables (optional, default = on)
Every ingested sheet is materialized into a DuckDB table named like:
- `raw__<file>__<sheet>__<hash>`

When syncing to Postgres we may **rename raw tables** because Postgres identifiers max out at 63 chars.

To help you find them, we also write:
- `raw_table_map` with columns: `duckdb_table`, `pg_table`, `file`, `sheet`

---

## One-time setup (pipeline environment)

Install dependencies:

```bash
pip install -r requirements.txt
```

This includes:
- `SQLAlchemy`
- `psycopg2-binary`

---

## Configure Postgres connection

Set env vars on the server (same host):

```bash
export JME_PG_URL="postgresql+psycopg2://USER:PASSWORD@localhost:5432/DBNAME"
export JME_PG_SCHEMA="jme"
```

Optional:
- `JME_PG_INCLUDE_RAW=true|false` (default: true)
- `JME_PG_RAW_LIMIT=2000`
- `JME_PG_CHUNKSIZE=5000`

---

## Run the sync

### Linux/macOS

```bash
chmod +x sync_to_postgres.sh
./sync_to_postgres.sh
```

### Windows (PowerShell)

```powershell
.\sync_to_postgres.ps1
```

### Manual

```bash
python sync_to_postgres.py
```

This does a **full refresh** (replace) into Postgres schema `jme`.

---

## Connect Superset to the synced Postgres schema

In Superset:
- **Settings → Database Connections → + Database**
- Select **PostgreSQL**
- Point it at the same Postgres instance (or a separate one, your choice)

Then create datasets from:
- `jme.invoices`, `jme.payments`, `jme.expenses`, `jme.bank_txns`
- `jme.raw_table_map` (to discover raw sheet table names)
- raw sheet tables listed in `jme.raw_table_map.pg_table`

---

## Automation (recommended)

Because ingestion updates DuckDB, run the sync on a schedule:
- systemd timer / cron every 5–15 minutes
- or trigger it at the end of your `/ingest` workflow

---

## Files added to support this

- `src/postgres_sync.py` (sync logic)
- `sync_to_postgres.py` (CLI entrypoint)
- `sync_to_postgres.sh` / `sync_to_postgres.ps1` (helpers)
