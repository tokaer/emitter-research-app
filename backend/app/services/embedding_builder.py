"""Build and load FAISS embedding index for semantic search."""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingIndex:
    """Manages sentence embeddings and FAISS index for semantic search."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self.model_name = model_name
        self._model = None
        self._index: Optional[faiss.Index] = None
        self._id_map: list[int] = []  # position -> dataset row id

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._index is not None

    def build_index(self, texts_with_ids: list[tuple[int, str]], batch_size: int = 256):
        """Build FAISS index from (row_id, search_text) pairs.

        Args:
            texts_with_ids: list of (dataset.id, search_text) tuples
            batch_size: encoding batch size
        """
        ids = [t[0] for t in texts_with_ids]
        texts = [t[1] for t in texts_with_ids]

        logger.info(f"Encoding {len(texts)} texts with {self.model_name}...")
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )

        dim = embeddings.shape[1]
        logger.info(f"Building FAISS index: {len(texts)} vectors x {dim} dimensions")

        # Use IndexFlatIP (inner product = cosine similarity for normalized vectors)
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(embeddings.astype(np.float32))
        self._id_map = ids

        logger.info(f"FAISS index built with {self._index.ntotal} vectors")

    def save(self, index_path: Path, metadata_path: Path):
        """Save FAISS index and id mapping to disk."""
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(index_path))
        with open(metadata_path, "wb") as f:
            pickle.dump(self._id_map, f)
        logger.info(f"Index saved to {index_path} ({index_path.stat().st_size / 1024 / 1024:.1f} MB)")

    def load(self, index_path: Path, metadata_path: Path):
        """Load pre-built FAISS index and id mapping."""
        if not index_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(
                f"Index files not found: {index_path}, {metadata_path}. "
                f"Run `python -m scripts.build_index` first."
            )
        self._index = faiss.read_index(str(index_path))
        with open(metadata_path, "rb") as f:
            self._id_map = pickle.load(f)
        logger.info(
            f"Loaded FAISS index: {self._index.ntotal} vectors, "
            f"{len(self._id_map)} id mappings"
        )

    def search(self, query_text: str, top_k: int = 100) -> list[tuple[int, float]]:
        """Search for similar texts, returning (dataset_row_id, score) pairs.

        Higher score = better match (cosine similarity).
        """
        if self._index is None:
            raise RuntimeError("Index not loaded. Call load() or build_index() first.")

        query_embedding = self.model.encode(
            [query_text], normalize_embeddings=True
        ).astype(np.float32)

        distances, indices = self._index.search(query_embedding, top_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS returns -1 for no result
                break
            row_id = self._id_map[idx]
            results.append((row_id, float(dist)))

        return results
