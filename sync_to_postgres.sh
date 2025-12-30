#!/usr/bin/env bash
set -e

# Activate venv if present
if [ -z "$VIRTUAL_ENV" ] && [ -d ".venv" ]; then
  source .venv/bin/activate
fi

if [ -z "$JME_PG_URL" ]; then
  echo "JME_PG_URL is required, e.g.:"
  echo "  export JME_PG_URL='postgresql+psycopg2://user:pass@localhost:5432/dbname'"
  exit 1
fi

python sync_to_postgres.py


