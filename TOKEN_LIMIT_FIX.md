# Token Limit Fix - OLLAMA_NUM_PREDICT

## Problem
Ollama is hitting the token limit (`done_reason: "length"`) even with `num_predict=1024`, causing empty or incomplete responses.

## Solution

### 1. Increased Default Token Limit
- Changed default `num_predict` from 1024 to **2048**
- This gives the model more room to generate complete JSON + SQL responses

### 2. Made It Configurable
- Added `OLLAMA_NUM_PREDICT` environment variable
- You can now adjust the limit without changing code

### 3. Updated All LLM Calls
- `src/planner_agent.py` - SQL planning
- `src/quick_excel.py` - Quick Excel queries
- `src/schema_agent.py` - Schema mapping

## Usage

### Default (2048 tokens)
No configuration needed - uses 2048 tokens by default.

### Increase Limit (if needed)
```bash
# Set environment variable
export OLLAMA_NUM_PREDICT=4096

# Or in .env file
OLLAMA_NUM_PREDICT=4096
```

### Decrease Limit (for speed)
```bash
# Use fewer tokens for faster responses (if model supports it)
export OLLAMA_NUM_PREDICT=1024
```

## Why 2048?

- **512**: Too restrictive, often causes empty responses
- **1024**: Better, but still hitting limits for complex queries
- **2048**: Good balance - enough tokens for most SQL queries without being too slow
- **4096**: Use if you have very complex queries or large schemas

## Performance Impact

| num_predict | Speed | Completeness | Use Case |
|-------------|-------|--------------|----------|
| 512 | Fastest | Low (often empty) | Not recommended |
| 1024 | Fast | Medium (may hit limit) | Simple queries only |
| 2048 | Medium | High (default) | Most queries |
| 4096 | Slower | Very High | Complex queries |

## Troubleshooting

### Still Getting "hit token limit" Error?

1. **Increase limit:**
   ```bash
   export OLLAMA_NUM_PREDICT=4096
   ```

2. **Check prompt size:**
   - Large schemas increase prompt size
   - Consider reducing `max_tables` and `max_cols_per_table` in `_schema_for_llm()`

3. **Use smaller model:**
   - Smaller models generate faster and may need fewer tokens
   - Try `qwen3:4b` instead of `qwen3:8b`

4. **Check Ollama logs:**
   ```bash
   # Check if model is actually generating tokens
   ollama logs
   ```

### Response Still Empty?

1. **Check done_reason:**
   - Error message now shows `done_reason`
   - `"length"` = hit token limit → increase `OLLAMA_NUM_PREDICT`
   - `"stop"` = model stopped naturally → check prompt

2. **Verify model is working:**
   ```bash
   ollama run qwen3:8b "test"
   ```

3. **Check network/connection:**
   - If Ollama is remote, network issues can cause empty responses

## Configuration Example

Add to `.env`:
```bash
# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Token Generation Limit (default: 2048)
OLLAMA_NUM_PREDICT=2048

# For very complex queries, increase:
# OLLAMA_NUM_PREDICT=4096
```

## Files Modified

- `src/planner_agent.py` - Uses configurable num_predict
- `src/quick_excel.py` - Uses configurable num_predict
- `src/schema_agent.py` - Uses configurable num_predict
- `src/llm_client.py` - Better error messages for token limits


