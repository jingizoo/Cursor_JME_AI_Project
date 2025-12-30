# src/vector_db.py
"""
Vector database for PDF text content.
Uses ChromaDB for local, lightweight vector storage.
"""
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Global client (initialized on first use)
_chroma_client = None
_chroma_collection = None

def _get_client():
    """Initialize ChromaDB client and collection."""
    global _chroma_client, _chroma_collection
    if not CHROMA_AVAILABLE:
        return None, None
    
    if _chroma_client is None:
        # Use local persistent storage
        db_path = Path("data/.chroma_db")
        db_path.mkdir(parents=True, exist_ok=True)
        
        _chroma_client = chromadb.PersistentClient(
            path=str(db_path),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Create or get collection
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="pdf_documents",
            metadata={"description": "PDF text chunks for semantic search"}
        )
    
    return _chroma_client, _chroma_collection

def extract_text_from_pdf(pdf_path: Path, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Extract text from PDF and chunk it.
    Returns list of chunks with metadata.
    """
    if not PDF_AVAILABLE:
        return []
    
    chunks = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text()
                if page_text:
                    full_text += f"\n[Page {page_num}]\n{page_text}\n"
            
            if not full_text.strip():
                return []
            
            # Simple chunking by character count with overlap
            words = full_text.split()
            current_chunk = []
            current_length = 0
            
            for word in words:
                word_len = len(word) + 1  # +1 for space
                if current_length + word_len > chunk_size and current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append({
                        "text": chunk_text,
                        "source_file": pdf_path.name,
                        "page": page_num,  # Approximate
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
                    "source_file": pdf_path.name,
                    "page": page_num,
                    "chunk_id": len(chunks)
                })
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return []
    
    return chunks

def _generate_embedding_id(pdf_path: Path, chunk_id: int) -> str:
    """Generate unique ID for a chunk."""
    return hashlib.sha256(f"{pdf_path.name}|{chunk_id}".encode()).hexdigest()[:16]

def store_pdf_embeddings(pdf_path: Path, base_url: str, embedding_model: str = "nomic-embed-text") -> Dict[str, Any]:
    """
    Extract text from PDF, generate embeddings, and store in vector DB.
    Uses Ollama's embedding model.
    """
    if not CHROMA_AVAILABLE:
        return {"ok": False, "error": "ChromaDB not available (pip install chromadb)"}
    
    client, collection = _get_client()
    if not client:
        return {"ok": False, "error": "ChromaDB not available"}
    
    # Extract text chunks
    chunks = extract_text_from_pdf(pdf_path)
    if not chunks:
        return {"ok": False, "error": "No text extracted from PDF"}
    
    # Generate embeddings using Ollama
    try:
        import requests
        embeddings = []
        ids = []
        metadatas = []
        documents = []
        
        for chunk in chunks:
            chunk_id = _generate_embedding_id(pdf_path, chunk["chunk_id"])
            ids.append(chunk_id)
            documents.append(chunk["text"])
            metadatas.append({
                "source_file": chunk["source_file"],
                "page": chunk["page"],
                "chunk_id": chunk["chunk_id"]
            })
            
            # Get embedding from Ollama
            try:
                resp = requests.post(
                    f"{base_url}/api/embeddings",
                    json={"model": embedding_model, "prompt": chunk["text"]},
                    timeout=30
                )
                resp.raise_for_status()
                embedding = resp.json().get("embedding", [])
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Fallback: skip if embedding fails
                    ids.pop()
                    documents.pop()
                    metadatas.pop()
            except Exception as e:
                print(f"Warning: Failed to generate embedding for chunk {chunk_id} (model: {embedding_model}): {e}")
                # Try fallback model if available
                if embedding_model != "all-minilm":
                    try:
                        resp = requests.post(
                            f"{base_url}/api/embeddings",
                            json={"model": "all-minilm", "prompt": chunk["text"]},
                            timeout=30
                        )
                        resp.raise_for_status()
                        embedding = resp.json().get("embedding", [])
                        if embedding:
                            embeddings.append(embedding)
                        else:
                            ids.pop()
                            documents.pop()
                            metadatas.pop()
                    except:
                        ids.pop()
                        documents.pop()
                        metadatas.pop()
                else:
                    ids.pop()
                    documents.pop()
                    metadatas.pop()
        
        if not embeddings:
            return {"ok": False, "error": "Failed to generate any embeddings"}
        
        # Store in ChromaDB
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        return {
            "ok": True,
            "chunks_stored": len(embeddings),
            "source_file": pdf_path.name
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to store embeddings: {e}"}

def search_pdf_context(question: str, base_url: str, embedding_model: str = "nomic-embed-text", top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Search PDF content for relevant context to answer the question.
    Returns top_k most relevant chunks.
    """
    if not CHROMA_AVAILABLE:
        return []
    
    client, collection = _get_client()
    if not client:
        return []
    
    # Check if collection is empty
    try:
        count = collection.count()
        if count == 0:
            return []
    except Exception:
        return []
    
    # Generate embedding for question
    try:
        import requests
        resp = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": embedding_model, "prompt": question},
            timeout=10
        )
        resp.raise_for_status()
        query_embedding = resp.json().get("embedding", [])
        if not query_embedding:
            # Try fallback model
            if embedding_model != "all-minilm":
                try:
                    resp = requests.post(
                        f"{base_url}/api/embeddings",
                        json={"model": "all-minilm", "prompt": question},
                        timeout=10
                    )
                    resp.raise_for_status()
                    query_embedding = resp.json().get("embedding", [])
                except:
                    pass
            if not query_embedding:
                return []
    except Exception as e:
        print(f"Warning: Failed to generate query embedding (model: {embedding_model}): {e}")
        return []
    
    # Search in ChromaDB
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        contexts = []
        if results and results.get("documents") and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results.get("metadatas") and results["metadatas"][0] else {}
                distance = results["distances"][0][i] if results.get("distances") and results["distances"][0] else None
                contexts.append({
                    "text": doc,
                    "source_file": metadata.get("source_file", "unknown"),
                    "page": metadata.get("page", 0),
                    "relevance_score": 1.0 - distance if distance is not None else None
                })
        
        return contexts
    except Exception as e:
        print(f"Warning: Vector search failed: {e}")
        return []

