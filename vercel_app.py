import csv
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import pydantic
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from storage_manager import StorageManager, storage_manager


app = FastAPI(
    title="Hybrid Variation Evaluation API",
    description="Vercel-safe API surface for the variation evaluation backend",
    version="2.0.0-vercel",
)

origins = [
    "https://frontend-phi-eight-69.vercel.app",
    "http://localhost:5174",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


def get_storage() -> StorageManager:
    return storage_manager


def _load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_groq_client():
    _load_local_env()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.strip().lower() in {"your_groq_api_key_here", "replace_me", "changeme"}:
        return None
    try:
        from groq import Groq
    except Exception as exc:
        raise RuntimeError("groq package is not installed. Run: pip install -r requirements.txt") from exc
    return Groq(api_key=api_key)


def _runtime_dir(*parts: str) -> str:
    base_dir = "/tmp" if os.getenv("VERCEL") else "."
    path = os.path.join(base_dir, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def _runtime_file(*parts: str) -> str:
    directory = _runtime_dir(*parts[:-1])
    return os.path.join(directory, parts[-1])


def _safe_filename(filename: Optional[str]) -> str:
    name = Path(filename or "upload.bin").name
    return name.replace("\\", "_").replace("/", "_") or "upload.bin"


def _save_upload(file: UploadFile, folder: str, prefix: str = "") -> Dict[str, Any]:
    filename = _safe_filename(file.filename)
    stored_name = f"{prefix}{filename}" if prefix else filename
    file_path = os.path.join(folder, stored_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "filename": filename,
        "stored_name": stored_name,
        "file_path": file_path,
        "content_type": file.content_type,
        "size": os.path.getsize(file_path),
    }


def _read_csv_rows(file_path: str) -> List[Dict[str, str]]:
    encodings = ("utf-8-sig", "utf-8", "latin1")
    for encoding in encodings:
        try:
            with open(file_path, newline="", encoding=encoding) as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeDecodeError:
            continue
    return []


def _first_value(row: Dict[str, Any], *keys: str) -> Any:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_boq_csv(file_path: str) -> List[Dict[str, Any]]:
    items = []
    for row in _read_csv_rows(file_path):
        description = _first_value(row, "description", "item description", "work description", "item", "particulars")
        if not description:
            continue
        items.append({
            "item_number": _first_value(row, "item_number", "item no", "item no.", "item_ref", "item reference", "ref", "code"),
            "description": description,
            "unit": _first_value(row, "unit", "uom", "u/m"),
            "quantity": _to_float(_first_value(row, "quantity", "qty", "original quantity"), 0.0),
            "rate": _to_float(_first_value(row, "rate", "unit rate", "price"), 0.0),
        })
    return items


def _parse_rate_csv(file_path: str, source_file: str) -> List[Dict[str, Any]]:
    items = []
    for row in _read_csv_rows(file_path):
        description = _first_value(row, "description", "item description", "work description", "item", "particulars")
        rate = _to_float(_first_value(row, "rate", "unit rate", "price"), None)
        if not description or rate is None:
            continue
        items.append({
            "source_type": "rate_breakdown",
            "source_file": source_file,
            "item_reference": _first_value(row, "item_reference", "item ref", "item no", "ref", "code"),
            "description": description,
            "unit": _first_value(row, "unit", "uom", "u/m"),
            "rate": rate,
            "confidence_score": 0.75,
        })
    return items


def _parse_schedule_csv(file_path: str) -> List[Dict[str, Any]]:
    activities = []
    for row in _read_csv_rows(file_path):
        name = _first_value(row, "name", "activity", "activity name", "task", "task name", "description")
        if not name:
            continue
        activities.append({
            "activity_id": _first_value(row, "activity_id", "activity id", "task_id", "id", "uid"),
            "name": name,
            "duration": _to_float(_first_value(row, "duration", "duration_days", "days"), 0.0),
            "is_critical": str(_first_value(row, "is_critical", "critical") or "").strip().lower() in {"1", "true", "yes", "y"},
        })
    return activities


def _token_score(query: str, candidate: str) -> float:
    query_text = (query or "").lower()
    candidate_text = (candidate or "").lower()
    query_tokens = set(re.findall(r"[a-z0-9]+", query_text))
    candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate_text))
    if not query_tokens or not candidate_tokens:
        return 0.0

    overlap = len(query_tokens.intersection(candidate_tokens)) / max(1, len(candidate_tokens))
    sequence = SequenceMatcher(None, query_text, candidate_text).ratio()
    return round(max(overlap, sequence * 0.85), 4)


