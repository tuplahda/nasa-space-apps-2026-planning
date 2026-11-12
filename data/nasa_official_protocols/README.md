# NASA Official Challenge Protocols Directory

Drop any newly released NASA Space Apps challenge clinical case studies, JSON protocols, CSV tables, or Markdown guidelines into this folder (`data/nasa_official_protocols/`).

`backend/services/rag_engine.py` automatically scans this folder at startup (and via `reload_knowledge_base()`) and indexes `.json`, `.csv`, `.md`, and `.txt` files into the local Level V RAG Knowledge Base without breaking existing API contracts.
