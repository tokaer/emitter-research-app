"""Processing endpoints: start batch processing, check progress."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import settings
from app.models import (
    DecisionType,
    OutputTooLongError,
    ProcessRequest,
    RowStatus,
)
from app.services.calculator import Calculator, format_number
from app.services.candidate_retriever import CandidateRetriever, map_unit
from app.services.dataset_store import DatasetStore
from app.services.embedding_builder import EmbeddingIndex
from app.services.llm_orchestrator import LLMOrchestrator
from app.services.output_builder import (
    build_beschreibung_decomp,
    build_beschreibung_match,
    build_detailed_calculation_decomp,
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


def process_row(
    row: dict,
    store: DatasetStore,
    retriever: CandidateRetriever,
    llm: LLMOrchestrator,
    calculator: Calculator,
    validator: Validator,
    mode: str,
):
    """Process a single input row through the full pipeline."""
    row_id = row["id"]

    try:
        # Step A: Already normalized during upload/edit
        store.update_input_row_status(row_id, RowStatus.SEARCHING.value)

        # Step B: Candidate Retrieval
        retrieval = retriever.retrieve(
            bezeichnung=row.get("bezeichnung_norm") or row["bezeichnung"],
            produktinfo=row.get("produktinfo_norm") or row.get("produktinformationen") or "",
            referenzeinheit=row["referenzeinheit"],
            region=row.get("region_norm") or row.get("region"),
            top_k=settings.candidate_top_k,
            scope=row.get("scope"),
            kategorie=row.get("kategorie"),
        )

        # Step C: LLM Decision
        store.update_input_row_status(row_id, RowStatus.LLM_DECIDING.value)

        if retrieval.force_decompose:
            # Unit not in DB or no candidates -> force decomposition
            decision = llm.request_decomposition(
                input_row=row,
                reason=retrieval.force_decompose_reason or "No candidates found",
            )
        else:
            decision = llm.decide(
                input_row=row,
                candidates=retrieval.candidates,
            )

        # Handle the three decision types
        if decision.type == DecisionType.MATCH:
            _handle_match(row, decision, store, calculator, validator, llm)

        elif decision.type == DecisionType.AMBIGUOUS:
            _handle_ambiguous(row, decision, store, mode, llm, calculator, validator)

        elif decision.type == DecisionType.DECOMPOSE:
            _handle_decompose(
                row, decision, store, retriever, llm, calculator, validator
            )

    except OutputTooLongError as e:
        store.update_input_row_status(row_id, RowStatus.ERROR.value, str(e))
        logger.error(f"Row {row_id}: Output too long: {e}")

    except Exception as e:
        store.update_input_row_status(row_id, RowStatus.ERROR.value, str(e))
        logger.exception(f"Row {row_id}: Processing failed: {e}")


def _handle_match(
    row: dict,
    decision,
    store: DatasetStore,
    calculator: Calculator,
    validator: Validator,
    llm: LLMOrchestrator,
):
    """Handle a direct match decision."""
    row_id = row["id"]
    uuid = decision.selected_uuid

    # Validate
    v_uuid = validator.validate_uuid(uuid)
    if not v_uuid.valid:
        store.update_input_row_status(row_id, RowStatus.ERROR.value, v_uuid.error)
        return

    v_market = validator.validate_activity_not_market(uuid)
    if not v_market.valid:
        store.update_input_row_status(row_id, RowStatus.ERROR.value, v_market.error)
        return

    # Check if unit conversion is needed
    dataset = store.lookup_by_uuid(uuid)
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
                f"Row {row_id}: Unit conversion FAILED ({reference_unit} -> {dataset.unit}): {e}.",
                exc_info=True
            )
            store.update_input_row_status(
                row_id,
                RowStatus.ERROR.value,
                f"Unit conversion failed: {reference_unit} -> {dataset.unit}. Error: {str(e)}"
            )
            return
    else:
        logger.info(f"Row {row_id}: Units match - no conversion needed")

    # Calculate
    calc = calculator.calculate_match(uuid, quantity, unit_conversion)

    # Build output strings
    beschreibung = build_beschreibung_match(row, calc)
    validate_beschreibung(beschreibung)
    quelle = build_quelle([uuid])
    detailed = build_detailed_calculation_match(row, calc)

    # Build provenance
    provenance = _build_provenance(row, "match", [uuid], [quantity], calc)

    # Save result
    store.save_row_result({
        "input_row_id": row_id,
        "decision_type": DecisionType.MATCH.value,
        "selected_uuid": uuid,
        "biogenic_t": format_number(calc.biogenic_t),
        "common_t": format_number(calc.total_excl_bio_t),
        "beschreibung": beschreibung,
        "quelle": quelle,
        "detailed_calc": detailed,
        "provenance_json": json.dumps(provenance, ensure_ascii=False),
    })
    store.update_input_row_status(row_id, RowStatus.CALCULATED.value)


def _handle_ambiguous(
    row: dict,
    decision,
    store: DatasetStore,
    mode: str,
    llm: LLMOrchestrator,
    calculator: Calculator,
    validator: Validator,
):
    """Handle an ambiguous decision."""
    row_id = row["id"]

    if mode == "auto" and decision.candidates:
        # In auto mode, pick the first (highest-ranked) candidate and process it as match
        top = decision.candidates[0]
        from app.models import LLMDecision
        match_decision = LLMDecision(
            type=DecisionType.MATCH,
            selected_uuid=top.uuid,
        )
        # Process as match with unit conversion
        _handle_match(row, match_decision, store, calculator, validator, llm)
    else:
        # In review mode, save candidates for user selection
        store.save_row_result({
            "input_row_id": row_id,
            "decision_type": DecisionType.AMBIGUOUS.value,
            "candidates_json": json.dumps(
                [c.dict() for c in decision.candidates], ensure_ascii=False
            ),
        })
        store.update_input_row_status(row_id, RowStatus.AMBIGUOUS.value)


def _handle_decompose(
    row: dict,
    decision,
    store: DatasetStore,
    retriever: CandidateRetriever,
    llm: LLMOrchestrator,
    calculator: Calculator,
    validator: Validator,
):
    """Handle a decomposition decision with sub-searches for each component."""
    row_id = row["id"]
    store.update_input_row_status(row_id, RowStatus.DECOMPOSING.value)

    resolved_components = []

    for comp in decision.components:
        # Sub-search for each component
        sub_retrieval = retriever.retrieve(
            bezeichnung=comp.search_query_text,
            produktinfo="",
            referenzeinheit=comp.assumed_unit,
            region=row.get("region_norm") or "GLO",
            top_k=20,
        )

        if sub_retrieval.force_decompose or not sub_retrieval.candidates:
            store.update_input_row_status(
                row_id,
                RowStatus.ERROR.value,
                f"Component '{comp.component_label}' ({comp.search_query_text}): "
                f"no candidates found (unit: {comp.assumed_unit})",
            )
            return

        # LLM selects among component candidates (no further decomposition allowed)
        comp_input = {
            "bezeichnung": comp.search_query_text,
            "produktinformationen": "",
            "referenzeinheit": comp.assumed_unit,
            "region_norm": row.get("region_norm") or "GLO",
        }
        comp_decision = llm.decide(comp_input, sub_retrieval.candidates, allow_decompose=False)

        if comp_decision.type == DecisionType.MATCH:
            # Validate
            v = validator.validate_uuid(comp_decision.selected_uuid)
            if not v.valid:
                store.update_input_row_status(row_id, RowStatus.ERROR.value, v.error)
                return
            resolved_components.append({
                "component_label": comp.component_label,
                "assumed_quantity": comp.assumed_quantity,
                "assumed_unit": comp.assumed_unit,
                "matched_uuid": comp_decision.selected_uuid,
            })
        elif comp_decision.type == DecisionType.AMBIGUOUS:
            # For components, auto-select top candidate
            if comp_decision.candidates:
                top = comp_decision.candidates[0]
                resolved_components.append({
                    "component_label": comp.component_label,
                    "assumed_quantity": comp.assumed_quantity,
                    "assumed_unit": comp.assumed_unit,
                    "matched_uuid": top.uuid,
                })
            else:
                store.update_input_row_status(
                    row_id,
                    RowStatus.ERROR.value,
                    f"Component '{comp.component_label}': ambiguous but no candidates returned",
                )
                return
        else:
            # Decomposition requested for a component - not allowed (max 1 level)
            store.update_input_row_status(
                row_id,
                RowStatus.ERROR.value,
                f"Component '{comp.component_label}': nested decomposition not supported",
            )
            return

    # Validate: Sum of component quantities should equal 1 reference unit
    # Group by unit and check if they sum correctly
    ref_unit = row.get("referenzeinheit", "")
    mapped_ref_unit = map_unit(ref_unit) or ref_unit

    # Check if all components use the same unit as reference (or compatible)
    unit_mismatches = []
    for comp in resolved_components:
        comp_unit_norm = comp["assumed_unit"].strip().lower()
        ref_unit_norm = mapped_ref_unit.strip().lower()
        if comp_unit_norm != ref_unit_norm:
            unit_mismatches.append(f"{comp['component_label']}: {comp['assumed_unit']} vs {ref_unit}")

    if not unit_mismatches:
        # All components have same unit - check if sum equals 1
        total_quantity = sum(comp["assumed_quantity"] for comp in resolved_components)
        if not (0.95 <= total_quantity <= 1.05):
            # Build component list for error message
            comp_list = [f"{c['component_label']}: {c['assumed_quantity']}" for c in resolved_components]
            store.update_input_row_status(
                row_id,
                RowStatus.ERROR.value,
                f"Decomposition sum validation failed: Components sum to {total_quantity:.3f} {mapped_ref_unit}, "
                f"but should be exactly 1 {ref_unit}. "
                f"Component quantities: {comp_list}",
            )
            logger.warning(
                f"Row {row_id}: Decomposition sum {total_quantity:.3f} != 1.0 for unit {ref_unit}. "
                f"Components: {resolved_components}"
            )
            return

    # Calculate totals
    decomp_result = calculator.calculate_decomposition(
        resolved_components,
        assumptions=decision.assumptions,
    )

    # Build output
    uuids = [c.matched_uuid for c in decomp_result.components]
    beschreibung = build_beschreibung_decomp(row, decomp_result)
    validate_beschreibung(beschreibung)
    quelle = build_quelle(uuids)
    detailed = build_detailed_calculation_decomp(row, decomp_result)

    # Build provenance
    quantities = [c.assumed_quantity for c in decomp_result.components]
    provenance = _build_provenance(row, "decompose", uuids, quantities, decomp_result)

    store.save_row_result({
        "input_row_id": row_id,
        "decision_type": DecisionType.DECOMPOSE.value,
        "selected_uuid": uuids[0] if uuids else None,
        "components_json": json.dumps(
            [c.dict() for c in decomp_result.components], ensure_ascii=False
        ),
        "biogenic_t": format_number(decomp_result.biogenic_t),
        "common_t": format_number(decomp_result.total_excl_bio_t),
        "beschreibung": beschreibung,
        "quelle": quelle,
        "detailed_calc": detailed,
        "provenance_json": json.dumps(provenance, ensure_ascii=False),
    })
    store.update_input_row_status(row_id, RowStatus.CALCULATED.value)


def _build_provenance(row, decision_type, uuids, quantities, calc_result) -> dict:
    """Build provenance JSON record."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_row": {
            k: row.get(k)
            for k in [
                "bezeichnung", "produktinformationen", "referenzeinheit",
                "region", "referenzjahr",
            ]
        },
        "normalized_input": {
            k: row.get(k)
            for k in ["bezeichnung_norm", "produktinfo_norm", "region_norm"]
        },
        "llm_decision_type": decision_type,
        "selected_uuids": uuids,
        "quantities": quantities,
        "llm_model": settings.llm_model,
    }


