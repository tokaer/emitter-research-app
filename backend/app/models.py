from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProcessingMode(str, Enum):
    AUTO = "auto"
    REVIEW = "review"


class RowStatus(str, Enum):
    PENDING = "pending"
    SEARCHING = "searching"
    LLM_DECIDING = "llm_deciding"
    AMBIGUOUS = "ambiguous"
    DECOMPOSING = "decomposing"
    MATCHED = "matched"
    CALCULATED = "calculated"
    ERROR = "error"


class DecisionType(str, Enum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"
    DECOMPOSE = "decompose"


# ---------------------------------------------------------------------------
# Input rows (from Excel template or manual entry)
# ---------------------------------------------------------------------------

class InputRowCreate(BaseModel):
    scope: Optional[str] = None
    kategorie: Optional[str] = None
    unterkategorie: Optional[str] = None
    bezeichnung: str
    produktinformationen: Optional[str] = None
    referenzeinheit: str
    region: Optional[str] = None
    referenzjahr: Optional[str] = None


class InputRowUpdate(BaseModel):
    scope: Optional[str] = None
    kategorie: Optional[str] = None
    unterkategorie: Optional[str] = None
    bezeichnung: Optional[str] = None
    produktinformationen: Optional[str] = None
    referenzeinheit: Optional[str] = None
    region: Optional[str] = None
    referenzjahr: Optional[str] = None


class InputRow(InputRowCreate):
    id: int
    job_id: str
    row_index: int
    bezeichnung_norm: Optional[str] = None
    produktinfo_norm: Optional[str] = None
    region_norm: str = "GLO"
    status: RowStatus = RowStatus.PENDING
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# ecoinvent dataset row
# ---------------------------------------------------------------------------

class DatasetRow(BaseModel):
    id: int
    uuid: str
    activity_name: str
    geography: str
    product_name: str
    unit: str
    amount: int
    biogenic_kg: float
    total_excl_bio_kg: float
    is_market: bool


# ---------------------------------------------------------------------------
# Search / retrieval
# ---------------------------------------------------------------------------

class CandidateResult(BaseModel):
    dataset: DatasetRow
    bm25_rank: Optional[int] = None
    embedding_rank: Optional[int] = None
    fused_score: float = 0.0
    region_priority: int = 3  # 0=exact, 1=GLO, 2=RoW, 3=other


class RetrievalResult(BaseModel):
    force_decompose: bool = False
    force_decompose_reason: Optional[str] = None
    candidates: list[CandidateResult] = []
    query_used: Optional[str] = None


# ---------------------------------------------------------------------------
# LLM decision
# ---------------------------------------------------------------------------

class AmbiguousCandidate(BaseModel):
    uuid: str
    activity_name: str
    product_name: str
    geography: str
    unit: str
    why_short: str
    rank: int


class DecompComponent(BaseModel):
    component_label: str
    assumed_quantity: float
    assumed_unit: str
    search_query_text: str


class LLMDecision(BaseModel):
    type: DecisionType
    selected_uuid: Optional[str] = None
    candidates: Optional[list[AmbiguousCandidate]] = None
    components: Optional[list[DecompComponent]] = None
    assumptions: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------

class CalcResult(BaseModel):
    uuid: str
    activity_name: str
    geography: str
    quantity: float
    unit: str
    biogenic_kg: float
    total_excl_bio_kg: float
    biogenic_t: float
    total_excl_bio_t: float
    unit_conversion: Optional[dict] = None  # {"factor": 36.0, "explanation": "..."}


class ResolvedComponent(BaseModel):
    component_label: str
    assumed_quantity: float
    assumed_unit: str
    matched_uuid: str
    matched_activity: str
    matched_geography: str
    scaled_biogenic_kg: float
    scaled_total_kg: float


class DecompCalcResult(BaseModel):
    components: list[ResolvedComponent]
    assumptions: list[str]
    biogenic_kg_sum: float
    total_excl_bio_kg_sum: float
    biogenic_t: float
    total_excl_bio_t: float


# ---------------------------------------------------------------------------
# Output / results
# ---------------------------------------------------------------------------

class RowResult(BaseModel):
    input_row_id: int
    decision_type: DecisionType
    selected_uuid: Optional[str] = None
    candidates_json: Optional[list[AmbiguousCandidate]] = None
    components_json: Optional[list[ResolvedComponent]] = None
    biogenic_t: Optional[str] = None
    common_t: Optional[str] = None
    beschreibung: Optional[str] = None
    quelle: Optional[str] = None
    detailed_calc: Optional[str] = None
    provenance_json: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    mode: ProcessingMode = ProcessingMode.AUTO


class Job(BaseModel):
    id: str
    created_at: str
    mode: ProcessingMode
    status: str
    total_rows: int
    done_rows: int


class JobProgress(BaseModel):
    job_id: str
    total: int
    pending: int
    processing: int
    done: int
    errors: int
    ambiguous: int
    rows: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    selected_uuid: str


class BatchResolveItem(BaseModel):
    row_id: int
    selected_uuid: str


class BatchResolveRequest(BaseModel):
    resolutions: list[BatchResolveItem]


class DecompositionApproval(BaseModel):
    components: list[DecompComponent]


# ---------------------------------------------------------------------------
# Process request
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    mode: ProcessingMode = ProcessingMode.AUTO


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class ProvenanceRecord(BaseModel):
    timestamp: str
    input_row: dict[str, Any]
    normalized_input: dict[str, Any]
    search_query: str
    candidates_count: int
    candidates_shown_to_llm: int
    llm_decision_type: str
    selected_uuids: list[str]
    quantities: list[float]
    formulas: list[str]
    biogenic_sum_kg: float
    total_sum_kg: float
    biogenic_t: str
    total_t: str
    llm_model: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    valid: bool
    error: Optional[str] = None
    data: Optional[Any] = None


class OutputTooLongError(Exception):
    def __init__(self, field: str, actual_length: int, max_length: int, message: str = ""):
        self.field = field
        self.actual_length = actual_length
        self.max_length = max_length
        if not message:
            message = (
                f"{field} exceeds {max_length} char limit: {actual_length} chars. "
                f"This is a blocking error."
            )
        super().__init__(message)
