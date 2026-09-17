"""
RAG Documentation Assistant — Demo Sequence
============================================

Run each step manually in order. Delete chroma_data/ between steps 2 and 3.

  Step 1 — Ingest with CHARACTER splitting (broken chunks):
      python demo/02_ingest_char.py

  Step 2 — Query (observe poor results from fragmented chunks):
      python demo/03_query.py "How does FastMCP register a tool with the MCP server?"

  Step 3 — Delete the vector store, then ingest with SEMANTIC splitting:
      rm -rf chroma_data/
      python demo/02_ingest.py

  Step 4 — Same query (observe clean, cited answer):
      python demo/03_query.py "How does FastMCP register a tool with the MCP server?"

  Optional — Chunking stats comparison (no DB required):
      python demo/01_chunking_comparison.py
"""