def _rank_boq_candidates(message: str, project: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    candidates = []
    for item in project.get("boq_items", []) or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("item_description") or "")
        score = _token_score(message, description)
        if score <= 0:
            continue
        item_ref = (
            item.get("item_number")
            or item.get("item_reference")
            or item.get("item_no")
            or item.get("item_ref")
            or item.get("code")
            or item.get("id")
        )
        candidates.append({
            "item_reference": str(item_ref) if item_ref is not None else None,
            "description": description,
            "unit": item.get("unit"),
            "rate": item.get("rate"),
            "quantity": item.get("quantity"),
            "similarity_score": score,
            "confidence_score": score,
            "source_type": "boq",
            "reason": "deterministic text match",
        })
    return sorted(candidates, key=lambda item: item.get("similarity_score", 0), reverse=True)[:limit]


def _rank_rate_candidates(message: str, project: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    candidates = []
    for item in project.get("rate_sources", []) or project.get("rate_breakdowns", []) or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "")
        score = _token_score(message, description)
        if score <= 0:
            continue
        candidate = {
            "id": item.get("id"),
            "source_type": item.get("source_type") or "rate_breakdown",
            "source_file": item.get("source_file"),
            "item_reference": item.get("item_reference"),
            "description": description,
            "unit": item.get("unit"),
            "rate": item.get("rate"),
            "confidence_score": max(score, _to_float(item.get("confidence_score"), 0.0) or 0.0),
            "reason": "deterministic text match",
        }
        candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.get("confidence_score", 0), reverse=True)[:limit]


def _rank_activity_candidates(message: str, project: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    candidates = []
    for item in project.get("activities", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("activity_name") or "")
        score = _token_score(message, name)
        if score <= 0:
            continue
        candidates.append({
            "activity_id": item.get("activity_id") or item.get("id") or item.get("task_id"),
            "name": name,
            "duration": item.get("duration"),
            "is_critical": item.get("is_critical") or item.get("critical"),
            "similarity_score": score,
            "confidence_score": score,
            "reason": "deterministic text match",
        })
    return sorted(candidates, key=lambda item: item.get("similarity_score", 0), reverse=True)[:limit]


def _extract_quantities_from_message(message: str) -> List[Dict[str, Any]]:
    quantities = []
    pattern = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m2|m3|m|nr|kg|ton|tons|day|days|hrs|hours|%)?", re.IGNORECASE)
    for match in pattern.finditer(message or ""):
        value = _to_float(match.group("value"), None)
        if value is None:
            continue
        quantities.append({
            "value": value,
            "unit": match.group("unit") or "",
            "description": "quantity mentioned by user",
        })
    return quantities[:5]


def _infer_variation_type_and_mode(message: str, ai_result: Optional[Dict[str, Any]] = None) -> tuple[str, str]:
    ai_result = ai_result or {}
    variation_type = str(ai_result.get("variation_type") or "").upper().strip()
    evaluation_mode = str(ai_result.get("evaluation_mode") or "").lower().strip()
    if variation_type:
        return variation_type, evaluation_mode or VARIATION_EVALUATION_MODES.get(variation_type, "quantity_change")

    text = (message or "").lower()
    if any(word in text for word in ("omit", "remove", "delete", "omission")):
        return "TYPE4", "omission"
    if any(word in text for word in ("replace", "substitute", "change to", "change from")):
        return "TYPE2", "substitution"
    if any(phrase in text for phrase in ("additional work", "new work", "extra work", "add new")):
        return "TYPE5", "additional_work"
    if any(word in text for word in ("sequence", "delay", "eot", "schedule", "time impact")):
        return "TYPE6", "time_sequence_change"
    return "TYPE1", "quantity_change"


