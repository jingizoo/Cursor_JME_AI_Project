# Wiki Page Ingestion

The application now supports ingesting content from wiki pages (Wikipedia, MediaWiki, etc.) and storing it in the vector database alongside PDFs and Excel data.

## How It Works

1. **Wiki Content Extraction**: Extracts text content from wiki pages via their APIs
2. **Vector Storage**: Chunks and embeds wiki content, storing it in ChromaDB
3. **Semantic Search**: Wiki content is automatically searched when answering questions
4. **Mixed Knowledge**: Combines wiki knowledge with Excel data and PDFs

## Supported Wiki Types

### 1. **Wikipedia** (Public, No API key needed)
- Automatically detected from URLs containing `wikipedia.org`
- Uses Wikipedia REST API
- Example: `https://en.wikipedia.org/wiki/Python_(programming_language)`

### 2. **Internal MediaWiki** (Requires authentication)
- **Primary use case for internal wikis**
- Generic MediaWiki-based wikis (most common for internal wikis)
- Supports custom wiki installations
- **Requires API key/token for authentication**
- Examples:
  - `https://internal-wiki.company.com/wiki/Page_Title`
  - `https://wiki.example.com/w/Page_Title`
  - `https://wiki.example.com/index.php?title=Page_Title`

### 3. **Generic Wikis** (Fallback)
- Attempts to extract content from any wiki-like URL
- Uses HTML parsing as fallback
- Supports authentication via API key

## Usage

### API Endpoint

```bash
POST /ingest
```

### Request Body

```json
{
  "force": false,
  "wiki_urls": [
    "https://en.wikipedia.org/wiki/Financial_statements",
    "https://en.wikipedia.org/wiki/Expense",
    "https://wiki.example.com/wiki/Company_Policy"
  ],
  "wiki_api_key": "optional-api-key-for-private-wikis"
}
```

### Example: Ingest Wiki Pages

```bash
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "force": false,
    "wiki_urls": [
      "https://en.wikipedia.org/wiki/Financial_statements",
      "https://en.wikipedia.org/wiki/Accounting"
    ]
  }'
```

### Example: Internal Wiki with Authentication

**For Bearer Token:**
```bash
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "force": false,
    "wiki_urls": [
      "https://internal-wiki.company.com/wiki/Expense_Policy"
    ],
    "wiki_api_key": "Bearer your-token-here"
  }'
```

**For Session Cookie:**
```bash
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "force": false,
    "wiki_urls": [
      "https://internal-wiki.company.com/wiki/Expense_Policy"
    ],
    "wiki_api_key": "session=abc123def456; token=xyz789"
  }'
```

**For API Key Parameter:**
```bash
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "force": false,
    "wiki_urls": [
      "https://internal-wiki.company.com/wiki/Expense_Policy"
    ],
    "wiki_api_key": "your-api-key-here"
  }'
```

## Response

```json
{
  "ok": true,
  "ingested_sheets": 5,
  "wiki_pages": 2,
  "skipped": 3,
  "errors": []
}
```

- `wiki_pages`: Number of wiki pages successfully ingested
- `ingested_sheets`: Number of Excel/PDF sheets ingested
- `errors`: Any errors encountered (wiki URLs that failed will be listed here)

## How Wiki Content is Used

When you ask questions, the system automatically:

1. **Searches Wiki Content**: Finds relevant wiki chunks using semantic search
2. **Includes in Context**: Adds wiki context to the LLM prompt
3. **Combines with Data**: Uses wiki knowledge to better understand and query Excel/PDF data

### Example Query

**Question**: "What are the accounting principles for expense recognition, and show me expenses that might violate them"

The system will:
1. Find relevant wiki content about "accounting principles" and "expense recognition"
2. Use that context to understand the question better
3. Query Excel expense data
4. Return results that combine wiki knowledge with actual data

## Configuration

### Change Embedding Model

Wiki content uses the same embedding model as PDFs. See `VECTOR_DB_README.md` for configuration.

