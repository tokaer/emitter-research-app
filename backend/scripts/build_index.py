#!/usr/bin/env python3
"""Build SQLite database and FAISS embedding index from ecoinvent CSV.

Run from the backend directory:
    python -m scripts.build_index
"""
from __future__ import annotations

import logging
import sys
import os

# Add backend dir to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.dataset_store import DatasetStore
from app.services.embedding_builder import EmbeddingIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    # Step 1: Load CSV into SQLite
    logger.info("=== Step 1: Building SQLite database ===")
    store = DatasetStore(settings.db_path)
    store.initialize_from_csv(settings.csv_path)

    # Verify
    total = store.connect().execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    market = store.connect().execute(
        "SELECT COUNT(*) FROM datasets WHERE is_market = 1"
    ).fetchone()[0]
    units = store.get_all_units()
    logger.info(f"  Total rows: {total}")
    logger.info(f"  Market rows: {market}")
    logger.info(f"  Searchable rows: {total - market}")
    logger.info(f"  Distinct units: {sorted(units)}")

    # Quick FTS test
    fts_results = store.fts_search("webcam camera", limit=5)
    logger.info(f"  FTS test 'webcam camera': {len(fts_results)} results")
    for rid, score in fts_results:
        ds = store.get_dataset_by_id(rid)
        if ds:
            logger.info(f"    [{score:.2f}] {ds.activity_name} | {ds.product_name} | {ds.geography}")

    # Step 2: Build FAISS embedding index
    logger.info("=== Step 2: Building FAISS embedding index ===")
    texts_with_ids = store.get_non_market_search_texts()
    logger.info(f"  Non-market texts to encode: {len(texts_with_ids)}")

    emb_index = EmbeddingIndex(model_name=settings.embedding_model)
    emb_index.build_index(texts_with_ids)
    emb_index.save(settings.faiss_index_path, settings.faiss_metadata_path)

    # Quick embedding test
    results = emb_index.search("webcam digital camera plastic", top_k=5)
    logger.info(f"  Embedding test 'webcam digital camera plastic': {len(results)} results")
    for rid, score in results:
        ds = store.get_dataset_by_id(rid)
        if ds:
            logger.info(f"    [{score:.4f}] {ds.activity_name} | {ds.product_name} | {ds.geography}")

    # Ensure job tables exist
    store.ensure_job_tables()

    store.close()
    logger.info("=== Done! ===")


if __name__ == "__main__":
    main()
