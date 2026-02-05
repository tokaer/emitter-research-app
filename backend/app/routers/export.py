"""Export endpoints: download results as Excel."""
from __future__ import annotations

import io
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from app.services.dataset_store import DatasetStore

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/jobs/{job_id}/export")
def export_results(job_id: str, request: Request):
    """Export all results as an Excel file."""
    store: DatasetStore = request.app.state.store
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    rows = store.get_input_rows(job_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    # Header row
    headers = [
        "Row",
        "Scope",
        "Kategorie",
        "ggf. Unterkategorie",
        "Bezeichnung",
        "Produktinformationen",
        "Referenzeinheit",
        "ggf. Region",
        "Referenzjahr",
        "Status",
        "Biogene Emissionen [t CO2-Eq]",
        "Common Factor [t CO2-Eq]",
        "Beschreibung",
        "Quelle",
        "Detailed calculation",
        "Error",
    ]
    ws.append(headers)

    for row in rows:
        result = store.get_row_result(row["id"])
        ws.append([
            row["row_index"] + 1,
            row.get("scope", ""),
            row.get("kategorie", ""),
            row.get("unterkategorie", ""),
            row.get("bezeichnung", ""),
            row.get("produktinformationen", ""),
            row.get("referenzeinheit", ""),
            row.get("region", ""),
            row.get("referenzjahr", ""),
            row.get("status", ""),
            result.get("biogenic_t", "") if result else "",
            result.get("common_t", "") if result else "",
            result.get("beschreibung", "") if result else "",
            result.get("quelle", "") if result else "",
            result.get("detailed_calc", "") if result else "",
            row.get("error_message", ""),
        ])

    # Auto-width columns
    for col in ws.columns:
        max_length = 0
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        adjusted_width = min(max_length + 2, 60)
        ws.column_dimensions[col[0].column_letter].width = adjusted_width

    # Provenance sheet
    ws_prov = wb.create_sheet("Provenance")
    ws_prov.append(["Row", "Bezeichnung", "Provenance JSON"])
    for row in rows:
        result = store.get_row_result(row["id"])
        prov = ""
        if result and result.get("provenance_json"):
            prov = result["provenance_json"]
        ws_prov.append([
            row["row_index"] + 1,
            row.get("bezeichnung", ""),
            prov,
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=emitter_results_{job_id[:8]}.xlsx"
        },
    )


@router.get("/jobs/{job_id}/rows/{row_id}/provenance")
def get_provenance(job_id: str, row_id: int, request: Request):
    """Get full provenance JSON for a single row."""
    store: DatasetStore = request.app.state.store
    result = store.get_row_result(row_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found for this row")

    prov = result.get("provenance_json")
    if prov:
        try:
            return json.loads(prov)
        except json.JSONDecodeError:
            return {"raw": prov}
    return {"message": "No provenance data available"}
