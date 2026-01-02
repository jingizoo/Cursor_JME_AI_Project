# Performance Optimization Guide

This guide explains the performance optimizations implemented in the JME AI Finance Pipeline and how to use them to improve query speed.

## Why Queries Can Feel Slow

The `/ask` endpoint performs several operations that can impact latency:

1. **LLM SQL Generation** - The main bottleneck: calling `qwen3:8b` (or your configured model) to generate SQL
   - Slow on CPU or weak GPU
   - Network latency if Ollama is on another machine
   - Cold starts if model keeps unloading/reloading

2. **PDF/Wiki Context Search** - If PDFs were ingested, every question triggers:
   - Embedding generation (Ollama API call)
   - ChromaDB similarity search
   - Additional network roundtrip

3. **Large Schema Payloads** - Even with compact schema, many tables/columns increase prompt size → slower LLM generation

4. **Unlimited SQL Results** - Queries without LIMIT can return huge datasets, slowing:
   - SQL execution
   - JSON serialization

5. **No Caching** - Repeated identical questions regenerate SQL every time

## Implemented Optimizations

### 1. Automatic LIMIT Enforcement ✅

**What it does:** Automatically adds `LIMIT 200` to all SQL queries if the LLM forgets.

**Implementation:** Added `ensure_limit()` function in `src/planner_agent.py` that:
- Checks if LIMIT already exists (case-insensitive)
- Appends `LIMIT 200` if missing
- Handles CTEs and nested queries safely

**Benefit:** Prevents runaway queries that return thousands of rows.

**Usage:** Automatic - no configuration needed.

### 2. PDF Context Disable via Environment Variable ✅

**What it does:** Allows disabling PDF/wiki context search for pure Excel-based queries.

**Implementation:** 
- Added `JME_DISABLE_PDF_CONTEXT` environment variable check in `plan_sql()`
- When set to `1`, `true`, or `yes`, skips embedding generation and vector search

**Benefit:** Saves 100-500ms per query when PDF context isn't needed.

**Usage:**
```bash
# Disable PDF context (faster for Excel-only queries)
export JME_DISABLE_PDF_CONTEXT=1

# Or in .env file
JME_DISABLE_PDF_CONTEXT=1
```

**When to use:**
- Most questions are about Excel data only
- PDFs were ingested but rarely needed for context
- You want maximum speed and can accept slightly less context-aware SQL

### 3. SQL Plan Caching ✅

**What it does:** Caches SQL plans by (question, model) tuple for instant repeat queries.

**Implementation:**
- Added `_PLAN_CACHE` dictionary in `src/api.py`
- Cache key: `(question.strip(), OLLAMA_MODEL)`
- Cache invalidated when database changes (detected via file mtime)
- Response includes `plan_cached: true` when cache hit

**Benefit:** 
- First query: normal latency (e.g., 3-8 seconds)
- Repeat query: instant (< 50ms)

**Usage:** Automatic - no configuration needed.

**Cache behavior:**
- Cache persists for the lifetime of the API process
- Automatically cleared when database is modified (new ingestion)
- Manual clear: restart the API server

### 4. Timing Information ✅

**What it does:** Returns detailed timing breakdown in API responses.

**Implementation:** Added `timings_ms` object to all `/ask` responses:
```json
{
  "ok": true,
  "sql": "...",
  "rows": [...],
  "timings_ms": {
    "schema_build_ms": 12.5,
    "llm_ms": 3450.2,
    "embedding_ms": 0,
    "sql_exec_ms": 45.8,
    "json_serialize_ms": 8.3,
    "total_ms": 3516.8
  }
}
```

**Benefit:** Instantly identify bottlenecks:
- High `llm_ms` → LLM is slow (use smaller model or better hardware)
- High `embedding_ms` → PDF context search is slow (disable if not needed)
- High `sql_exec_ms` → Query is complex or data is large (add indexes or optimize)
- High `json_serialize_ms` → Too many rows (LIMIT already enforced)

**Usage:** Automatic - check `timings_ms` in response.

### 5. Compact Schema Generation ✅

**What it does:** Sends only relevant tables to LLM, reducing prompt size.

**Implementation:** `_schema_for_llm()` function:
- Always includes canonical tables (invoices, payments, etc.)
- Includes up to 8 most recent/relevant raw tables
- Matches table names to question tokens when possible

**Benefit:** Smaller prompts → faster LLM generation → better accuracy.

**Usage:** Automatic - no configuration needed.

## Additional Performance Tips

