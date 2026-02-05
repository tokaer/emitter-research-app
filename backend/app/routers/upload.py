"""Upload Excel template endpoint."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Request, UploadFile, HTTPException

from app.models import ProcessingMode
from app.services.dataset_store import DatasetStore
from app.services.template_parser import normalize_input_row, parse_template

router = APIRouter()


@router.post("/upload")
async def upload_template(request: Request, file: UploadFile = File(...)):
    """Upload an .xlsx template file, parse it, and create a processing job.

    Returns the job_id and all parsed input rows.
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        parsed_rows = parse_template(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    store: DatasetStore = request.app.state.store
    job_id = str(uuid.uuid4())
    store.create_job(job_id, ProcessingMode.AUTO.value, len(parsed_rows))

    result_rows = []
    for idx, row in enumerate(parsed_rows):
        norm = normalize_input_row(row)
        row_data = row.dict()
        row_data.update(norm)
        row_id = store.insert_input_row(job_id, idx, row_data)
        # Get the full row from DB including status
        created_row = store.get_input_row(row_id)
        result_rows.append(created_row)

    return {
        "job_id": job_id,
        "total_rows": len(parsed_rows),
        "rows": result_rows,
    }
