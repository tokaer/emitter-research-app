"""Ambiguity resolution endpoints."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.models import (
    BatchResolveRequest,
    DecisionType,
    ResolveRequest,
    RowStatus,
)
from app.services.calculator import Calculator, format_number
from app.services.candidate_retriever import map_unit
from app.services.dataset_store import DatasetStore
from app.services.llm_orchestrator import LLMOrchestrator
from app.services.output_builder import (
    build_beschreibung_match,
    build_detailed_calculation_match,
    build_quelle,
    validate_beschreibung,
)
from app.services.validator import Validator

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_llm(request: Request) -> LLMOrchestrator:
    if not hasattr(request.app.state, "_llm") or request.app.state._llm is None:
        request.app.state._llm = LLMOrchestrator(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
        )
    return request.app.state._llm


def _resolve_single(
    row_id: int,
    selected_uuid: str,
    store: DatasetStore,
    llm: LLMOrchestrator,
):
    """Resolve a single ambiguous row by selecting a UUID."""
    row = store.get_input_row(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Row {row_id} not found")

    if row["status"] != "ambiguous":
        raise HTTPException(
            status_code=400,
            detail=f"Row {row_id} is not in ambiguous state (current: {row['status']})",
        )

    # Validate UUID
    validator = Validator(store)
    v = validator.validate_uuid(selected_uuid)
    if not v.valid:
        raise HTTPException(status_code=400, detail=v.error)

    v_market = validator.validate_activity_not_market(selected_uuid)
    if not v_market.valid:
        raise HTTPException(status_code=400, detail=v_market.error)

    # Check if unit conversion is needed
    dataset = store.lookup_by_uuid(selected_uuid)
    reference_unit = row["referenzeinheit"]
    mapped_ref_unit = map_unit(reference_unit) or reference_unit
    quantity = 1.0
    unit_conversion = None

    # Normalize units for comparison (case-insensitive)
    dataset_unit_norm = dataset.unit.strip().lower()
    ref_unit_norm = mapped_ref_unit.strip().lower()

    logger.info(
        f"Row {row_id}: Unit check - Dataset unit: '{dataset.unit}' (norm: '{dataset_unit_norm}'), "
        f"Reference unit: '{reference_unit}' (mapped: '{mapped_ref_unit}', norm: '{ref_unit_norm}')"
    )

    if dataset_unit_norm != ref_unit_norm:
        # Units differ - need conversion
        logger.info(
            f"Row {row_id}: Units differ - requesting conversion from {reference_unit} to {dataset.unit}"
        )
        try:
            product_context = f"{row.get('bezeichnung', '')} ({row.get('produktinformationen', '')})"
            unit_conversion = llm.convert_unit(
                reference_unit=reference_unit,
                dataset_unit=dataset.unit,
                product_context=product_context,
            )
            quantity = unit_conversion["conversion_factor"]
            logger.info(
                f"Row {row_id}: Unit conversion successful - factor: {quantity}, "
                f"explanation: {unit_conversion['explanation']}"
            )
        except Exception as e:
            logger.error(
                f"Row {row_id}: Unit conversion FAILED ({reference_unit} -> {dataset.unit}): {e}. "
                f"Using quantity=1.0 (INCORRECT!)",
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail=f"Unit conversion failed: {reference_unit} -> {dataset.unit}. Error: {str(e)}"
            )
    else:
        logger.info(f"Row {row_id}: Units match - no conversion needed")

    # Calculate
    calculator = Calculator(store)
    calc = calculator.calculate_match(selected_uuid, quantity, unit_conversion)

    # Build output
    beschreibung = build_beschreibung_match(row, calc)
    validate_beschreibung(beschreibung)
    quelle = build_quelle([selected_uuid])
    detailed = build_detailed_calculation_match(row, calc)

    # Update the existing result
    store.save_row_result({
        "input_row_id": row_id,
        "decision_type": DecisionType.MATCH.value,
        "selected_uuid": selected_uuid,
        "biogenic_t": format_number(calc.biogenic_t),
        "common_t": format_number(calc.total_excl_bio_t),
        "beschreibung": beschreibung,
        "quelle": quelle,
        "detailed_calc": detailed,
    })
    store.update_input_row_status(row_id, RowStatus.CALCULATED.value)

    return {
        "row_id": row_id,
        "status": "calculated",
        "selected_uuid": selected_uuid,
        "biogenic_t": format_number(calc.biogenic_t),
        "common_t": format_number(calc.total_excl_bio_t),
    }


@router.get("/jobs/{job_id}/ambiguities")
def get_ambiguities(job_id: str, request: Request):
    """Get all rows with ambiguous status and their candidate lists."""
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = store.get_ambiguous_rows(job_id)
    result = []
    for r in rows:
        candidates = []
        if r.get("candidates_json"):
            try:
                candidates = json.loads(r["candidates_json"])
            except json.JSONDecodeError:
                pass
        result.append({
            "id": r["id"],
            "row_index": r["row_index"],
            "bezeichnung": r["bezeichnung"],
            "produktinformationen": r.get("produktinformationen"),
            "referenzeinheit": r["referenzeinheit"],
            "region": r.get("region"),
            "candidates": candidates,
        })

    return {"job_id": job_id, "ambiguities": result}


@router.post("/jobs/{job_id}/rows/{row_id}/resolve")
def resolve_ambiguity(
    job_id: str,
    row_id: int,
    body: ResolveRequest,
    request: Request,
):
    """Resolve a single ambiguous row by selecting a UUID."""
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    llm = _get_llm(request)
    return _resolve_single(row_id, body.selected_uuid, store, llm)


@router.post("/jobs/{job_id}/resolve-batch")
def resolve_batch(
    job_id: str,
    body: BatchResolveRequest,
    request: Request,
):
    """Batch resolve multiple ambiguous rows."""
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    llm = _get_llm(request)
    results = []
    errors = []
    for item in body.resolutions:
        try:
            r = _resolve_single(item.row_id, item.selected_uuid, store, llm)
            results.append(r)
        except HTTPException as e:
            errors.append({"row_id": item.row_id, "error": e.detail})

    return {"resolved": len(results), "results": results, "errors": errors}
