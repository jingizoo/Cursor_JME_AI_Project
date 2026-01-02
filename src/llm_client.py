import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

def ollama_chat(*, base_url: str, model: str, messages: List[Dict[str, str]], temperature: float = 0.0, timeout_sec: int = 600) -> str:
    """
    Calls Ollama /api/chat.
    base_url example: http://localhost:11434 or http://<linux-ip>:11434
    """
    url = base_url.rstrip("/") + "/api/chat"
    payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_sec) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out["message"]["content"]

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
        try:
            return json.loads(candidate)
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
        # Clean up common issues
        candidate = re.sub(r',\s*}', '}', candidate)
        candidate = re.sub(r',\s*]', ']', candidate)
        # Remove any text that looks like it's after the JSON (common LLM issue)
        # Stop at lines that don't look like JSON
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
            # Try the original candidate
            try:
                return json.loads(candidate)
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
