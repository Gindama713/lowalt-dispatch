"""ChromaDB-backed retrieval over the repository knowledge corpus.

Design rules:
- The corpus is whatever ``knowledge._documents()`` returns (repo docs + knowledge/*.md).
- The index is rebuilt only when the corpus fingerprint changes.
- Any failure here is raised; ``knowledge.search`` decides whether to fall back to
  keyword search. Retrieval must never silently return fabricated excerpts.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSIST_DIR = Path(os.getenv("AERIS_CHROMA_DIR", str(ROOT / "data" / "chroma")))
COLLECTION = "aeris_knowledge"
METADATA = {"hnsw:space": "cosine"}

_lock = threading.RLock()
_collection = None
_collection_fingerprint = None


def _fingerprint() -> str:
    from services.assistant.knowledge import _documents

    digest = hashlib.sha256()
    digest.update(b"line-chunks-v2")
    for path in _documents():
        digest.update(path.encode())
        digest.update(hashlib.sha256((ROOT / path).read_bytes()).digest())
    return digest.hexdigest()[:16]


def _build():
    import chromadb
    from chromadb.utils import embedding_functions

    from services.assistant.knowledge import _documents, _split

    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(PERSIST_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        metadata=METADATA,
    )
    fingerprint = _fingerprint()
    marker = PERSIST_DIR / "corpus.fingerprint"
    cached = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if collection.count() and cached == fingerprint:
        return collection

    stale = collection.get(include=[])["ids"]
    if stale:
        collection.delete(ids=stale)

    documents, metadatas, ids = [], [], []
    for path in _documents():
        for excerpt in _split(path, (ROOT / path).read_bytes()):
            uid = hashlib.sha1(f"{path}:{excerpt.start_line}:{excerpt.revision}".encode()).hexdigest()[:20]
            ids.append(uid)
            documents.append(excerpt.text)
            metadatas.append(
                {
                    "path": excerpt.path,
                    "heading": excerpt.heading,
                    "start_line": excerpt.start_line,
                    "end_line": excerpt.end_line,
                    "revision": excerpt.revision,
                }
            )
    if documents:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
    marker.write_text(fingerprint, encoding="utf-8")
    return collection


def _ensure():
    global _collection, _collection_fingerprint
    with _lock:
        fingerprint = _fingerprint()
        if _collection is None or fingerprint != _collection_fingerprint:
            _collection = _build()
            _collection_fingerprint = fingerprint
        return _collection


def search(query: str, limit: int = 3) -> list[dict]:
    """Return the closest corpus chunks with the same shape as keyword search."""
    collection = _ensure()
    if not collection.count():
        return []
    result = collection.query(query_texts=[query], n_results=max(1, min(limit, 6)))
    rows = []
    for index, doc_id in enumerate(result.get("ids", [[]])[0]):
        metadata = result["metadatas"][0][index] or {}
        distance = result["distances"][0][index] if result.get("distances") else None
        rows.append(
            {
                "path": metadata.get("path", ""),
                "heading": metadata.get("heading", ""),
                "start_line": metadata.get("start_line", 0),
                "end_line": metadata.get("end_line", 0),
                "revision": metadata.get("revision", ""),
                "text": result["documents"][0][index] or "",
                "score": round(1.0 - float(distance), 4) if distance is not None else None,
                "retriever": "chroma",
                "id": doc_id,
            }
        )
    return rows


def reset() -> None:
    """Drop the in-process handle so the next call rebuilds from disk."""
    global _collection, _collection_fingerprint
    with _lock:
        _collection = None
        _collection_fingerprint = None
