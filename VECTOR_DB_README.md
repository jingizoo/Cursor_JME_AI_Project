# Vector DB for PDF Knowledge

The application now includes a **vector database** that extracts and stores text content from PDFs, enabling semantic search to mix PDF knowledge with Excel data when answering questions.

## How It Works

### 1. **PDF Text Extraction**
- When you ingest a PDF, the system extracts **all text content** (not just tables)
- Text is chunked into ~500 character segments with overlap
- Each chunk is stored with metadata (source file, page number)

### 2. **Embedding Generation**
- Text chunks are converted to **embeddings** using Ollama's embedding model
- Default model: `nomic-embed-text` (fallback: `all-minilm`)
- Embeddings capture semantic meaning, enabling similarity search

### 3. **Vector Storage**
- Uses **ChromaDB** (lightweight, local, persistent)
- Stored in `data/.chroma_db/`
- No external services required

### 4. **Semantic Search**
- When you ask a question, the system:
  1. Converts your question to an embedding
  2. Searches the vector DB for the **top 3 most relevant PDF chunks**
  3. Includes those chunks as context when planning SQL queries

### 5. **Mixed Knowledge**
- The LLM receives:
  - **Excel schema** (tables, columns, data types)
  - **PDF context** (relevant text chunks that help understand the question)
  - **Your question**
- This enables answers that combine structured Excel data with unstructured PDF knowledge

## Installation

```bash
pip install chromadb requests
```

Or install all requirements:
```bash
pip install -r requirements.txt
```

## Setup Embedding Model

You need an embedding model in Ollama. Pull one:

```bash
# Option 1: nomic-embed-text (recommended, ~274MB)
ollama pull nomic-embed-text

# Option 2: all-minilm (smaller, ~23MB, fallback)
ollama pull all-minilm
```

## Usage

### Automatic (During Ingestion)

When you ingest PDFs, text extraction and embedding storage happens automatically:

```bash
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

You'll see output like:
```
✓ Stored 15 text chunks from report.pdf in vector DB
```

### Querying with PDF Context

Just ask questions normally - PDF context is automatically included:

```bash
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What does the policy document say about expense limits?"
  }'
```

The system will:
1. Search PDFs for relevant context about "expense limits"
2. Use that context + Excel schema to generate better SQL
3. Return results that combine both sources

## Example Scenarios

### Scenario 1: Policy Questions
**Question**: "What is the maximum expense amount allowed per transaction according to company policy?"

- **PDF context**: Finds policy document chunks mentioning expense limits
- **Excel data**: Queries expense tables to find actual transactions
- **Result**: Combines policy rules (from PDF) with actual data (from Excel)

### Scenario 2: Context-Aware Queries
**Question**: "Show me expenses that violate the approval threshold"

- **PDF context**: Finds approval policy details (e.g., "expenses over $1000 require approval")
- **Excel data**: Queries expenses table
- **Result**: Filters Excel data based on PDF-defined rules

### Scenario 3: Terminology Mapping
**Question**: "What are our vendor payments this month?"

- **PDF context**: Finds document explaining terminology (e.g., "vendor payments" = "paid_amount" column)
- **Excel data**: Queries using correct column names
- **Result**: Better SQL because LLM understands terminology from PDFs

## Configuration

### Change Embedding Model

Edit `src/vector_db.py`:

```python
# In store_pdf_embeddings and search_pdf_context
embedding_model: str = "your-model-name"
```

### Disable PDF Context

If you want to disable PDF context for a specific query, you can modify the code to pass `include_pdf_context=False` to `plan_sql()`. By default, it's enabled.

### Adjust Chunk Size

Edit `src/vector_db.py` in `extract_text_from_pdf()`:

```python
chunk_size: int = 500,  # Increase for longer context, decrease for more granular chunks
overlap: int = 50       # Overlap between chunks
```

### Adjust Search Results

Edit `src/planner_agent.py` in `plan_sql()`:

```python
pdf_context = search_pdf_context(question, base_url=base_url, top_k=3)  # Change top_k
```

## Troubleshooting

### "ChromaDB not available"
```bash
pip install chromadb
```

### "Failed to generate embedding"
- Check that embedding model is installed: `ollama list`
- Pull the model: `ollama pull nomic-embed-text`
- Check Ollama is running: `curl http://localhost:11434/api/tags`

### "No text extracted from PDF"
- PDF may be image-based (scanned) - text extraction won't work
- PDF may be empty or corrupted
- Try opening PDF in a viewer to verify it has selectable text

### PDF Context Not Being Used
- Check that PDFs were ingested (look for "✓ Stored X text chunks" messages)
- Verify ChromaDB collection has data (check `data/.chroma_db/`)
- Check logs for embedding generation errors

## Technical Details

- **Storage**: ChromaDB persistent storage in `data/.chroma_db/`
- **Embeddings**: Generated via Ollama's `/api/embeddings` endpoint
- **Search**: Cosine similarity search in ChromaDB
- **Integration**: PDF context is added to the LLM system prompt automatically
- **Performance**: Embedding generation is done during ingestion (one-time cost)

## Limitations

- **Text-only**: Only extracts text from PDFs (not images, charts, or complex layouts)
- **Chunking**: Long documents are split into chunks - context may be fragmented
- **Embedding quality**: Depends on the embedding model quality
- **Search accuracy**: Semantic search may not always find the most relevant chunks
- **Model dependency**: Requires an embedding model in Ollama (not just LLM)

## Future Enhancements

Potential improvements:
- Support for image-based PDFs (OCR)
- Multi-modal embeddings (text + table structure)
- Hybrid search (keyword + semantic)
- Automatic re-indexing when PDFs are updated
- Support for other document types (Word, HTML, etc.)

