"""Hybrid BM25 + embedding candidate retrieval with region/unit filtering."""
from __future__ import annotations

import logging
import re
from typing import Optional

from rank_bm25 import BM25Okapi
from unidecode import unidecode

from app.models import CandidateResult, DatasetRow, RetrievalResult
from app.services.dataset_store import DatasetStore
from app.services.embedding_builder import EmbeddingIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# German -> ecoinvent unit mapping
# ---------------------------------------------------------------------------

UNIT_MAP: dict[str, Optional[str]] = {
    # Direct DB units (lowercase)
    "kg": "kg",
    "kwh": "kWh",
    "mj": "MJ",
    "m2": "m2",
    "m3": "m3",
    "l": "l",
    "km": "km",
    "ha": "ha",
    "hour": "hour",
    "m": "m",
    "unit": "unit",
    "person*km": "person*km",
    "metric ton*km": "metric ton*km",
    "km*year": "km*year",
    "m2*year": "m2*year",
    "m*year": "m*year",
    "kg*day": "kg*day",
    "guest night": "guest night",
    # German unit names
    "stück": "unit",
    "stueck": "unit",
    "stk": "unit",
    "stk.": "unit",
    "pcs": "unit",
    "pc": "unit",
    "ea": "unit",
    "piece": "unit",
    "pieces": "unit",
    "liter": "l",
    "kilogramm": "kg",
    "kilowattstunde": "kWh",
    "meter": "m",
    "quadratmeter": "m2",
    "kubikmeter": "m3",
    "hektar": "ha",
    "stunde": "hour",
    "stunden": "hour",
    "personenkilometer": "person*km",
    "tonnenkilometer": "metric ton*km",
    "tkm": "metric ton*km",
    "pkm": "person*km",
    "sqm": "m2",
    "cbm": "m3",
}


def map_unit(raw_unit: str) -> Optional[str]:
    """Map a user-provided unit to an ecoinvent DB unit.

    Returns the mapped unit string or None if no mapping exists.
    """
    normalized = raw_unit.strip().lower()
    return UNIT_MAP.get(normalized)


def normalize_query(text: str) -> str:
    """Normalize text for search: lowercase, strip, collapse whitespace, transliterate."""
    text = text.strip().lower()
    text = unidecode(text)  # ä -> a, ö -> o, ü -> u, ß -> ss
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return text.split()


# ---------------------------------------------------------------------------
# CandidateRetriever
# ---------------------------------------------------------------------------

