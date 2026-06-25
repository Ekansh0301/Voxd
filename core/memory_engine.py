"""
core/memory_engine.py — Persistent Local Memory
================================================================================
Uses ChromaDB (local, no server needed) to store and recall conversations.
Embeddings via sentence-transformers (CPU, lightweight).

Flash remembers:
- Past conversations and preferences
- What you've asked before
- System states you've checked
- Anything you've mentioned about your setup
================================================================================
"""

import logging
import time
from pathlib import Path

log = logging.getLogger('flash.memory')

MAX_MEMORY_ITEMS = 1000
RECALL_LIMIT = 5


class MemoryEngine:
    """
    Persistent conversational memory using ChromaDB.
    Fully local, no external API.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._embedding_fn = None
        self._id_counter = 0
        self._ready = False

        self._init_db()

    def _init_db(self):
        """Initialize ChromaDB with local embeddings."""
        try:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=str(self.db_path),
                settings=Settings(anonymized_telemetry=False)
            )

            # Use sentence-transformers for embedding
            try:
                from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
                self._embedding_fn = SentenceTransformerEmbeddingFunction(
                    model_name='all-MiniLM-L6-v2'  # Tiny, fast, good quality
                )
                log.info("Using SentenceTransformer embeddings")
            except Exception:
                log.warning("SentenceTransformer not available, using default embeddings")
                self._embedding_fn = None

            # Get or create collection
            self._collection = self._client.get_or_create_collection(
                name='flash_memory',
                embedding_function=self._embedding_fn,
                metadata={'hnsw:space': 'cosine'}
            )

            # Get current item count
            count = self._collection.count()
            self._id_counter = count
            log.info(f"Memory loaded: {count} stored memories at {self.db_path}")
            self._ready = True

        except ImportError:
            log.warning("ChromaDB not installed. Memory disabled.")
            log.warning("Install with: pip install chromadb sentence-transformers")
        except Exception as e:
            log.error(f"Memory init failed: {e}")

    def save(self, user_input: str, assistant_reply: str):
        """Save a conversation exchange to memory."""
        if not self._ready:
            return

        try:
            self._id_counter += 1
            doc_id = f"mem_{self._id_counter}_{int(time.time())}"

            # Store both user input and reply together
            document = (
                f"User said: {user_input}\n"
                f"Flash replied: {assistant_reply}"
            )

            metadata = {
                'user': user_input[:200],
                'reply': assistant_reply[:500],
                'timestamp': int(time.time()),
            }

            self._collection.add(
                documents=[document],
                metadatas=[metadata],
                ids=[doc_id]
            )

            # Prune old memories if over limit
            count = self._collection.count()
            if count > MAX_MEMORY_ITEMS:
                self._prune_old()

        except Exception as e:
            log.error(f"Memory save failed: {e}")

    def recall(self, query: str, limit: int = RECALL_LIMIT) -> str:
        """
        Find memories relevant to the current query.
        Returns a formatted string for injection into the LLM prompt.
        """
        if not self._ready:
            return ""

        try:
            count = self._collection.count()
            if count == 0:
                return ""

            actual_limit = min(limit, count)
            results = self._collection.query(
                query_texts=[query],
                n_results=actual_limit,
                include=['documents', 'metadatas', 'distances']
            )

            if not results or not results['documents']:
                return ""

            docs = results['documents'][0]
            distances = results['distances'][0]

            # Filter by relevance (cosine distance < 0.8 = relevant)
            relevant = [
                doc for doc, dist in zip(docs, distances)
                if dist < 0.8
            ]

            if not relevant:
                return ""

            memory_text = "Memories from past conversations:\n"
            for doc in relevant[:3]:
                memory_text += f"- {doc[:200]}\n"

            return memory_text

        except Exception as e:
            log.error(f"Memory recall failed: {e}")
            return ""

    def _prune_old(self):
        """Remove oldest memories when over limit."""
        try:
            all_items = self._collection.get(
                include=['metadatas'],
            )
            if not all_items or not all_items['ids']:
                return

            # Sort by timestamp, remove oldest 10%
            ids_with_ts = list(zip(
                all_items['ids'],
                [m.get('timestamp', 0) for m in all_items['metadatas']]
            ))
            ids_with_ts.sort(key=lambda x: x[1])

            to_remove = int(len(ids_with_ts) * 0.1)
            old_ids = [x[0] for x in ids_with_ts[:to_remove]]

            if old_ids:
                self._collection.delete(ids=old_ids)
                log.info(f"Pruned {len(old_ids)} old memories")

        except Exception as e:
            log.error(f"Memory prune failed: {e}")

    def clear_all(self):
        """Wipe all memories."""
        if not self._ready:
            return
        try:
            self._client.delete_collection('flash_memory')
            self._collection = self._client.get_or_create_collection(
                name='flash_memory',
                embedding_function=self._embedding_fn
            )
            self._id_counter = 0
            log.info("Memory cleared.")
        except Exception as e:
            log.error(f"Memory clear failed: {e}")

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get n most recent memories."""
        if not self._ready:
            return []
        try:
            all_items = self._collection.get(include=['metadatas'])
            if not all_items:
                return []
            metas = all_items['metadatas']
            metas.sort(key=lambda m: m.get('timestamp', 0), reverse=True)
            return metas[:n]
        except Exception as e:
            log.error(f"Get recent failed: {e}")
            return []

    @property
    def count(self) -> int:
        """Number of stored memories."""
        if not self._ready:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