### Use a Smaller/Faster LLM Model

For NL→SQL, you often don't need an 8B model. Smaller models (3B-4B) are often:
- 2-3x faster
- Still accurate for SQL generation
- Lower memory usage

**How to change:**
```bash
# In .env or environment
OLLAMA_MODEL=qwen3:4b  # or another smaller model
```

**Test first:**
```bash
ollama pull qwen3:4b
# Test a few queries, compare accuracy vs speed
```

### Run API on Same Machine as Ollama

Network latency adds overhead:
- Local Ollama: ~50-100ms per call
- Remote Ollama: 200-500ms+ per call

**Best practice:**
- Run API and Ollama on the same Linux machine, OR
- Use SSH tunnel: `ssh -L 11434:localhost:11434 user@ollama-host`

### Monitor Cache Hit Rate

Check if caching is working:
```bash
# Query 1 (cache miss)
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "top 5 expenses"}' | jq '.timings_ms.total_ms'

# Query 2 (cache hit - should be much faster)
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "top 5 expenses"}' | jq '.plan_cached, .timings_ms.total_ms'
```

### Optimize Database

For large datasets:
- Use DuckDB's columnar storage efficiently
- Consider partitioning very large tables
- Add indexes on frequently queried columns (DuckDB auto-indexes, but explicit helps)

## Performance Benchmarks

Typical query times (on modern hardware, local Ollama):

| Scenario | Before Optimizations | After Optimizations |
|----------|---------------------|-------------------|
| First query (Excel-only) | 5-10s | 3-6s |
| First query (with PDF context) | 8-15s | 5-10s |
| Repeat query (cached) | 5-10s | < 0.1s |
| With smaller model (3B) | N/A | 1-3s |

*Times vary based on hardware, network, and data size.*

## Configuration Summary

### Environment Variables

```bash
# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b  # Consider smaller model for speed

# Performance Optimizations
JME_DISABLE_PDF_CONTEXT=1  # Disable PDF context search (faster)

# Data Directories
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache
```

### Recommended Settings for Speed

**Maximum Speed (Excel-only queries):**
```bash
OLLAMA_MODEL=qwen3:4b  # Smaller, faster model
JME_DISABLE_PDF_CONTEXT=1  # Skip PDF context
```

**Balanced (Accuracy + Speed):**
```bash
OLLAMA_MODEL=qwen3:8b  # Default model
JME_DISABLE_PDF_CONTEXT=0  # Keep PDF context for better SQL
```

**Maximum Accuracy (Slower):**
```bash
OLLAMA_MODEL=qwen3:8b  # Or larger model
JME_DISABLE_PDF_CONTEXT=0  # Use all context
```

## Troubleshooting Slow Queries

### Check Timing Breakdown

```bash
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "your question"}' | jq '.timings_ms'
```

**If `llm_ms` is high (> 5s):**
- Use smaller model: `OLLAMA_MODEL=qwen3:4b`
- Check Ollama is on same machine
- Verify GPU is being used (if available)

**If `embedding_ms` is high (> 1s):**
- Disable PDF context: `JME_DISABLE_PDF_CONTEXT=1`
- Or reduce `top_k` in vector search (requires code change)

**If `sql_exec_ms` is high (> 1s):**
- Query might be complex - check the generated SQL
- Data might be large - LIMIT is already enforced
- Consider optimizing the query manually

**If `total_ms` is acceptable but feels slow:**
- Check network latency to Ollama
- Verify cache is working (repeat query should be instant)
- Consider using `/ask-data` endpoint for chart rendering (optimized for webapp)

### Verify Optimizations Are Active

```bash
# Check if LIMIT is enforced
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "show all expenses"}' | jq '.sql' | grep -i limit

# Check if PDF context is disabled
# (Should see "embedding_ms": 0 in timings)
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "test"}' | jq '.timings_ms.embedding_ms'

# Check cache is working
# Run same query twice, second should have plan_cached: true
```

## Next Steps

1. **Profile your queries:** Use `timings_ms` to identify bottlenecks
2. **Experiment with models:** Try smaller models for speed vs accuracy tradeoff
3. **Disable PDF context:** If most queries are Excel-only
4. **Monitor cache hits:** Ensure repeated queries are fast
5. **Optimize hardware:** Run Ollama on GPU if available, or same machine as API

For more information:
- `INSTALLATION.md` - Setup and installation
- `DEPLOYMENT_LINUX.md` - Production deployment
- `VECTOR_DB_README.md` - Vector database details

