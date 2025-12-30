# src/wiki_extractor.py
"""
Extract content from wiki pages (Wikipedia, MediaWiki, etc.)
and prepare it for vector DB storage.
"""
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

def extract_wikipedia_content(page_title: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract content from a Wikipedia page.
    
    Args:
        page_title: Wikipedia page title (e.g., "Python_(programming_language)")
        api_key: Not needed for Wikipedia, but kept for API consistency
    
    Returns:
        Dict with 'ok', 'title', 'content', 'url', 'error'
    """
    if not REQUESTS_AVAILABLE:
        return {"ok": False, "error": "requests library not available"}
    
    try:
        # Wikipedia API endpoint
        api_url = "https://en.wikipedia.org/api/rest_v1/page/summary/"
        page_encoded = page_title.replace(" ", "_")
        
        resp = requests.get(f"{api_url}{page_encoded}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Get full content (not just summary)
        content_url = f"https://en.wikipedia.org/api/rest_v1/page/html/{page_encoded}"
        content_resp = requests.get(content_url, timeout=10)
        
        if content_resp.status_code == 200:
            # Extract text from HTML (simple approach)
            html_content = content_resp.text
            # Remove HTML tags and decode entities
            text_content = re.sub(r'<[^>]+>', ' ', html_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()
            
            # Also get plain text extract
            extract = data.get("extract", "")
            
            # Combine extract + full content
            full_content = f"{extract}\n\n{text_content[:5000]}"  # Limit to avoid huge chunks
            
            return {
                "ok": True,
                "title": data.get("title", page_title),
                "content": full_content,
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "extract": extract
            }
        else:
            # Fallback to extract only
            return {
                "ok": True,
                "title": data.get("title", page_title),
                "content": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "extract": data.get("extract", "")
            }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"Failed to fetch Wikipedia page: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Error processing Wikipedia page: {e}"}

def extract_mediawiki_content(wiki_url: str, page_title: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract content from a MediaWiki-based wiki.
    
    Args:
        wiki_url: Base URL of the wiki (e.g., "https://wiki.example.com")
        page_title: Page title to extract
        api_key: Optional API key if required
    
    Returns:
        Dict with 'ok', 'title', 'content', 'url', 'error'
    """
    if not REQUESTS_AVAILABLE:
        return {"ok": False, "error": "requests library not available"}
    
    try:
        # Normalize wiki URL
        wiki_base = wiki_url.rstrip('/')
        if not wiki_base.startswith('http'):
            wiki_base = f"https://{wiki_base}"
        
        # MediaWiki API endpoint
        api_url = f"{wiki_base}/api.php"
        
        # Get page content
        params = {
            "action": "query",
            "format": "json",
            "titles": page_title,
            "prop": "extracts|info",
            "exintro": "false",
            "explaintext": "true",
            "inprop": "url"
        }
        
        if api_key:
            params["apikey"] = api_key
        
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        resp = requests.get(api_url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return {"ok": False, "error": f"Page '{page_title}' not found"}
        
        page_id = list(pages.keys())[0]
        page_data = pages[page_id]
        
        if page_id == "-1":
            return {"ok": False, "error": f"Page '{page_title}' not found"}
        
        content = page_data.get("extract", "")
        title = page_data.get("title", page_title)
        canonical_url = page_data.get("canonicalurl", f"{wiki_base}/wiki/{page_title.replace(' ', '_')}")
        
        return {
            "ok": True,
            "title": title,
            "content": content,
            "url": canonical_url,
            "extract": content[:500]  # First 500 chars as summary
        }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"Failed to fetch MediaWiki page: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Error processing MediaWiki page: {e}"}

def extract_wiki_from_url(url: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract content from a wiki page given a URL.
    Auto-detects wiki type (Wikipedia, MediaWiki, etc.)
    
    Args:
        url: Full URL to the wiki page
        api_key: Optional API key if required
    
    Returns:
        Dict with 'ok', 'title', 'content', 'url', 'error'
    """
    if not REQUESTS_AVAILABLE:
        return {"ok": False, "error": "requests library not available"}
    
    try:
        # Parse URL
        url_lower = url.lower()
        
        # Wikipedia detection
        if "wikipedia.org" in url_lower or "wikipedia.org/wiki/" in url_lower:
            # Extract page title from URL
            # Format: https://en.wikipedia.org/wiki/Page_Title
            match = re.search(r'/wiki/([^?#]+)', url)
            if match:
                page_title = match.group(1).replace("_", " ")
                return extract_wikipedia_content(page_title, api_key)
            else:
                return {"ok": False, "error": "Could not extract page title from Wikipedia URL"}
        
        # MediaWiki detection (generic)
        elif "/wiki/" in url_lower or "/index.php" in url_lower:
            # Extract base URL and page title
            # Format: https://wiki.example.com/wiki/Page_Title
            match = re.search(r'(https?://[^/]+)/.*?/([^?#]+)', url)
            if match:
                wiki_base = match.group(1)
                page_title = match.group(2).replace("_", " ")
                return extract_mediawiki_content(wiki_base, page_title, api_key)
            else:
                return {"ok": False, "error": "Could not parse MediaWiki URL"}
        
        # Generic wiki page - try to extract as HTML
        else:
            try:
                resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                
                # Extract title
                title_match = re.search(r'<title[^>]*>([^<]+)</title>', resp.text, re.IGNORECASE)
                title = title_match.group(1) if title_match else "Wiki Page"
                
                # Extract text content (simple approach)
                text_content = re.sub(r'<[^>]+>', ' ', resp.text)
                text_content = re.sub(r'\s+', ' ', text_content).strip()
                
                return {
                    "ok": True,
                    "title": title,
                    "content": text_content[:10000],  # Limit content
                    "url": url,
                    "extract": text_content[:500]
                }
            except Exception as e:
                return {"ok": False, "error": f"Failed to extract content from URL: {e}"}
    
    except Exception as e:
        return {"ok": False, "error": f"Error processing wiki URL: {e}"}

def chunk_wiki_content(content: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Chunk wiki content into smaller segments for vector DB storage.
    
    Args:
        content: Full wiki page content
        chunk_size: Target chunk size in characters
        overlap: Overlap between chunks in words
    
    Returns:
        List of chunk dicts with 'text', 'chunk_id'
    """
    if not content or not content.strip():
        return []
    
    chunks = []
    words = content.split()
    current_chunk = []
    current_length = 0
    
    for word in words:
        word_len = len(word) + 1  # +1 for space
        if current_length + word_len > chunk_size and current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append({
                "text": chunk_text,
                "chunk_id": len(chunks)
            })
            # Overlap: keep last N words
            overlap_words = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_words + [word]
            current_length = sum(len(w) + 1 for w in current_chunk)
        else:
            current_chunk.append(word)
            current_length += word_len
    
    # Add final chunk
    if current_chunk:
        chunk_text = " ".join(current_chunk)
        chunks.append({
            "text": chunk_text,
            "chunk_id": len(chunks)
        })
    
    return chunks

