# Cursor Project: JME AI Finance Pipeline (Dynamic Excel + Ollama)

You said: `ollama serve` is running on a Linux machine and you have model `qwen3:8b`.

## First step (do this first)
From the machine where you will run this API (your laptop or the Linux box), verify Ollama is reachable:

```bash
export OLLAMA_URL="http://<LINUX_IP>:11434"
curl -s $OLLAMA_URL/api/tags | head
```

If you can’t reach it, either:
- run this API on the same Linux machine, OR
- open firewall for port 11434 on Linux, OR
- SSH tunnel: `ssh -L 11434:localhost:11434 user@linux-host`

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure
```bash
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="http://<LINUX_IP>:11434"
export OLLAMA_MODEL="qwen3:8b"
```

## Run
```bash
python -m uvicorn src.api:app --host 127.0.0.1 --port 8010
```

Swagger:
- http://127.0.0.1:8010/docs

## Flow
1) Put Excel files into `data/`
2) POST `/ingest`  (LLM maps schemas + loads canonical tables)
3) GET  `/catalog` (review mappings and confidence)
4) POST `/ask`     (NL -> SQL plan via LLM -> executed)
5) POST `/report-pack` (download Excel pack)

## New: Raw sheet tables (for non-canonical sheets like timesheets / hours)
During `/ingest`, **every sheet** is also materialized into a queryable DuckDB table named like:
- `raw__<file>__<sheet>__<hash>`

This means even if a sheet is mapped as `unknown` (or doesn't fit invoices/payments/expenses/bank), you can still query it via `/ask` (and Superset endpoints) by using the raw table + its real column names.

To discover these tables/columns:
- **Tables**: `GET /api/v1/tables`
- **Columns**: `GET /api/v1/table/<table_name>/columns`

## Better “no answer” hints
If `/ask` (or `/ask-chart`) can’t execute SQL or returns 0 rows, the response now includes a **`hint`** field explaining likely causes (missing table/column, filters too strict) and where to inspect tables/columns.

