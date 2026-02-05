"""FastAPI application: startup, CORS, routes."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.services.candidate_retriever import CandidateRetriever
from app.services.dataset_store import DatasetStore
from app.services.embedding_builder import EmbeddingIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Emitter Research App", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Shared application state
# ---------------------------------------------------------------------------
# These are initialized on startup and available via app.state
# Access in routers: request.app.state.store, etc.


@app.on_event("startup")
def startup():
    logger.info("Starting up Emitter Research App...")

    # Initialize DatasetStore
    store = DatasetStore(settings.db_path)
    store.initialize_from_csv(settings.csv_path)
    store.ensure_job_tables()
    app.state.store = store

    # Load FAISS embedding index
    emb_index = EmbeddingIndex(model_name=settings.embedding_model)
    try:
        emb_index.load(settings.faiss_index_path, settings.faiss_metadata_path)
    except FileNotFoundError:
        logger.warning(
            "FAISS index not found. Run `python -m scripts.build_index` first. "
            "Embedding search will be disabled."
        )
    app.state.embedding_index = emb_index

    # Initialize CandidateRetriever
    retriever = CandidateRetriever(
        store=store,
        embedding_index=emb_index,
        rrf_k=settings.rrf_k,
    )
    retriever.initialize()
    app.state.retriever = retriever

    logger.info("Startup complete.")


@app.on_event("shutdown")
def shutdown():
    logger.info("Shutting down...")
    if hasattr(app.state, "store"):
        app.state.store.close()


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

from app.routers import upload, rows, process, resolve, export  # noqa: E402

app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(rows.router, prefix="/api/v1", tags=["rows"])
app.include_router(process.router, prefix="/api/v1", tags=["process"])
app.include_router(resolve.router, prefix="/api/v1", tags=["resolve"])
app.include_router(export.router, prefix="/api/v1", tags=["export"])


@app.get("/api/v1/health")
def health():
    store: DatasetStore = app.state.store
    emb: EmbeddingIndex = app.state.embedding_index
    conn = store.connect()
    db_rows = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    return {
        "status": "ok",
        "db_rows": db_rows,
        "index_loaded": emb.is_loaded,
        "units": sorted(store.get_all_units()),
    }


@app.get("/api/v1/units")
def list_units():
    return {"units": sorted(app.state.store.get_all_units())}


@app.get("/api/v1/geographies")
def list_geographies():
    return {"geographies": sorted(app.state.store.get_all_geographies())}
