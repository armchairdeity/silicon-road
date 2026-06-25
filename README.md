# Mad Claude: Silicon Road

RAG system over a scavenged electronics component inventory.

- **Phase 1 (current):** Spreadsheet → Perplexity embeddings → ChromaDB → CLI query
- **Phase 2:** Test suite, MCP server, ChromaDB hardening
- **Phase 3:** Perplexity web chaser, curation UI, full pipeline

## Quick start

```bash
# Install
uv sync

# Ingest the inventory spreadsheet
PERPLEXITY_API_KEY=<key> mcsr-ingest

# Query
PERPLEXITY_API_KEY=<key> mcsr-query "5V boost converter"

# Or interactive mode
PERPLEXITY_API_KEY=<key> mcsr-query
```
