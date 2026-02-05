"""CRUD endpoints for input rows."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from app.models import InputRowCreate, InputRowUpdate, ProcessingMode
from app.services.dataset_store import DatasetStore
from app.services.template_parser import normalize_input_row

router = APIRouter()


@router.post("/jobs")
def create_job(request: Request):
    """Create an empty job for manual row addition."""
    store: DatasetStore = request.app.state.store
    job_id = str(uuid.uuid4())
    store.create_job(job_id, ProcessingMode.AUTO.value, 0)
    return {"job_id": job_id, "status": "created"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/rows")
def get_rows(job_id: str, request: Request):
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = store.get_input_rows(job_id)
    # Attach results if available
    for row in rows:
        result = store.get_row_result(row["id"])
        row["result"] = result

    return {"job_id": job_id, "rows": rows}


@router.post("/jobs/{job_id}/rows")
def add_row(job_id: str, body: InputRowCreate, request: Request):
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get current max row_index
    existing = store.get_input_rows(job_id)
    next_index = max((r["row_index"] for r in existing), default=-1) + 1

    norm = normalize_input_row(body)
    row_data = body.dict()
    row_data.update(norm)
    row_id = store.insert_input_row(job_id, next_index, row_data)

    # Update job total
    store.connect().execute(
        "UPDATE processing_jobs SET total_rows = total_rows + 1 WHERE id = ?",
        (job_id,),
    )
    store.connect().commit()

    # Return the full row with status
    created_row = store.get_input_row(row_id)
    return created_row


@router.put("/jobs/{job_id}/rows/{row_id}")
def update_row(job_id: str, row_id: int, body: InputRowUpdate, request: Request):
    store: DatasetStore = request.app.state.store
    existing = store.get_input_row(row_id)
    if existing is None or existing["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Row not found")

    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        # Recompute normalized fields if relevant fields changed
        if any(k in updates for k in ["bezeichnung", "produktinformationen", "region"]):
            merged = {**existing, **updates}
            row_obj = InputRowCreate(
                bezeichnung=merged.get("bezeichnung", ""),
                referenzeinheit=merged.get("referenzeinheit", ""),
                produktinformationen=merged.get("produktinformationen"),
                region=merged.get("region"),
            )
            norm = normalize_input_row(row_obj)
            updates.update(norm)

        # Reset status to pending when edited
        updates["status"] = "pending"
        updates["error_message"] = None
        store.update_input_row_fields(row_id, updates)

    return store.get_input_row(row_id)


@router.delete("/jobs/{job_id}/rows/{row_id}")
def delete_row(job_id: str, row_id: int, request: Request):
    store: DatasetStore = request.app.state.store
    existing = store.get_input_row(row_id)
    if existing is None or existing["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Row not found")

    store.delete_input_row(row_id)

    # Update job total
    store.connect().execute(
        "UPDATE processing_jobs SET total_rows = total_rows - 1 WHERE id = ?",
        (job_id,),
    )
    store.connect().commit()

    return {"status": "deleted", "row_id": row_id}
