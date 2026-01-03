# Model Configuration and Troubleshooting

## How to Check Which Model You're Using

### 1. Check Health Endpoint
```bash
curl http://localhost:8010/health
```

Response includes:
- `ollama_model`: The model name being used
- `ollama_url`: Ollama server URL
- `ollama_timeout_sec`: Request timeout
- `num_predict`: Token generation limit

### 2. Check API Responses
All `/ask` responses now include a `model` field showing which model was used.

### 3. Check Environment Variable
```bash
# Windows PowerShell
echo $env:OLLAMA_MODEL

# Linux/macOS
echo $OLLAMA_MODEL
```

### 4. Check Ollama Models
```bash
ollama list
```

## Common Model Names

- `qwen2.5:3b` - Qwen 2.5 3B model (small, fast)
- `qwen3:8b` - Qwen 3 8B model (default, larger)
- `qwen2.5:7b` - Qwen 2.5 7B model
- `llama3.2:3b` - Llama 3.2 3B model

## Configuration

### Set Model Name
```bash
# Windows PowerShell
$env:OLLAMA_MODEL = "qwen2.5:3b"

# Linux/macOS
export OLLAMA_MODEL="qwen2.5:3b"
```

### Set Timeout (for slow models or large prompts)
```bash
# Windows PowerShell
$env:OLLAMA_TIMEOUT = "600"  # 10 minutes

# Linux/macOS
export OLLAMA_TIMEOUT="600"  # 10 minutes
```

### Set Token Limit (for smaller models)
```bash
# Windows PowerShell
$env:OLLAMA_NUM_PREDICT = "1024"  # Lower for 3B models

# Linux/macOS
export OLLAMA_NUM_PREDICT="1024"  # Lower for 3B models
```

## Troubleshooting Timeouts

### Symptoms
- Requests hang and eventually timeout
- Error: "Request to Ollama timed out after 300s"
- Long wait times (minutes) before response

### Solutions

#### 1. Increase Timeout
```bash
export OLLAMA_TIMEOUT="600"  # 10 minutes instead of 5
```

#### 2. Use a Faster Model
Smaller models (3B) are faster but may be less accurate:
```bash
export OLLAMA_MODEL="qwen2.5:3b"
```

#### 3. Reduce Token Limit
For smaller models, use lower `num_predict`:
```bash
export OLLAMA_NUM_PREDICT="512"  # Lower limit = faster
```

#### 4. Disable PDF Context (Performance)
```bash
export JME_DISABLE_PDF_CONTEXT="1"
```

#### 5. Limit Schema Size
```bash
export JME_MAX_TABLES="10"  # Limit tables in schema
export JME_MAX_COLS="30"    # Limit columns per table
```

#### 6. Check Ollama Server
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Check model availability
ollama list

# Pull model if missing
ollama pull qwen2.5:3b
```

## Model-Specific Optimizations

### For 3B Models (qwen2.5:3b, llama3.2:3b)
```bash
export OLLAMA_MODEL="qwen2.5:3b"
export OLLAMA_NUM_PREDICT="512"   # Lower limit
export OLLAMA_TIMEOUT="300"      # 5 minutes
export JME_DISABLE_PDF_CONTEXT="1"  # Disable for speed
export JME_MAX_TABLES="5"        # Limit schema
export JME_MAX_COLS="20"         # Limit columns
```

### For 8B+ Models (qwen3:8b, qwen2.5:7b)
```bash
export OLLAMA_MODEL="qwen3:8b"
export OLLAMA_NUM_PREDICT="2048"  # Higher limit
export OLLAMA_TIMEOUT="600"       # 10 minutes
export JME_MAX_TABLES="10"        # More tables OK
export JME_MAX_COLS="50"          # More columns OK
```

## Performance Tips

1. **Use smaller models for speed**: 3B models are 2-3x faster than 8B
2. **Cache SQL plans**: Repeated questions use cached plans (instant)
3. **Limit schema size**: Fewer tables/columns = faster LLM processing
4. **Disable PDF context**: Skip vector search if not needed
5. **Monitor logs**: Check console for `[ollama_chat]` and `[plan_sql]` messages

## Example: Full Configuration for qwen2.5:3b

```bash
# Set model
export OLLAMA_MODEL="qwen2.5:3b"

# Optimize for speed
export OLLAMA_NUM_PREDICT="512"
export OLLAMA_TIMEOUT="300"
export JME_DISABLE_PDF_CONTEXT="1"
export JME_MAX_TABLES="5"
export JME_MAX_COLS="20"

# Start API
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

## Debugging

### Check Model in Logs
Look for these log messages:
```
[plan_sql] Using model: qwen2.5:3b, num_predict: 512, timeout: 300s
[ollama_chat] Model: qwen2.5:3b, Time: 45.23s, Tokens: 234 chars
```

### Check API Response
```json
{
  "ok": true,
  "model": "qwen2.5:3b",
  "sql": "SELECT ...",
  "timings_ms": {
    "llm_ms": 45230,
    "sql_exec_ms": 12.5
  }
}
```

## Common Issues

### Issue: "Model not found"
**Solution**: Pull the model first
```bash
ollama pull qwen2.5:3b
```

### Issue: "Connection error"
**Solution**: Check Ollama is running
```bash
# Check if running
curl http://localhost:11434/api/tags

# Start Ollama if not running
ollama serve
```

### Issue: "Token limit hit"
**Solution**: Increase `OLLAMA_NUM_PREDICT`
```bash
export OLLAMA_NUM_PREDICT="2048"
```

### Issue: "Timeout after 300s"
**Solution**: Increase timeout or use faster model
```bash
export OLLAMA_TIMEOUT="600"
# OR
export OLLAMA_MODEL="qwen2.5:3b"  # Faster model
```