def _process_all_rows(
    job_id: str,
    mode: str,
    store: DatasetStore,
    retriever: CandidateRetriever,
    embedding_index: EmbeddingIndex,
):
    """Background task to process all pending rows in a job."""
    llm = LLMOrchestrator(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
    )
    calculator = Calculator(store)
    validator = Validator(store)

    store.update_job_status(job_id, "processing")
    rows = store.get_input_rows(job_id)
    pending = [r for r in rows if r["status"] == "pending"]

    done = 0
    for row in pending:
        process_row(row, store, retriever, llm, calculator, validator, mode)
        done += 1
        store.update_job_status(job_id, "processing", done_rows=done)

    # Check if all rows are done
    rows = store.get_input_rows(job_id)
    all_done = all(r["status"] in ("calculated", "ambiguous", "error") for r in rows)
    if all_done:
        store.update_job_status(job_id, "completed", done_rows=len(rows))
    else:
        store.update_job_status(job_id, "completed", done_rows=done)


@router.post("/jobs/{job_id}/process")
async def start_processing(
    job_id: str,
    body: ProcessRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY not configured. Set it in backend/.env",
        )

    background_tasks.add_task(
        _process_all_rows,
        job_id,
        body.mode.value,
        store,
        request.app.state.retriever,
        request.app.state.embedding_index,
    )

    return {"status": "started", "job_id": job_id, "mode": body.mode.value}