def _json_from_model_text(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _session_context(project_id: int, session_id: int, storage: StorageManager) -> Optional[Dict[str, Any]]:
    project = storage.get_project(project_id)
    if not project:
        return None
    session = storage.get_session(project_id, session_id)
    if not session:
        return None
    variations = [variation for variation in project.get("variations", []) if variation.get("session_id") == session_id]
    return {
        "session_id": session.get("id"),
        "session_key": session.get("session_key"),
        "project_id": project_id,
        "status": session.get("status"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "metadata": session.get("session_metadata", {}),
        "conversation_history": session.get("chat_history", []),
        "variations_count": len(variations),
        "variations": variations,
    }


def _validate_variation_payload(project: Dict[str, Any], variation: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    warnings = []
    variation_type = str(variation.get("variation_type", "")).upper()
    evaluation_mode = str(variation.get("evaluation_mode", "")).lower()

    if not variation.get("human_confirmed"):
        errors.append("Variation must be confirmed by human before evaluation")
    if evaluation_mode != "additional_work" and not variation.get("original_boq_item_ref"):
        errors.append("BOQ reference missing")
    if variation.get("total_cost_impact", 0) != 0 and not variation.get("confirmed_rate_source"):
        warnings.append("Missing rate source evidence for cost calculation")
    if variation_type == "TYPE4" or evaluation_mode == "omission":
        if float(variation.get("total_cost_impact") or 0) > 0:
            errors.append("Omission variation should have negative cost impact")
    if variation.get("confirmed_activity_ref") and not variation.get("productivity_source"):
        warnings.append("Missing productivity source for time calculation")
    if not variation.get("engineer_instruction_ref"):
        warnings.append("Missing Engineer's Instruction reference")
    if variation_type == "TYPE3" and "drawing" not in str(variation.get("supporting_documents", "")).lower():
        warnings.append("Position variation missing original/revised drawings")

    return {"valid": not errors, "warnings": warnings, "errors": errors}


def _proposal_text(data: Dict[str, Any]) -> str:
    lines = [
        "VARIATION PROPOSAL",
        f"Project: {data.get('project_name') or data.get('name') or 'Construction Project'}",
        f"Variation ID: {data.get('variation_id') or data.get('id') or 'draft'}",
        f"Variation Type: {data.get('variation_type') or ''}",
        f"Evaluation Mode: {data.get('evaluation_mode') or ''}",
        f"Description: {data.get('description') or data.get('replacement_description') or data.get('original_description') or ''}",
        f"Total Cost Impact: {data.get('total_cost_impact', data.get('cost_impact', 0))}",
        "",
        "Cost Lines:",
    ]
    for line in data.get("cost_lines", []) or []:
        if isinstance(line, dict):
            lines.append(
                f"- {line.get('line_type', '')}: {line.get('description', '')} | "
                f"{line.get('quantity', '')} {line.get('unit', '')} x {line.get('rate', '')} = {line.get('amount', '')}"
            )
            if line.get("formula"):
                lines.append(f"  Formula: {line.get('formula')}")
    validation = data.get("validation") or {}
    if validation:
        lines.extend(["", f"Validation: {validation}"])
    return "\n".join(lines)


def _write_minimal_pdf(path: str, text: str) -> None:
    safe_lines = []
    for raw_line in text.splitlines()[:45]:
        line = raw_line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        safe_lines.append(line[:100])
    content_lines = ["BT", "/F1 11 Tf", "50 790 Td"]
    for index, line in enumerate(safe_lines):
        if index:
            content_lines.append("0 -16 Td")
        content_lines.append(f"({line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj + b"\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
    with open(path, "wb") as handle:
        handle.write(pdf)


def _write_minimal_docx(path: str, text: str) -> None:
    paragraphs = "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in text.splitlines())
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{paragraphs}</w:body>
</w:document>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/document.xml", document)


def _build_proposal_data(project: Dict[str, Any], variation: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "project_name": project.get("name") or variation.get("project_name") or "Construction Project",
        "variation_id": variation.get("id"),
        "variation_type": variation.get("variation_type"),
        "evaluation_mode": variation.get("evaluation_mode"),
        "description": variation.get("description") or variation.get("replacement_description") or variation.get("original_description"),
        "cost_lines": variation.get("cost_lines", []),
        "total_cost_impact": variation.get("total_cost_impact", 0),
        "time_impact": variation.get("time_impact", {}),
        "validation": variation.get("validation", {}),
        "formula_summary": variation.get("formula_summary", []),
        "assumptions": variation.get("assumptions", []),
        "rate_sources": [line.get("used_rate_source") for line in variation.get("cost_lines", []) if isinstance(line, dict) and line.get("used_rate_source")],
    }


def _compact_project_context(project: Dict[str, Any]) -> str:
    boq_items = (project.get("boq_items") or [])[:20]
    rate_sources = (project.get("rate_sources") or project.get("rate_breakdowns") or [])[:20]
    activities = (project.get("activities") or [])[:20]
    return json.dumps(
        {
            "project_name": project.get("name"),
            "boq_items": boq_items,
            "rate_sources": rate_sources,
            "activities": activities,
        },
        default=str,
    )[:12000]


def _ask_groq_for_extraction(message: str, project: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    client = _get_groq_client()
    if client is None:
        return {}

    model = os.getenv("GROQ_MODEL", GROQ_DEFAULT_MODEL)
    history_text = "\n".join(
        f"{item.get('role', 'user')}: {item.get('content', '')}"
        for item in (history or [])[-8:]
    )
    prompt = f"""
You are an expert Quantity Surveyor assistant for construction variation evaluation.
Extract structured facts only. Do not calculate final cost. Do not invent rates.

User message:
{message}

Conversation history:
{history_text}

Project context JSON:
{_compact_project_context(project)}

Return only valid JSON with this schema:
{{
  "reply": "short professional response",
  "workflow_state": "type_selection|collecting_details|ready_for_confirmation",
  "variation_type": "TYPE1|TYPE2|TYPE3|TYPE4|TYPE5|TYPE6|null",
  "evaluation_mode": "quantity_change|omission|substitution|additional_work|time_sequence_change|null",
  "original_description": null,
  "replacement_description": null,
  "original_quantity": null,
  "new_quantity": null,
  "replacement_quantity": null,
  "unit": "",
  "extracted_quantities": [{{"value": 0, "unit": "", "description": ""}}],
  "affected_boq_candidates": [{{"description": "", "item_reference": null, "similarity_score": 0.0}}],
  "affected_activity_candidates": [{{"name": "", "activity_id": null, "similarity_score": 0.0}}],
  "rate_evidence_candidates": [{{"source_type": "", "reference": "", "rate": null}}],
  "supporting_documents_found": [],
  "missing_information": [],
  "confidence_score": 0.0,
  "requires_human_confirmation": true
}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. You extract QS variation facts from user messages."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=1600,
    )
    return _json_from_model_text(response.choices[0].message.content or "")


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


class ChatRequest(pydantic.BaseModel):
    message: str
    project_id: int
    session_id: Optional[int] = None


@app.get("/")
def read_root():
    return {
        "message": "Hybrid Rule-Based and ML-Assisted Variation Evaluation Prototype",
        "version": "2.0.0",
        "status": "running",
        "description": "ML-assisted extraction + rule-based evaluation",
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
    projects = []
    for project_meta in storage.get_projects():
        project = storage.get_project(project_meta.get("id")) or {}
        projects.append({
            **project_meta,
            "boq_items": len(project.get("boq_items", []) or []),
            "rate_breakdowns": len(project.get("rate_breakdowns", []) or []),
            "rate_sources": len(project.get("rate_sources", []) or []),
            "activities": len(project.get("activities", []) or []),
            "variations": len(project.get("variations", []) or []),
        })
    return {"projects": projects}


@app.get("/debug/project/{project_id}")
def debug_project(project_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "status": "success",
        "project_id": project_id,
        "project_name": project.get("name"),
        "counts": {
            "boq_items": len(project.get("boq_items", []) or []),
            "rate_breakdowns": len(project.get("rate_breakdowns", []) or []),
            "rate_sources": len(project.get("rate_sources", []) or []),
            "activities": len(project.get("activities", []) or []),
            "sessions": len(project.get("sessions", []) or []),
            "variations": len(project.get("variations", []) or []),
            "additional_files": len(project.get("additional_files", []) or []),
        },
        "sample_boq_items": (project.get("boq_items", []) or [])[:3],
        "sample_rate_sources": (project.get("rate_sources", []) or [])[:5],
        "sample_activities": (project.get("activities", []) or [])[:5],
        "additional_files": project.get("additional_files", []) or [],
    }


@app.post("/session/create")
def create_session(
    project_id: int = Body(...),
    metadata: Optional[Dict[str, Any]] = Body(None),
    storage: StorageManager = Depends(get_storage),
):
    session = storage.create_session(project_id, metadata)
    if not session:
        raise HTTPException(status_code=404, detail="Project not found")
    return session


@app.get("/session/{project_id}/{session_id}")
def get_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    context = _session_context(project_id, session_id, storage)
    if not context:
        raise HTTPException(status_code=404, detail="Session not found")
    return context


@app.post("/session/{project_id}/{session_id}/continue")
def continue_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    session = storage.get_session(project_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    for existing in project.get("sessions", []):
        if existing.get("id") == session.get("id"):
            existing["status"] = "active"
            existing["updated_at"] = datetime.utcnow().isoformat()
            break
    storage.update_project(project_id, {"sessions": project.get("sessions", [])})
    return {"status": "success", "context": _session_context(project_id, session_id, storage)}


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
    proposal = _build_proposal_data(project, variation)
    report_text = _proposal_text(proposal)
    pdf_path = _runtime_file("generated_reports", f"variation_proposal_{variation.get('id')}.pdf")
    docx_path = _runtime_file("generated_reports", f"variation_proposal_{variation.get('id')}.docx")
    _write_minimal_pdf(pdf_path, report_text)
    _write_minimal_docx(docx_path, report_text)
    storage.update_variation(project_id, variation.get("id"), {
        "pdf_url": f"/download/{os.path.basename(pdf_path)}",
        "docx_url": f"/download/{os.path.basename(docx_path)}",
        "pdf_path": pdf_path,
        "docx_path": docx_path,
    })

    return {
        "status": "success",
        "variation_id": variation.get("id"),
        "pdf_url": f"/download/{os.path.basename(pdf_path)}",
        "docx_url": f"/download/{os.path.basename(docx_path)}",
        "proposal": proposal,
        **evaluation_result,
    }


@app.post("/variation/validate/{project_id}/{variation_id}")
def validate_variation(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    variation = storage.get_variation(project_id, variation_id)
    if not project or not variation:
        raise HTTPException(status_code=404, detail="Project or variation not found")
    return _validate_variation_payload(project, variation)


@app.get("/variation/validation-report/{project_id}/{variation_id}")
def get_validation_report(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    variation = storage.get_variation(project_id, variation_id)
    if not project or not variation:
        raise HTTPException(status_code=404, detail="Project or variation not found")
    validation = _validate_variation_payload(project, variation)
    report_lines = ["Variation Validation Report", f"Project: {project.get('name')}", f"Variation ID: {variation_id}", f"Valid: {validation['valid']}"]
    report_lines.extend([f"Warning: {item}" for item in validation.get("warnings", [])])
    report_lines.extend([f"Error: {item}" for item in validation.get("errors", [])])
    return {"report": "\n".join(report_lines), "validation": validation}


@app.get("/variation/{project_id}/{variation_id}")
def get_variation(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    return variation


@app.put("/variation/{project_id}/{variation_id}/details/{detail_id}")
def update_variation_detail(project_id: int, variation_id: int, detail_id: int, updates: Dict[str, Any], storage: StorageManager = Depends(get_storage)):
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")

    updated = False
    for field in ("details", "cost_lines"):
        lines = variation.get(field)
        if not isinstance(lines, list):
            continue
        for index, line in enumerate(lines):
            if isinstance(line, dict) and str(line.get("id", index + 1)) == str(detail_id):
                line.update(updates)
                updated = True
                break
        if updated:
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Detail not found")

    storage.update_variation(project_id, variation_id, variation)
    return {"status": "success", "detail_id": detail_id, "message": "Detail updated"}


@app.post("/variation/{project_id}/{variation_id}/status")
def update_variation_status(project_id: int, variation_id: int, status: str = Body(..., embed=True), storage: StorageManager = Depends(get_storage)):
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    updated = storage.update_variation(project_id, variation_id, {"status": status})
    return {"status": "success", "variation": updated}


@app.post("/upload/files")
async def upload_files(
    boq: Optional[UploadFile] = File(None),
    breakdown: Optional[UploadFile] = File(None),
    schedule: Optional[UploadFile] = File(None),
    storage: StorageManager = Depends(get_storage),
):
    if not any([boq, breakdown, schedule]):
        raise HTTPException(status_code=400, detail="Upload at least one file: boq, breakdown, or schedule")

    upload_dir = _runtime_dir("uploaded_files")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

    project_name = (
        Path(boq.filename).stem
        if boq and boq.filename
        else f"Project_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    )
    project = storage.create_project(
        name=project_name,
        boq_filename=boq.filename if boq else None,
        rate_breakdown_filename=breakdown.filename if breakdown else None,
        schedule_filename=schedule.filename if schedule else None,
    )
    session = storage.create_session(project["id"], {"created_via": "upload", "storage": "temporary"})

    results = {
        "project_id": project["id"],
        "session_id": session["id"],
        "session_key": session["session_key"],
        "boq_items": 0,
        "rate_breakdowns": 0,
        "schedule_tasks": 0,
        "files": [],
        "processing_notes": [],
        "temporary_storage": True,
    }

    if boq:
        saved = _save_upload(boq, upload_dir, prefix=f"{timestamp}_boq_")
        results["files"].append({**saved, "type": "boq"})
        if saved["filename"].lower().endswith(".csv"):
            items = _parse_boq_csv(saved["file_path"])
            results["boq_items"] = storage.add_boq_items(project["id"], items, "Uploaded BOQ")
            results["processing_notes"].append(f"BOQ CSV parsed: {results['boq_items']} items")
        else:
            results["processing_notes"].append("BOQ uploaded temporarily; only CSV parsing is enabled in this clean backend")

    if breakdown:
        saved = _save_upload(breakdown, upload_dir, prefix=f"{timestamp}_rate_")
        results["files"].append({**saved, "type": "rate_breakdown"})
        if saved["filename"].lower().endswith(".csv"):
            items = _parse_rate_csv(saved["file_path"], saved["filename"])
            results["rate_breakdowns"] = storage.add_rate_breakdowns(project["id"], items)
            results["processing_notes"].append(f"Rate CSV parsed: {results['rate_breakdowns']} items")
        else:
            results["processing_notes"].append("Rate breakdown uploaded temporarily; only CSV parsing is enabled in this clean backend")

    if schedule:
        saved = _save_upload(schedule, upload_dir, prefix=f"{timestamp}_schedule_")
        results["files"].append({**saved, "type": "schedule"})
        if saved["filename"].lower().endswith(".csv"):
            activities = _parse_schedule_csv(saved["file_path"])
            results["schedule_tasks"] = storage.add_activities(project["id"], activities)
            results["processing_notes"].append(f"Schedule CSV parsed: {results['schedule_tasks']} activities")
        else:
            results["processing_notes"].append("Schedule uploaded temporarily; only CSV parsing is enabled in this clean backend")

    return {"status": "success", "data": results}


@app.post("/upload/quotation")
async def upload_quotation(file: UploadFile = File(...)):
    upload_dir = _runtime_dir("uploaded_files", "quotations")
    saved = _save_upload(file, upload_dir, prefix=f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_")
    extracted_items = _parse_rate_csv(saved["file_path"], saved["filename"]) if saved["filename"].lower().endswith(".csv") else []
    return {
        "status": "success",
        "temporary_storage": True,
        "file": saved,
        "extracted_items_count": len(extracted_items),
        "preview": extracted_items[:5],
        "message": "Quotation uploaded temporarily. CSV rate extraction is enabled; PDF extraction is not enabled in the clean backend.",
    }


@app.post("/upload/additional-files")
async def upload_additional_files(
    project_id: int = Form(...),
    variation_id: Optional[str] = Form(None),
    file_type: str = Form(...),
    files: List[UploadFile] = File(...),
    storage: StorageManager = Depends(get_storage),
):
    if not storage.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    upload_dir = _runtime_dir("uploaded_files", "additional")
    uploaded = []
    for file in files:
        saved = _save_upload(file, upload_dir, prefix=f"{project_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_")
        extracted_items = []
        if file_type.strip().lower() in {"bsr", "hsr", "quotation", "rate_breakdown"} and saved["filename"].lower().endswith(".csv"):
            extracted_items = _parse_rate_csv(saved["file_path"], saved["filename"])
            if extracted_items:
                storage.add_rate_sources(project_id, extracted_items)
        record = storage.add_additional_file(project_id, {
            "variation_id": variation_id,
            "filename": saved["filename"],
            "file_type": file_type,
            "file_path": saved["file_path"],
            "temporary_storage": True,
            "size": saved["size"],
            "content_type": saved["content_type"],
            "rate_sources_extracted": len(extracted_items),
        })
        uploaded.append({**saved, "record": record, "rate_sources_extracted": len(extracted_items), "preview": extracted_items[:5]})

    return {
        "status": "success",
        "temporary_storage": True,
        "files_uploaded": len(uploaded),
        "rate_sources_extracted": sum(item.get("rate_sources_extracted", 0) for item in uploaded),
        "preview": [candidate for item in uploaded for candidate in item.get("preview", [])][:5],
        "files": uploaded,
    }


@app.post("/chat")
def chat(request: ChatRequest, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if request.session_id:
        session = storage.get_session(request.project_id, request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = storage.create_session(request.project_id, {"created_via": "chat"})

    session_id = session["id"]
    storage.add_chat_message(request.project_id, session_id, "user", request.message)
    history = storage.get_session(request.project_id, session_id).get("chat_history", [])

    boq_candidates = _rank_boq_candidates(request.message, project)
    rate_candidates = _rank_rate_candidates(request.message, project)
    activity_candidates = _rank_activity_candidates(request.message, project)
    extracted_quantities = _extract_quantities_from_message(request.message)

    ai_result: Dict[str, Any] = {}
    ai_error = None
    try:
        ai_result = _ask_groq_for_extraction(request.message, project, history)
    except Exception as exc:
        ai_error = str(exc)
        ai_result = {}

    variation_type, evaluation_mode = _infer_variation_type_and_mode(request.message, ai_result)
    detected_unit = ai_result.get("unit") or (extracted_quantities[0].get("unit") if extracted_quantities else "")

    merged_boq_candidates = ai_result.get("affected_boq_candidates") or boq_candidates
    merged_activity_candidates = ai_result.get("affected_activity_candidates") or activity_candidates
    merged_rate_candidates = ai_result.get("rate_evidence_candidates") or rate_candidates

    missing_information = ai_result.get("missing_information") or []
    if not merged_boq_candidates and evaluation_mode not in {"additional_work", "time_sequence_change"}:
        missing_information.append("affected BOQ item confirmation")
    if not merged_rate_candidates and evaluation_mode != "time_sequence_change":
        missing_information.append("rate source confirmation")

    reply = ai_result.get("reply")
    if not reply:
        if ai_error:
            reply = "AI extraction is currently unavailable, so I used deterministic matching from uploaded project data instead."
        elif os.getenv("GROQ_API_KEY"):
            reply = "I extracted the likely variation details and candidates. Please confirm the BOQ item, rate source, quantities, and any activity/productivity data before final evaluation."
        else:
            reply = "AI extraction is not configured because GROQ_API_KEY is missing. I used deterministic matching from uploaded project data instead."

    response = {
        "reply": reply,
        "proposal": None,
        "session_id": session_id,
        "workflow_state": ai_result.get("workflow_state") or "collecting_details",
        "requires_human_confirmation": True,
        "variation_type": variation_type,
        "evaluation_mode": evaluation_mode,
        "original_description": ai_result.get("original_description"),
        "replacement_description": ai_result.get("replacement_description"),
        "original_quantity": ai_result.get("original_quantity"),
        "new_quantity": ai_result.get("new_quantity"),
        "replacement_quantity": ai_result.get("replacement_quantity"),
        "unit": detected_unit,
        "extracted_quantities": ai_result.get("extracted_quantities") or extracted_quantities,
        "rate_candidates": merged_rate_candidates,
        "selected_rate_candidate": merged_rate_candidates[0] if merged_rate_candidates else None,
        "affected_boq_candidates": merged_boq_candidates,
        "affected_activity_candidates": merged_activity_candidates,
        "supporting_documents_found": ai_result.get("supporting_documents_found") or [],
        "missing_information": missing_information,
        "confidence_score": ai_result.get("confidence_score", 0.0),
        "ai_provider": "groq" if ai_result else "deterministic_fallback",
    }
    if ai_error:
        response["ai_error"] = ai_error

    storage.add_chat_message(request.project_id, session_id, "assistant", reply, {"chat_response": response})
    return response


@app.post("/generate-pdf")
def generate_pdf(request: Dict[str, Any]):
    output_path = _runtime_file("generated_reports", f"variation_proposal_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.pdf")
    _write_minimal_pdf(output_path, _proposal_text(request))
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"Variation_Proposal_{request.get('variation_id', 'draft')}.pdf",
    )


@app.post("/variation/{project_id}/{variation_id}/generate-docx")
def generate_variation_docx(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    project = storage.get_project(project_id)
    variation = storage.get_variation(project_id, variation_id)
    if not project or not variation:
        raise HTTPException(status_code=404, detail="Project or variation not found")
    proposal = _build_proposal_data(project, variation)
    output_path = _runtime_file("generated_reports", f"variation_proposal_{variation_id}.docx")
    _write_minimal_docx(output_path, _proposal_text(proposal))
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"Variation_Proposal_{variation_id}.docx",
    )


@app.get("/download/{filename}")
def download_file(filename: str):
    safe_filename = _safe_filename(filename)
    if not safe_filename.lower().endswith((".pdf", ".docx")):
        raise HTTPException(status_code=400, detail="Only PDF and DOCX downloads are allowed")
    file_path = _runtime_file("generated_reports", safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "application/pdf" if safe_filename.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(file_path, media_type=media_type, filename=safe_filename)
