"""Load ecoinvent CSV into SQLite with FTS5 index for fast text search."""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import pandas as pd

from app.models import DatasetRow

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_thread_local = threading.local()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS datasets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    activity_name       TEXT NOT NULL,
    activity_name_lower TEXT NOT NULL,
    geography           TEXT NOT NULL,
    product_name        TEXT NOT NULL,
    product_name_lower  TEXT NOT NULL,
    unit                TEXT NOT NULL,
    amount              INTEGER NOT NULL,
    biogenic_kg         REAL NOT NULL,
    total_excl_bio_kg   REAL NOT NULL,
    is_market           INTEGER NOT NULL DEFAULT 0,
    search_text         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_datasets_uuid ON datasets(uuid);
CREATE INDEX IF NOT EXISTS idx_datasets_geography ON datasets(geography);
CREATE INDEX IF NOT EXISTS idx_datasets_unit ON datasets(unit);
CREATE INDEX IF NOT EXISTS idx_datasets_is_market ON datasets(is_market);
CREATE INDEX IF NOT EXISTS idx_datasets_geo_market ON datasets(geography, is_market);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS datasets_fts USING fts5(
    search_text,
    content='datasets',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""

_POPULATE_FTS = """
INSERT INTO datasets_fts(rowid, search_text)
SELECT id, search_text FROM datasets;
"""

_CREATE_JOB_TABLES = """
CREATE TABLE IF NOT EXISTS processing_jobs (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    mode        TEXT NOT NULL CHECK(mode IN ('auto', 'review')),
    status      TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'completed', 'error')),
    total_rows  INTEGER NOT NULL DEFAULT 0,
    done_rows   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS input_rows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              TEXT NOT NULL REFERENCES processing_jobs(id),
    row_index           INTEGER NOT NULL,
    scope               TEXT,
    kategorie           TEXT,
    unterkategorie      TEXT,
    bezeichnung         TEXT NOT NULL,
    produktinformationen TEXT,
    referenzeinheit     TEXT NOT NULL,
    region              TEXT,
    referenzjahr        TEXT,
    bezeichnung_norm    TEXT,
    produktinfo_norm    TEXT,
    region_norm         TEXT DEFAULT 'GLO',
    status              TEXT NOT NULL DEFAULT 'pending',
    error_message       TEXT
);

CREATE TABLE IF NOT EXISTS row_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    input_row_id        INTEGER NOT NULL REFERENCES input_rows(id),
    decision_type       TEXT NOT NULL,
    selected_uuid       TEXT,
    candidates_json     TEXT,
    components_json     TEXT,
    biogenic_t          TEXT,
    common_t            TEXT,
    beschreibung        TEXT,
    quelle              TEXT,
    detailed_calc       TEXT,
    provenance_json     TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# DatasetStore
# ---------------------------------------------------------------------------

class DatasetStore:
    """Manages the SQLite database with ecoinvent data."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._units_cache: Optional[set[str]] = None
        self._geographies_cache: Optional[set[str]] = None

    def connect(self) -> sqlite3.Connection:
        # Use thread-local connection to avoid conflicts
        if not hasattr(_thread_local, 'conn') or _thread_local.conn is None:
            _thread_local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,  # 30 second timeout for locks
            )
            _thread_local.conn.row_factory = sqlite3.Row
            _thread_local.conn.execute("PRAGMA journal_mode=WAL")
            _thread_local.conn.execute("PRAGMA foreign_keys=ON")
            _thread_local.conn.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout
        return _thread_local.conn

    def close(self):
        if hasattr(_thread_local, 'conn') and _thread_local.conn is not None:
            _thread_local.conn.close()
            _thread_local.conn = None

    # ------------------------------------------------------------------
    # Initialization: load CSV into SQLite
    # ------------------------------------------------------------------

    def initialize_from_csv(self, csv_path: Path):
        """Load the ecoinvent CSV into SQLite, creating tables and FTS index."""
        conn = self.connect()

        # Check if already loaded
        try:
            count = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
            if count > 0:
                logger.info(f"Database already contains {count} rows, skipping CSV load.")
                return
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        logger.info(f"Loading CSV from {csv_path}...")

        # Read CSV with European format
        df = pd.read_csv(
            csv_path,
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
        )

        # Parse European decimals (comma -> dot)
        for col in ["Biogenic [kg CO2-Eq]", "Total (excl. Biogenic) [kg CO2-Eq]"]:
            df[col] = df[col].str.replace(",", ".").astype(float)

        df["Reference Product Amount"] = df["Reference Product Amount"].astype(int)

        # Fill missing Geography with empty string (will be treated as unspecified)
        df["Geography"] = df["Geography"].fillna("")

        # Compute derived columns
        df["activity_name_lower"] = df["Activity Name"].str.lower().str.strip()
        df["product_name_lower"] = df["Reference Product Name"].str.lower().str.strip()
        df["is_market"] = df["activity_name_lower"].str.startswith("market").astype(int)
        df["search_text"] = df["activity_name_lower"] + " " + df["product_name_lower"]

        # Create tables
        conn.executescript(_CREATE_TABLES)
        conn.executescript(_CREATE_JOB_TABLES)

        # Insert data
        logger.info(f"Inserting {len(df)} rows into SQLite...")
        for _, row in df.iterrows():
            conn.execute(
                """INSERT INTO datasets
                   (uuid, activity_name, activity_name_lower, geography,
                    product_name, product_name_lower, unit, amount,
                    biogenic_kg, total_excl_bio_kg, is_market, search_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["Activity UUID_Product UUID"],
                    row["Activity Name"],
                    row["activity_name_lower"],
                    row["Geography"],
                    row["Reference Product Name"],
                    row["product_name_lower"],
                    row["Reference Product Unit"],
                    row["Reference Product Amount"],
                    row["Biogenic [kg CO2-Eq]"],
                    row["Total (excl. Biogenic) [kg CO2-Eq]"],
                    row["is_market"],
                    row["search_text"],
                ),
            )

        conn.commit()

        # Create FTS5 index
        logger.info("Building FTS5 index...")
        conn.executescript(_CREATE_FTS)
        conn.execute(_POPULATE_FTS)
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        market = conn.execute(
            "SELECT COUNT(*) FROM datasets WHERE is_market = 1"
        ).fetchone()[0]
        logger.info(
            f"Database initialized: {total} total rows, {market} market rows, "
            f"{total - market} searchable."
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _row_to_dataset(self, row: sqlite3.Row) -> DatasetRow:
        return DatasetRow(
            id=row["id"],
            uuid=row["uuid"],
            activity_name=row["activity_name"],
            geography=row["geography"],
            product_name=row["product_name"],
            unit=row["unit"],
            amount=row["amount"],
            biogenic_kg=row["biogenic_kg"],
            total_excl_bio_kg=row["total_excl_bio_kg"],
            is_market=bool(row["is_market"]),
        )

    def lookup_by_uuid(self, uuid: str) -> Optional[DatasetRow]:
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM datasets WHERE uuid = ?", (uuid,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dataset(row)

    def lookup_by_uuids(self, uuids: list[str]) -> list[DatasetRow]:
        if not uuids:
            return []
        conn = self.connect()
        placeholders = ",".join("?" for _ in uuids)
        rows = conn.execute(
            f"SELECT * FROM datasets WHERE uuid IN ({placeholders})", uuids
        ).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    def get_all_units(self) -> set[str]:
        if self._units_cache is not None:
            return self._units_cache
        conn = self.connect()
        rows = conn.execute(
            "SELECT DISTINCT unit FROM datasets"
        ).fetchall()
        self._units_cache = {r["unit"] for r in rows}
        return self._units_cache

    def get_all_geographies(self) -> set[str]:
        if self._geographies_cache is not None:
            return self._geographies_cache
        conn = self.connect()
        rows = conn.execute(
            "SELECT DISTINCT geography FROM datasets"
        ).fetchall()
        self._geographies_cache = {r["geography"] for r in rows}
        return self._geographies_cache

    def fts_search(self, query: str, limit: int = 100) -> list[tuple[int, float]]:
        """FTS5 search returning (rowid, bm25_score) pairs.
        Lower bm25 score = better match (it returns negative values)."""
        conn = self.connect()
        # Escape special FTS5 characters
        safe_query = query.replace('"', '""')
        # Use each word as a separate term for broad matching
        words = safe_query.split()
        if not words:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in words)
        rows = conn.execute(
            f"""SELECT rowid, bm25(datasets_fts) as score
                FROM datasets_fts
                WHERE search_text MATCH ?
                ORDER BY score
                LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [(r["rowid"], r["score"]) for r in rows]

    def get_non_market_rows(self) -> list[DatasetRow]:
        """Get all non-market rows (for building embeddings index)."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM datasets WHERE is_market = 0 ORDER BY id"
        ).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    def get_non_market_search_texts(self) -> list[tuple[int, str]]:
        """Get (id, search_text) for all non-market rows. For BM25/embedding building."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, search_text FROM datasets WHERE is_market = 0 ORDER BY id"
        ).fetchall()
        return [(r["id"], r["search_text"]) for r in rows]

    def get_dataset_by_id(self, row_id: int) -> Optional[DatasetRow]:
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM datasets WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dataset(row)

    def get_datasets_by_ids(self, row_ids: list[int]) -> list[DatasetRow]:
        if not row_ids:
            return []
        conn = self.connect()
        placeholders = ",".join("?" for _ in row_ids)
        rows = conn.execute(
            f"SELECT * FROM datasets WHERE id IN ({placeholders})", row_ids
        ).fetchall()
        # Return in order matching row_ids
        by_id = {r["id"]: self._row_to_dataset(r) for r in rows}
        return [by_id[rid] for rid in row_ids if rid in by_id]

    # ------------------------------------------------------------------
    # Job / input row management
    # ------------------------------------------------------------------

    def create_job(self, job_id: str, mode: str, total_rows: int):
        conn = self.connect()
        conn.execute(
            "INSERT INTO processing_jobs (id, mode, total_rows) VALUES (?, ?, ?)",
            (job_id, mode, total_rows),
        )
        conn.commit()

    def get_job(self, job_id: str) -> Optional[dict]:
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_job_status(self, job_id: str, status: str, done_rows: Optional[int] = None):
        conn = self.connect()
        if done_rows is not None:
            conn.execute(
                "UPDATE processing_jobs SET status = ?, done_rows = ? WHERE id = ?",
                (status, done_rows, job_id),
            )
        else:
            conn.execute(
                "UPDATE processing_jobs SET status = ? WHERE id = ?",
                (status, job_id),
            )
        conn.commit()

    def insert_input_row(self, job_id: str, row_index: int, data: dict) -> int:
        conn = self.connect()
        cur = conn.execute(
            """INSERT INTO input_rows
               (job_id, row_index, scope, kategorie, unterkategorie,
                bezeichnung, produktinformationen, referenzeinheit,
                region, referenzjahr, bezeichnung_norm, produktinfo_norm, region_norm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                row_index,
                data.get("scope"),
                data.get("kategorie"),
                data.get("unterkategorie"),
                data["bezeichnung"],
                data.get("produktinformationen"),
                data["referenzeinheit"],
                data.get("region"),
                data.get("referenzjahr"),
                data.get("bezeichnung_norm"),
                data.get("produktinfo_norm"),
                data.get("region_norm", "GLO"),
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_input_rows(self, job_id: str) -> list[dict]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM input_rows WHERE job_id = ? ORDER BY row_index",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_input_row(self, row_id: int) -> Optional[dict]:
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM input_rows WHERE id = ?", (row_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_input_row_status(self, row_id: int, status: str, error_message: Optional[str] = None):
        conn = self.connect()
        conn.execute(
            "UPDATE input_rows SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, row_id),
        )
        conn.commit()

    def update_input_row_fields(self, row_id: int, updates: dict):
        conn = self.connect()
        set_clauses = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [row_id]
        conn.execute(
            f"UPDATE input_rows SET {set_clauses} WHERE id = ?", values
        )
        conn.commit()

    def delete_input_row(self, row_id: int):
        conn = self.connect()
        conn.execute("DELETE FROM row_results WHERE input_row_id = ?", (row_id,))
        conn.execute("DELETE FROM input_rows WHERE id = ?", (row_id,))
        conn.commit()

    def save_row_result(self, result: dict) -> int:
        conn = self.connect()
        cur = conn.execute(
            """INSERT INTO row_results
               (input_row_id, decision_type, selected_uuid, candidates_json,
                components_json, biogenic_t, common_t, beschreibung, quelle,
                detailed_calc, provenance_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result["input_row_id"],
                result["decision_type"],
                result.get("selected_uuid"),
                result.get("candidates_json"),
                result.get("components_json"),
                result.get("biogenic_t"),
                result.get("common_t"),
                result.get("beschreibung"),
                result.get("quelle"),
                result.get("detailed_calc"),
                result.get("provenance_json"),
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_row_result(self, input_row_id: int) -> Optional[dict]:
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM row_results WHERE input_row_id = ? ORDER BY id DESC LIMIT 1",
            (input_row_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_all_row_results(self, job_id: str) -> list[dict]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT rr.* FROM row_results rr
               JOIN input_rows ir ON rr.input_row_id = ir.id
               WHERE ir.job_id = ?
               ORDER BY ir.row_index""",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_ambiguous_rows(self, job_id: str) -> list[dict]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT ir.*, rr.candidates_json, rr.decision_type
               FROM input_rows ir
               JOIN row_results rr ON rr.input_row_id = ir.id
               WHERE ir.job_id = ? AND ir.status = 'ambiguous'
               ORDER BY ir.row_index""",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def ensure_job_tables(self):
        """Create job/input/result tables if they don't exist."""
        conn = self.connect()
        conn.executescript(_CREATE_JOB_TABLES)
        conn.commit()