@router.get("/jobs/{job_id}/progress")
def get_progress(job_id: str, request: Request):
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = store.get_input_rows(job_id)
    statuses = {
        "pending": 0,
        "searching": 0,
        "llm_deciding": 0,
        "ambiguous": 0,
        "decomposing": 0,
        "matched": 0,
        "calculated": 0,
        "error": 0,
    }
    row_summaries = []
    for r in rows:
        status = r["status"]
        statuses[status] = statuses.get(status, 0) + 1
        result = store.get_row_result(r["id"])
        row_summaries.append({
            "id": r["id"],
            "row_index": r["row_index"],
            "bezeichnung": r["bezeichnung"],
            "status": status,
            "error_message": r.get("error_message"),
            "has_result": result is not None,
            "biogenic_t": result.get("biogenic_t") if result else None,
            "common_t": result.get("common_t") if result else None,
        })

    processing = statuses["searching"] + statuses["llm_deciding"] + statuses["decomposing"]
    done = statuses["calculated"] + statuses["ambiguous"] + statuses["error"]

    return {
        "job_id": job_id,
        "job_status": job["status"],
        "total": len(rows),
        "pending": statuses["pending"],
        "processing": processing,
        "done": done,
        "calculated": statuses["calculated"],
        "ambiguous": statuses["ambiguous"],
        "errors": statuses["error"],
        "rows": row_summaries,
    }
