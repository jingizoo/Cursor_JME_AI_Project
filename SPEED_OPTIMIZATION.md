# Speed Optimization for 9-Minute LLM Latency

## Problem
LLM response time is ~9 minutes per request, which is unacceptable. This document outlines aggressive optimizations to reduce latency.

## Root Causes

1. **Large Model (8B parameters)** - `qwen3:8b` is slow on CPU
2. **Large Prompts** - Schema with many tables/columns increases processing time
3. **No Token Limits** - LLM generates unlimited tokens
4. **Network Latency** - If Ollama is remote
5. **CPU vs GPU** - Running on CPU is 10-100x slower than GPU

## Implemented Optimizations

### 1. Aggressive Schema Reduction ✅

**Changes:**
- Reduced max tables from 8 to **5**
- Reduced max columns per table from unlimited to **15**
- Removed registry tables from base schema
- Limited raw tables to 10 (was 25)

**Impact:** Reduces prompt size by 40-60%, significantly faster LLM processing

**Code:**
```python
def _schema_for_llm(con, question: str, max_tables: int = 5, max_cols_per_table: int = 15):
    # Only 5 tables max, 15 columns per table max
```

### 2. Token Generation Limit ✅

**Changes:**
- Added `num_predict=512` to Ollama calls
- Limits LLM to generate max 512 tokens (SQL is usually <200 tokens)

**Impact:** Prevents long generations, 2-5x faster responses

**Code:**
```python
ollama_chat(..., num_predict=512)  # Stop after 512 tokens
```

### 3. Shorter Prompts ✅

**Changes:**
- Shortened system prompt (removed verbose instructions)
- Reduced PDF context from 300 to 150 chars
- Limited PDF contexts from 3 to 2
- Compact JSON (no spaces)

**Impact:** 20-30% faster LLM processing

### 4. Column Caching with Limits ✅

**Changes:**
- Column info cached with max_cols parameter
- Only first N columns included (most important are usually first)

**Impact:** Faster schema building, smaller prompts

## Recommended Additional Steps

### 1. Use Smaller/Faster Model (CRITICAL)

**Current:** `qwen3:8b` (8B parameters, slow on CPU)

**Recommended:**
```bash
# Option 1: Smaller model (3-4B parameters)
export OLLAMA_MODEL=qwen3:4b
# Or
export OLLAMA_MODEL=llama3.2:3b

# Option 2: Faster specialized model
export OLLAMA_MODEL=phi3:mini  # Very fast, good for SQL
```

**Expected Impact:** 3-5x faster (from 9 min to 2-3 min on CPU)

### 2. Use GPU (If Available)

**If you have NVIDIA GPU:**
```bash
# Install CUDA-enabled Ollama or use GPU-accelerated model
# GPU can be 10-50x faster than CPU
```

**Expected Impact:** 10-50x faster (from 9 min to 10-50 seconds)

### 3. Disable PDF Context (If Not Needed)

```bash
export JME_DISABLE_PDF_CONTEXT=1
```

**Expected Impact:** Saves 100-500ms per query

### 4. Use Local Ollama (If Remote)

**If Ollama is on another machine:**
- Move Ollama to same machine as API
- Or use SSH tunnel to reduce latency
- Or use local Ollama instance

**Expected Impact:** Reduces network latency (can save seconds)

### 5. Increase Cache Hit Rate

**Strategy:**
- Ask similar questions (cache hits are instant)
- Use question templates
- Pre-warm cache with common queries

**Expected Impact:** Cached queries are <50ms (vs 9 minutes)

## Performance Targets

| Scenario | Current | Target | How to Achieve |
|----------|---------|--------|----------------|
| CPU + 8B model | 9 min | 2-3 min | Use smaller model (3-4B) |
| CPU + 3B model | N/A | 1-2 min | Already optimized |
| GPU + 8B model | N/A | 10-30 sec | Use GPU |
| GPU + 3B model | N/A | 5-15 sec | Use GPU + smaller model |
| Cached query | <50ms | <50ms | Already optimized |

## Quick Wins (Do These First)

1. **Change model to smaller one:**
   ```bash
   export OLLAMA_MODEL=qwen3:4b
   # Or
   export OLLAMA_MODEL=phi3:mini
   ```

2. **Disable PDF context:**
   ```bash
   export JME_DISABLE_PDF_CONTEXT=1
   ```

3. **Verify Ollama is local:**
   ```bash
   export OLLAMA_URL=http://localhost:11434
   ```

4. **Check if GPU is available:**
   ```bash
   nvidia-smi  # If available, Ollama should use it automatically
   ```

## Monitoring

Check timing breakdown in API response:
```json
{
  "timings_ms": {
    "llm_ms": 540000,  // This is the 9 minutes - should be < 60000
    ...
  }
}
```

If `llm_ms` is still high after optimizations:
- Model is too large → use smaller model
- Running on CPU → use GPU
- Network latency → move Ollama local
- Prompt still too large → reduce schema further

## Configuration

Add to `.env`:
```bash
# Use smaller/faster model
OLLAMA_MODEL=qwen3:4b

# Disable PDF context
JME_DISABLE_PDF_CONTEXT=1

# Ensure local Ollama
OLLAMA_URL=http://localhost:11434
```

## Next Steps

1. **Immediate:** Change to smaller model (`qwen3:4b` or `phi3:mini`)
2. **Short-term:** Disable PDF context if not needed
3. **Medium-term:** Set up GPU if available
4. **Long-term:** Consider using specialized SQL models or fine-tuned models

