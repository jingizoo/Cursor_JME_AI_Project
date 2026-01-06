import json
import os
import re
import threading
import urllib.request
from typing import Any, Dict, List, Optional

_OLLAMA_SEM = threading.Semaphore(int(os.getenv("OLLAMA_MAX_CONCURRENCY", "1")))

def _env_int(name: str) -> int | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return int(v)
    except Exception:
        return None

def _env_float(name: str) -> float | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return float(v)
    except Exception:
        return None

def ollama_chat(*, base_url: str, model: str, messages: List[Dict[str, str]], temperature: float = 0.0, timeout_sec: int = 300, num_predict: int = 512) -> str:
    """
    Calls Ollama /api/chat.
    base_url example: http://localhost:11434 or http://<linux-ip>:11434
    
    Args:
        base_url: Ollama server URL
        model: Model name (e.g., "qwen2.5:3b", "qwen3:8b")
        messages: List of message dicts with "role" and "content"
        temperature: Sampling temperature (default: 0.0 for deterministic)
        timeout_sec: Request timeout in seconds (default: 300 = 5 minutes)
        num_predict: Maximum tokens to generate (default: 512). Lower = faster but may truncate.
                    For SQL generation, 512-1024 is usually enough for small models.
    """
    url = base_url.rstrip("/") + "/api/chat"

    payload_base = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        }
    }

    # Optional perf knobs (all optional; only sent if env var is set)
    # Docs: Ollama model options: num_ctx, num_thread, top_k, top_p, repeat_penalty, mirostat, etc.
    num_ctx = _env_int("OLLAMA_NUM_CTX")
    if num_ctx:
        payload_base["options"]["num_ctx"] = num_ctx

    num_thread = _env_int("OLLAMA_NUM_THREAD")
    if num_thread:
        payload_base["options"]["num_thread"] = num_thread

    top_k = _env_int("OLLAMA_TOP_K")
    if top_k is not None:
        payload_base["options"]["top_k"] = top_k

    top_p = _env_float("OLLAMA_TOP_P")
    if top_p is not None:
        payload_base["options"]["top_p"] = top_p

    repeat_penalty = _env_float("OLLAMA_REPEAT_PENALTY")
    if repeat_penalty is not None:
        payload_base["options"]["repeat_penalty"] = repeat_penalty

    seed = _env_int("OLLAMA_SEED")
    if seed is not None:
        payload_base["options"]["seed"] = seed

    # Optional features (newer Ollama supports these)
    want_json = os.getenv("OLLAMA_FORCE_JSON", "1").lower() in ("1", "true", "yes")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    attempts = []
    p1 = dict(payload_base)
    if want_json:
        p1["format"] = "json"
    if keep_alive:
        p1["keep_alive"] = keep_alive
    attempts.append(p1)

    # fallback attempt (no optional fields)
    attempts.append(payload_base)

    last_err = None

    with _OLLAMA_SEM:
        for payload in attempts:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as r:
                    response_data = r.read().decode("utf-8")
                    out = json.loads(response_data)
                    message_content = out.get("message", {}).get("content", "")
                    if not message_content:
                        if "error" in out:
                            raise Exception(f"Ollama API error: {out['error']}")
                        
                        # Check if response was cut off (done: false means incomplete)
                        done_reason = out.get("done_reason", "")
                        if out.get("done") is False:
                            raise Exception(f"Ollama response incomplete (done_reason: {done_reason or 'unknown'})")
                        
                        # Check done_reason for clues
                        if done_reason:
                            if done_reason == "stop":
                                raise Exception(f"Ollama stopped but returned empty content (done_reason: {done_reason})")
                            elif done_reason == "length":
                                raise Exception(f"Ollama hit token limit (num_predict={num_predict}) before generating content. Set OLLAMA_NUM_PREDICT environment variable to increase (e.g., export OLLAMA_NUM_PREDICT=4096)")
                            else:
                                raise Exception(f"Ollama returned empty content (done_reason: {done_reason})")
                        
                        raise Exception("Ollama returned empty response content (no done_reason provided)")
                    
                    return message_content
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8") if e.fp else ""
                last_err = Exception(f"HTTP error {e.code}: {error_body}")
                continue
            except Exception as e:
                last_err = e
                continue

    raise Exception(str(last_err) if last_err else "Ollama call failed")

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from LLM response text.
    Handles cases where LLM adds explanatory text before/after JSON.
    """
    if not text or not text.strip():
        return None
    
    # Strategy 1: Look for JSON code blocks (```json ... ```)
    json_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_block_match:
        candidate = json_block_match.group(1).strip()
        # Clean up common issues
        candidate = re.sub(r',\s*}', '}', candidate)
        candidate = re.sub(r',\s*]', ']', candidate)
        try:
            return json.loads(candidate)
        except Exception:
            # Try to find complete JSON by counting braces
            brace_count = 0
            end_pos = -1
            for i, char in enumerate(candidate):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                try:
                    return json.loads(candidate[:end_pos])
                except Exception:
                    pass
    
    # Strategy 2: Find the largest valid JSON object by counting braces
    brace_count = 0
    start_idx = -1
    best_start = -1
    best_end = -1
    max_length = 0
    
    for i, char in enumerate(text):
        if char == '{':
            if brace_count == 0:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_idx != -1:
                # Found a complete JSON object
                candidate = text[start_idx:i+1]
                # Try to parse it
                try:
                    parsed = json.loads(candidate)
                    # If it's a dict and has expected keys, prefer it
                    if isinstance(parsed, dict) and len(candidate) > max_length:
                        max_length = len(candidate)
                        best_start = start_idx
                        best_end = i + 1
                except Exception:
                    pass
                start_idx = -1
    
    # If we found a valid JSON object, use it
    if best_start != -1 and best_end != -1:
        candidate = text[best_start:best_end].strip()
        # Clean up common JSON issues
        candidate = re.sub(r',\s*}', '}', candidate)  # Remove trailing commas before }
        candidate = re.sub(r',\s*]', ']', candidate)  # Remove trailing commas before ]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    
    # Strategy 3: Simple find first { and last } (original approach, improved)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end+1].strip()
        
        # First, try to clean up common JSON issues
        candidate = re.sub(r',\s*}', '}', candidate)  # Remove trailing commas
        candidate = re.sub(r',\s*]', ']', candidate)
        
        # Try parsing as-is first
        try:
            return json.loads(candidate)
        except Exception:
            pass
        
        # If that fails, try to remove text after JSON
        # Find the last complete JSON structure by counting braces
        brace_count = 0
        last_valid_end = -1
        for i, char in enumerate(candidate):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_valid_end = i + 1
        
        if last_valid_end > 0:
            candidate = candidate[:last_valid_end]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        
        # Last resort: remove lines that don't look like JSON
        lines = candidate.split('\n')
        fixed_lines = []
        for line in lines:
            line_stripped = line.strip()
            # If line has no JSON-like characters and we already have content, stop
            if fixed_lines and line_stripped and not any(c in line_stripped for c in ['{', '}', '[', ']', ':', ',', '"', "'"]):
                # Check if previous line ended with } or ]
                if fixed_lines[-1].strip().endswith(('}', ']')):
                    break
            fixed_lines.append(line)
        
        fixed_candidate = '\n'.join(fixed_lines)
        try:
            return json.loads(fixed_candidate)
        except Exception:
            pass
    
    # Strategy 4: Try to find JSON after common prefixes
    # Some LLMs say "Here's the JSON:" or similar
    prefixes = [
        r'json\s*:\s*(\{.*?\})',
        r'response\s*:\s*(\{.*?\})',
        r'answer\s*:\s*(\{.*?\})',
    ]
    for pattern in prefixes:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Find matching closing brace
            brace_count = 0
            end_pos = -1
            for i, char in enumerate(candidate):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                candidate = candidate[:end_pos]
            try:
                return json.loads(candidate)
            except Exception:
                continue
    
    return None
