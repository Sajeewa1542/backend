from datetime import datetime
from typing import Any, Dict, List, Optional

import pydantic
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .storage_manager import StorageManager, storage_manager


app = FastAPI(
    title="Hybrid Variation Evaluation API",
    description="Vercel-safe API surface for the variation evaluation backend",
    version="2.0.0-vercel",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


VARIATION_EVALUATION_MODES = {
    "TYPE1": "quantity_change",
    "TYPE2": "substitution",
    "TYPE3": "quantity_change",
    "TYPE4": "omission",
    "TYPE5": "additional_work",
    "TYPE6": "time_sequence_change",
}


def get_storage() -> StorageManager:
    return storage_manager


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _get_item_description(item: Optional[Dict[str, Any]], fallback: Optional[str]) -> str:
    item = _safe_dict(item)
    return (
        _normalize(fallback)
        or _normalize(item.get("description"))
        or _normalize(item.get("item_description"))
        or "Variation item"
    )


def _get_item_unit(item: Optional[Dict[str, Any]], fallback: Optional[str]) -> str:
    item = _safe_dict(item)
    return _normalize(fallback) or _normalize(item.get("unit")) or "unit"


def _get_item_rate(item: Optional[Dict[str, Any]]) -> Optional[float]:
    item = _safe_dict(item)
    for key in ("rate", "unit_rate", "price"):
        rate = _to_float(item.get(key), None)
        if rate is not None:
            return rate
    return None


def _build_cost_line(
    line_type: str,
    description: str,
    quantity: float,
    unit: str,
    rate: float,
    rate_source: str,
    rate_source_id: str,
    formula: str,
    amount: float,
) -> Dict[str, Any]:
    return {
        "line_type": line_type,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "rate": rate,
        "rate_source": rate_source,
        "rate_source_id": rate_source_id,
        "formula": formula,
        "amount": amount,
        "used_rate_source": {
            "source_type": rate_source or "confirmed",
            "source_file": "",
            "item_reference": rate_source_id,
            "description": description,
            "unit": unit,
            "rate": rate,
            "confidence": "Human confirmed",
        },
    }


def _evaluate_confirmed_variation(project: Dict[str, Any], request_data: Dict[str, Any], storage: StorageManager) -> Dict[str, Any]:
    if not request_data.get("human_confirmed"):
        raise ValueError("human_confirmed must be true before evaluation")

    project_id_value = request_data.get("project_id") or project.get("id")
    if project_id_value is None:
        raise ValueError("project_id is required")
    project_id = int(project_id_value)
    variation_type = _normalize(request_data.get("variation_type")).upper()
    evaluation_mode = _normalize(request_data.get("evaluation_mode")).lower()
    if not evaluation_mode:
        evaluation_mode = VARIATION_EVALUATION_MODES.get(variation_type, "quantity_change")

    original_ref = _normalize(request_data.get("original_boq_item_ref"))
    replacement_ref = _normalize(request_data.get("replacement_item_ref"))
    original_boq = storage.get_boq_item(project_id, original_ref) if original_ref else None
    replacement_boq = storage.get_boq_item(project_id, replacement_ref) if replacement_ref else None

    original_description = _get_item_description(original_boq, request_data.get("original_description"))
    replacement_description = _get_item_description(replacement_boq, request_data.get("replacement_description"))
    unit = _get_item_unit(original_boq or replacement_boq, request_data.get("unit"))

    original_quantity = _to_float(request_data.get("original_quantity"), None)
    new_quantity = _to_float(request_data.get("new_quantity"), None)
    replacement_quantity = _to_float(request_data.get("replacement_quantity"), None)
    confirmed_rate = _to_float(request_data.get("confirmed_rate"), None)
    original_rate = _to_float(request_data.get("original_rate"), None) or _get_item_rate(original_boq)
    replacement_rate = confirmed_rate if confirmed_rate is not None else _get_item_rate(replacement_boq)
    confirmed_rate_source = _normalize(request_data.get("confirmed_rate_source")) or "confirmed"
    confirmed_rate_source_id = _normalize(request_data.get("confirmed_rate_source_id")) or original_ref or replacement_ref

    cost_lines: List[Dict[str, Any]] = []
    formula_summary: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []

    if evaluation_mode == "quantity_change":
        rate = confirmed_rate if confirmed_rate is not None else original_rate
        if original_quantity is None or new_quantity is None or rate is None:
            errors.append("quantity_change requires original_quantity, new_quantity, and confirmed_rate or BOQ rate")
        else:
            quantity = new_quantity - original_quantity
            amount = quantity * rate
            formula = f"({new_quantity} - {original_quantity}) x {rate}"
            cost_lines.append(_build_cost_line("quantity_change", original_description, quantity, unit, rate, confirmed_rate_source, confirmed_rate_source_id, formula, amount))
            formula_summary.append(f"Quantity change: {formula} = {amount}")

    elif evaluation_mode == "omission" or variation_type == "TYPE4":
        rate = confirmed_rate if confirmed_rate is not None else original_rate
        if original_quantity is None or rate is None:
            errors.append("omission requires original_quantity and confirmed_rate or BOQ rate")
        else:
            amount = (0 - original_quantity) * rate
            formula = f"(0 - {original_quantity}) x {rate}"
            cost_lines.append(_build_cost_line("omission", original_description, original_quantity, unit, rate, confirmed_rate_source, confirmed_rate_source_id, formula, amount))
            formula_summary.append(f"Omission: {formula} = {amount}")

    elif evaluation_mode == "substitution" or variation_type == "TYPE2":
        if replacement_quantity is None:
            replacement_quantity = original_quantity
        if original_quantity is None or replacement_quantity is None or original_rate is None or replacement_rate is None:
            errors.append("substitution requires quantities, original_rate, and confirmed replacement rate")
        else:
            omission_amount = (0 - original_quantity) * original_rate
            addition_amount = replacement_quantity * replacement_rate
            omission_formula = f"(0 - {original_quantity}) x {original_rate}"
            addition_formula = f"{replacement_quantity} x {replacement_rate}"
            cost_lines.append(_build_cost_line("omission", original_description, original_quantity, unit, original_rate, "BOQ", original_ref, omission_formula, omission_amount))
            cost_lines.append(_build_cost_line("addition", replacement_description, replacement_quantity, unit, replacement_rate, confirmed_rate_source, confirmed_rate_source_id, addition_formula, addition_amount))
            formula_summary.append(f"Substitution omission: {omission_formula} = {omission_amount}")
            formula_summary.append(f"Substitution addition: {addition_formula} = {addition_amount}")

    elif evaluation_mode == "additional_work" or variation_type == "TYPE5":
        quantity = new_quantity if new_quantity is not None else replacement_quantity
        rate = confirmed_rate if confirmed_rate is not None else replacement_rate
        if quantity is None or rate is None:
            errors.append("additional_work requires quantity and confirmed_rate")
        else:
            amount = quantity * rate
            formula = f"{quantity} x {rate}"
            cost_lines.append(_build_cost_line("addition", replacement_description or original_description, quantity, unit, rate, confirmed_rate_source, confirmed_rate_source_id, formula, amount))
            formula_summary.append(f"Additional work: {formula} = {amount}")

    else:
        errors.append(f"unsupported evaluation_mode: {evaluation_mode}")

    if not request_data.get("engineer_instruction_ref"):
        warnings.append("Missing Engineer's Instruction warning")
    if confirmed_rate_source.lower() in {"bsr", "hsr", "quotation"} and not request_data.get("supporting_documents"):
        errors.append("external rate source claimed but no supporting document reference provided")
    if evaluation_mode != "additional_work" and not original_ref:
        errors.append("BOQ reference missing")

    total_cost_impact = sum(float(line.get("amount", 0.0)) for line in cost_lines)

    return {
        "cost_lines": cost_lines,
        "total_cost_impact": total_cost_impact,
        "time_impact": {
            "eot_days": 0,
            "manual_required": bool(request_data.get("confirmed_activity_ref") or request_data.get("confirmed_productivity")),
            "message": "Serverless Vercel adapter does not run CPM/time-impact calculation.",
        },
        "validation": {
            "valid": not errors,
            "warnings": warnings,
            "errors": errors,
        },
        "formula_summary": formula_summary,
        "assumptions": ["Evaluated by Vercel-safe deterministic adapter."],
        "manual_confirmation_required": bool(errors),
    }


def _unsupported_serverless_endpoint(name: str) -> Dict[str, str]:
    return {
        "status": "unsupported_on_vercel",
        "endpoint": name,
        "message": "This endpoint needs persistent file storage, long-running processing, or native OCR/PDF dependencies. Deploy the full backend on Render/Railway/Fly.io, or move files to Blob storage and split processing into jobs.",
    }


class ProjectCreateRequest(pydantic.BaseModel):
    name: str
    boq_filename: Optional[str] = None
    rate_breakdown_filename: Optional[str] = None
    schedule_filename: Optional[str] = None


class ConfirmEvaluateRequest(pydantic.BaseModel):
    project_id: int
    session_id: int
    project_name: Optional[str] = None
    variation_type: str
    evaluation_mode: str
    original_boq_item_ref: Optional[str] = None
    replacement_item_ref: Optional[str] = None
    original_description: Optional[str] = None
    replacement_description: Optional[str] = None
    original_quantity: Optional[float] = None
    new_quantity: Optional[float] = None
    replacement_quantity: Optional[float] = None
    unit: Optional[str] = None
    original_rate: Optional[float] = None
    confirmed_rate: Optional[float] = None
    confirmed_rate_source: Optional[str] = None
    confirmed_rate_source_id: Optional[str] = None
    confirmed_activity_ref: Optional[str] = None
    confirmed_productivity: Optional[float] = None
    productivity_source: Optional[str] = None
    supporting_documents: List[Any] = pydantic.Field(default_factory=list)
    engineer_instruction_ref: Optional[str] = None
    original_drawing_ref: Optional[str] = None
    revised_drawing_ref: Optional[str] = None
    human_confirmed: bool = False


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "Hybrid Variation Evaluation API",
        "runtime": "vercel-serverless",
        "persistent_storage": False,
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/variation-types")
def get_variation_types():
    return {
        "variation_types": [
            {"id": 1, "code": "TYPE1", "name": "Quantity Changes", "evaluation_mode": "quantity_change"},
            {"id": 2, "code": "TYPE2", "name": "Quality/Characteristics Changes", "evaluation_mode": "substitution"},
            {"id": 3, "code": "TYPE3", "name": "Levels/Positions/Dimensions Changes", "evaluation_mode": "quantity_change"},
            {"id": 4, "code": "TYPE4", "name": "Omission of Work", "evaluation_mode": "omission"},
            {"id": 5, "code": "TYPE5", "name": "Additional Work/Plant/Materials", "evaluation_mode": "additional_work"},
            {"id": 6, "code": "TYPE6", "name": "Sequence/Timing Changes", "evaluation_mode": "time_sequence_change"},
        ]
    }


@app.post("/project/create")
def create_project(request: ProjectCreateRequest, storage: StorageManager = Depends(get_storage)):
    project = storage.create_project(
        name=request.name,
        boq_filename=request.boq_filename,
        rate_breakdown_filename=request.rate_breakdown_filename,
        schedule_filename=request.schedule_filename,
    )
    session = storage.create_session(project["id"], {"created_via": "vercel"})
    return {"status": "success", "project": project, "session": session}


@app.get("/projects")
def get_projects(storage: StorageManager = Depends(get_storage)):
    return {"projects": storage.get_projects()}


@app.post("/session/create")
def create_session(project_id: int, metadata: Optional[Dict[str, Any]] = None, storage: StorageManager = Depends(get_storage)):
    session = storage.create_session(project_id, metadata)
    if not session:
        raise HTTPException(status_code=404, detail="Project not found")
    return session


@app.get("/session/{project_id}/{session_id}")
def get_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    session = storage.get_session(project_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/session/{project_id}/{session_id}/close")
def close_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for session in project.get("sessions", []):
        if session.get("id") == session_id:
            session["status"] = "completed"
            session["updated_at"] = datetime.utcnow().isoformat()
            storage.update_project(project_id, {"sessions": project["sessions"]})
            return {"status": "success", "message": "Session closed"}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/variation/{project_id}/confirm-and-evaluate")
def confirm_and_evaluate(project_id: int, request: ConfirmEvaluateRequest, storage: StorageManager = Depends(get_storage)):
    if project_id != request.project_id:
        raise HTTPException(status_code=400, detail="project_id path/body mismatch")
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not storage.get_session(project_id, request.session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    request_data = request.model_dump()
    request_data["project_id"] = project_id

    try:
        evaluation_result = _evaluate_confirmed_variation(project, request_data, storage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    variation_data = {
        **request_data,
        **evaluation_result,
        "status": "Calculated" if evaluation_result.get("validation", {}).get("valid") else "Needs Review",
    }
    variation = storage.add_variation(project_id, request.session_id, variation_data)

    return {
        "status": "success",
        "variation_id": variation.get("id"),
        **evaluation_result,
    }


@app.get("/variation/{project_id}/{variation_id}")
def get_variation(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    return variation


@app.post("/variation/{project_id}/{variation_id}/status")
def update_variation_status(project_id: int, variation_id: int, status: str = Body(..., embed=True), storage: StorageManager = Depends(get_storage)):
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    updated = storage.update_variation(project_id, variation_id, {"status": status})
    return {"status": "success", "variation": updated}


@app.post("/upload/files")
def upload_files_on_vercel():
    return _unsupported_serverless_endpoint("/upload/files")


@app.post("/upload/quotation")
def upload_quotation_on_vercel():
    return _unsupported_serverless_endpoint("/upload/quotation")


@app.post("/upload/additional-files")
def upload_additional_files_on_vercel():
    return _unsupported_serverless_endpoint("/upload/additional-files")


@app.post("/chat")
def chat_on_vercel():
    return _unsupported_serverless_endpoint("/chat")


@app.post("/generate-pdf")
def generate_pdf_on_vercel():
    return _unsupported_serverless_endpoint("/generate-pdf")