def store_wiki_embeddings(title: str, content: str, url: str, base_url: str, embedding_model: str = "nomic-embed-text") -> Dict[str, Any]:
    """
    Store wiki page content in vector DB.
    
    Args:
        title: Wiki page title
        content: Full wiki page content
        url: Source URL
        base_url: Ollama base URL
        embedding_model: Embedding model name
    
    Returns:
        Dict with 'ok', 'chunks_stored', 'error'
    """
    if not CHROMA_AVAILABLE:
        return {"ok": False, "error": "ChromaDB not available (pip install chromadb)"}
    
    client, collection = _get_client()
    if not client:
        return {"ok": False, "error": "ChromaDB not available"}
    
    # Chunk the content
    from .wiki_extractor import chunk_wiki_content
    chunks = chunk_wiki_content(content, chunk_size=500, overlap=50)
    if not chunks:
        return {"ok": False, "error": "No content to chunk"}
    
    # Generate embeddings
    try:
        import requests
        embeddings = []
        ids = []
        metadatas = []
        documents = []
        
        for chunk in chunks:
            chunk_id = hashlib.sha256(f"{url}|{chunk['chunk_id']}".encode()).hexdigest()[:16]
            ids.append(chunk_id)
            documents.append(chunk["text"])
            metadatas.append({
                "source_type": "wiki",
                "source_title": title,
                "source_url": url,
                "chunk_id": chunk["chunk_id"]
            })
            
            # Get embedding from Ollama
            try:
                resp = requests.post(
                    f"{base_url}/api/embeddings",
                    json={"model": embedding_model, "prompt": chunk["text"]},
                    timeout=30
                )
                resp.raise_for_status()
                embedding = resp.json().get("embedding", [])
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Fallback: skip if embedding fails
                    ids.pop()
                    documents.pop()
                    metadatas.pop()
            except Exception as e:
                print(f"Warning: Failed to generate embedding for wiki chunk {chunk_id}: {e}")
                # Try fallback model
                if embedding_model != "all-minilm":
                    try:
                        resp = requests.post(
                            f"{base_url}/api/embeddings",
                            json={"model": "all-minilm", "prompt": chunk["text"]},
                            timeout=30
                        )
                        resp.raise_for_status()
                        embedding = resp.json().get("embedding", [])
                        if embedding:
                            embeddings.append(embedding)
                        else:
                            ids.pop()
                            documents.pop()
                            metadatas.pop()
                    except:
                        ids.pop()
                        documents.pop()
                        metadatas.pop()
                else:
                    ids.pop()
                    documents.pop()
                    metadatas.pop()
        
        if not embeddings:
            return {"ok": False, "error": "Failed to generate any embeddings"}
        
        # Store in ChromaDB
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        return {
            "ok": True,
            "chunks_stored": len(embeddings),
            "source_title": title,
            "source_url": url
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to store wiki embeddings: {e}"}

def delete_pdf_embeddings(pdf_name: str) -> Dict[str, Any]:
    """Delete all embeddings for a specific PDF file."""
    if not CHROMA_AVAILABLE:
        return {"ok": False, "error": "ChromaDB not available"}
    
    client, collection = _get_client()
    if not client:
        return {"ok": False, "error": "ChromaDB not available"}
    
    try:
        # Get all documents for this PDF
        all_data = collection.get()
        ids_to_delete = []
        
        if all_data and all_data.get("metadatas"):
            for i, metadata in enumerate(all_data["metadatas"]):
                if metadata.get("source_file") == pdf_name:
                    ids_to_delete.append(all_data["ids"][i])
        
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            return {"ok": True, "deleted": len(ids_to_delete)}
        else:
            return {"ok": True, "deleted": 0, "message": "No embeddings found for this PDF"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to delete embeddings: {e}"}

