from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    data_dir: str = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    csv_filename: str = "Cut-off Cumulative LCIA v3.11 Kopie.csv"
    db_filename: str = "emitter.db"

    # Embedding
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    faiss_index_file: str = "embeddings/index.faiss"
    faiss_metadata_file: str = "embeddings/metadata.pkl"

    # LLM
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    llm_temperature: float = 0.2
    llm_top_p: float = 0.4

    # Search
    candidate_top_k: int = 20
    bm25_top_n: int = 100
    embedding_top_n: int = 100
    rrf_k: int = 60

    # Server
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        env_file_encoding = "utf-8"

    @property
    def csv_path(self) -> Path:
        return Path(self.data_dir) / self.csv_filename

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_filename

    @property
    def faiss_index_path(self) -> Path:
        return Path(self.data_dir) / self.faiss_index_file

    @property
    def faiss_metadata_path(self) -> Path:
        return Path(self.data_dir) / self.faiss_metadata_file


settings = Settings()
