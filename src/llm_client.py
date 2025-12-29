import json
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
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end+1].strip()
    try:
        return json.loads(candidate)
    except Exception:
        return None