### Chunk Size

Wiki content is chunked into ~500 character segments. To change this, edit `src/wiki_extractor.py`:

```python
chunks = chunk_wiki_content(content, chunk_size=500, overlap=50)
```

## Authentication for Internal Wikis

Internal wikis typically require authentication. The `wiki_api_key` parameter supports multiple formats:

### 1. Bearer Token
```json
"wiki_api_key": "Bearer your-token-here"
```
- Used for token-based authentication
- Sent as `Authorization: Bearer <token>` header

### 2. Session Cookie
```json
"wiki_api_key": "session=abc123; token=xyz789"
```
- Used for cookie-based authentication
- Multiple cookies can be separated by semicolons
- Format: `key1=value1; key2=value2`

### 3. API Key Parameter
```json
"wiki_api_key": "your-api-key-here"
```
- Used for MediaWiki API key parameter
- Also sent as Bearer token (for compatibility)

### Getting Authentication Credentials

**For MediaWiki:**
1. Log into your internal wiki
2. Go to your user preferences → API access
3. Generate an API token or get your session cookie
4. Use the token/cookie as `wiki_api_key`

**For Other Wikis:**
1. Check your wiki's API documentation
2. Look for API tokens, OAuth tokens, or session cookies
3. Use the appropriate format above

## Troubleshooting

### "Failed to fetch Wikipedia page"
- Check internet connectivity
- Verify the Wikipedia URL is correct
- Some Wikipedia pages may not exist or be restricted

### "Failed to fetch MediaWiki page" or "Authentication failed"
- **For internal wikis**: Verify authentication is required and provided
- Check if API key format is correct (Bearer token, cookie, or API key)
- Verify the wiki URL is accessible from your network
- Test the wiki API directly: `curl "https://your-wiki.com/api.php?action=query&format=json&titles=Test"`
- Some MediaWiki installations may have different API endpoints
- Check firewall/VPN access to internal wiki

### "Cannot connect to wiki" or "Timeout"
- Verify the wiki URL is correct and accessible
- Check network connectivity (especially for internal wikis)
- Ensure VPN is connected if wiki is behind VPN
- Check if wiki requires specific IP whitelisting
- Increase timeout if wiki is slow (requires code change)

### "Failed to generate embeddings"
- Ensure Ollama is running and has the embedding model
- Pull the embedding model: `ollama pull nomic-embed-text`
- Check Ollama URL in environment variables

### "No content extracted"
- Wiki page may be empty or have no text content
- Some wikis may require authentication (use API key)
- Check if the URL format is supported

### Wiki Content Not Appearing in Queries
- Verify wiki pages were successfully ingested (check `wiki_pages` count in response)
- Check ChromaDB collection has data: `data/.chroma_db/`
- Ensure embedding model is working correctly

## Supported URL Formats

### Wikipedia
- `https://en.wikipedia.org/wiki/Page_Title`
- `https://en.wikipedia.org/wiki/Page_Title?query=params` (query params ignored)

### MediaWiki (Internal Wikis)
- `https://internal-wiki.company.com/wiki/Page_Title`
- `https://wiki.example.com/w/Page_Title`
- `https://wiki.example.com/index.php?title=Page_Title`
- `https://wiki.example.com/api.php?action=query&titles=Page_Title` (will extract base URL)

### Generic
- Any URL with `/wiki/` or `/index.php` in the path

## Limitations

- **Text Only**: Only extracts text content (not images, tables, or complex formatting)
- **API Rate Limits**: Wikipedia and some wikis have rate limits
- **Authentication**: Private wikis may require API keys or additional authentication
- **Content Size**: Very large wiki pages may be truncated
- **Format Support**: Some wiki formats may not be fully supported

## Future Enhancements

Potential improvements:
- Support for wiki table extraction
- Caching of wiki content to avoid re-fetching
- Support for wiki categories and related pages
- Automatic wiki discovery from links
- Support for other wiki platforms (Confluence, Notion, etc.)