class CandidateRetriever:
    """Hybrid BM25 + embedding search with region/unit filtering."""

    def __init__(
        self,
        store: DatasetStore,
        embedding_index: EmbeddingIndex,
        rrf_k: int = 60,
    ):
        self.store = store
        self.embedding_index = embedding_index
        self.rrf_k = rrf_k

        # Build BM25 index from non-market rows
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: list[int] = []
        self._bm25_rows: dict[int, DatasetRow] = {}

    def initialize(self):
        """Build BM25 index. Call once after DatasetStore is initialized."""
        logger.info("Building BM25 index...")
        texts_with_ids = self.store.get_non_market_search_texts()
        self._bm25_ids = [t[0] for t in texts_with_ids]
        tokenized = [tokenize(t[1]) for t in texts_with_ids]
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index built with {len(self._bm25_ids)} documents")

    def retrieve(
        self,
        bezeichnung: str,
        produktinfo: str,
        referenzeinheit: str,
        region: Optional[str],
        top_k: int = 50,
        scope: Optional[str] = None,
        kategorie: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve candidate datasets for an input row.

        Returns RetrievalResult with either candidates or force_decompose=True.
        """
        # Step 1: Map unit and check existence
        mapped_unit = map_unit(referenzeinheit)
        db_units = self.store.get_all_units()

        if mapped_unit is None or mapped_unit not in db_units:
            return RetrievalResult(
                force_decompose=True,
                force_decompose_reason=(
                    f"Unit '{referenzeinheit}' (mapped: {mapped_unit}) "
                    f"not found in database. Available units: {sorted(db_units)}"
                ),
            )

        # Step 2: Build query text with enhanced context
        query_parts = [bezeichnung]
        if produktinfo:
            query_parts.append(produktinfo)

        # Add scope context hints for better semantic matching
        if scope:
            if "Scope 1" in scope or "1." in scope:
                # Scope 1: Direct emissions, typically combustion
                query_parts.append("combustion burned fuel")
            elif "Scope 3" in scope or "3." in scope:
                # Scope 3: Indirect emissions, typically production/manufacturing
                query_parts.append("production manufacturing")

        # Add category context if available
        if kategorie:
            # Extract meaningful keywords from category (e.g., "Heizung" -> "heating")
            query_parts.append(kategorie)

        query = normalize_query(" ".join(query_parts))
        if not query.strip():
            return RetrievalResult(
                force_decompose=True,
                force_decompose_reason="Empty query after normalization",
            )

        # Step 3: BM25 search
        bm25_results = self._bm25_search(query, top_n=100)

        # Step 4: Embedding search
        embed_results = self._embedding_search(query, top_n=100)

        # Step 5: Reciprocal Rank Fusion
        fused = self._rrf_merge(bm25_results, embed_results)

        # Step 6: Region priority + unit filtering
        region_norm = (region or "GLO").strip().upper()
        region_priority = self._build_region_priority(region_norm)

        scored_candidates = []
        for row_id, rrf_score, bm25_rank, embed_rank in fused:
            ds = self.store.get_dataset_by_id(row_id)
            if ds is None:
                continue

            # Compute region priority
            reg_prio = region_priority.get(ds.geography, 3)

            scored_candidates.append(
                CandidateResult(
                    dataset=ds,
                    bm25_rank=bm25_rank,
                    embedding_rank=embed_rank,
                    fused_score=rrf_score,
                    region_priority=reg_prio,
                )
            )

        # Sort: region priority first, then fused score (descending)
        scored_candidates.sort(key=lambda c: (c.region_priority, -c.fused_score))

        # Filter to preferred unit matches, but include others if few matches
        unit_matched = [c for c in scored_candidates if c.dataset.unit == mapped_unit]
        unit_other = [c for c in scored_candidates if c.dataset.unit != mapped_unit]

        if len(unit_matched) >= top_k:
            final = unit_matched[:top_k]
        else:
            # Fill with non-unit-matched candidates
            final = unit_matched + unit_other[: top_k - len(unit_matched)]

        return RetrievalResult(
            force_decompose=False,
            candidates=final,
            query_used=query,
        )

    def _bm25_search(self, query: str, top_n: int = 100) -> list[tuple[int, float]]:
        """BM25 search returning (dataset_row_id, score) pairs. Higher=better."""
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        # Get top N indices
        top_indices = scores.argsort()[-top_n:][::-1]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self._bm25_ids[idx], float(scores[idx])))
        return results

    def _embedding_search(self, query: str, top_n: int = 100) -> list[tuple[int, float]]:
        """Embedding search returning (dataset_row_id, score) pairs. Higher=better."""
        if not self.embedding_index.is_loaded:
            return []
        return self.embedding_index.search(query, top_k=top_n)

    def _rrf_merge(
        self,
        bm25_results: list[tuple[int, float]],
        embed_results: list[tuple[int, float]],
    ) -> list[tuple[int, float, Optional[int], Optional[int]]]:
        """Reciprocal Rank Fusion: merge two ranked lists.

        Returns list of (row_id, rrf_score, bm25_rank, embed_rank).
        """
        k = self.rrf_k
        scores: dict[int, float] = {}
        bm25_ranks: dict[int, int] = {}
        embed_ranks: dict[int, int] = {}

        for rank, (row_id, _) in enumerate(bm25_results):
            scores[row_id] = scores.get(row_id, 0) + 1.0 / (k + rank + 1)
            bm25_ranks[row_id] = rank + 1

        for rank, (row_id, _) in enumerate(embed_results):
            scores[row_id] = scores.get(row_id, 0) + 1.0 / (k + rank + 1)
            embed_ranks[row_id] = rank + 1

        merged = sorted(scores.items(), key=lambda x: -x[1])
        return [
            (row_id, score, bm25_ranks.get(row_id), embed_ranks.get(row_id))
            for row_id, score in merged
        ]

    def _build_region_priority(self, requested_region: str) -> dict[str, int]:
        """Build region -> priority mapping.

        0 = exact match, 1 = GLO, 2 = RoW, 3 = other.
        """
        prio: dict[str, int] = {requested_region: 0}
        if requested_region != "GLO":
            prio["GLO"] = 1
        if requested_region != "RoW":
            prio["RoW"] = 2
        return prio
