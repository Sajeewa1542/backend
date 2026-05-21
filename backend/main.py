from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Optional, Dict, Any
import uvicorn
import shutil
import pydantic
import os
import re
import importlib
from datetime import datetime
from .storage_manager import StorageManager, storage_manager
from dotenv import load_dotenv

# Load .env
load_dotenv()

# storage_manager is initialized in its own module

app = FastAPI(
    title="Hybrid Rule-Based and ML-Assisted Variation Evaluation Prototype",
    description="FIDIC-compliant variation assessment with ML-assisted extraction and rule-based evaluation",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_storage() -> StorageManager:
    return storage_manager


def _runtime_path(*parts: str) -> str:
    if os.getenv("VERCEL"):
        return os.path.join("/tmp", *parts)
    return os.path.join(*parts)


def _append_runtime_log(*parts: str, message: str) -> None:
    path = _runtime_path(*parts)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a") as handle:
        handle.write(message)


class _LazyImport:
    def __init__(self, module_name: str, attribute_name: str):
        self.module_name = module_name
        self.attribute_name = attribute_name
        self._value = None

    def _load(self):
        if self._value is None:
            module = importlib.import_module(self.module_name, package=__package__)
            self._value = getattr(module, self.attribute_name)
        return self._value

    def __call__(self, *args, **kwargs):
        return self._load()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._load(), name)


# Heavy data/ML/PDF modules are loaded only when an endpoint actually needs them.
CostEngine = _LazyImport(".engine", "CostEngine")
TimeEngine = _LazyImport(".engine", "TimeEngine")
SessionManager = _LazyImport(".session_manager", "SessionManager")
ValidationEngine = _LazyImport(".validation_engine", "ValidationEngine")
ocr_processor = _LazyImport(".ocr_processor", "ocr_processor")
PDFGenerator = _LazyImport(".pdf_utils", "PDFGenerator")
DOCXGenerator = _LazyImport(".docx_utils", "DOCXGenerator")
rate_source_extractor = _LazyImport(".rate_source_extractor", "rate_source_extractor")
rate_resolver = _LazyImport(".rate_resolver", "rate_resolver")
variation_evaluator = _LazyImport(".variation_evaluator", "variation_evaluator")
load_keyword_normalization_map = _LazyImport(".keyword_normalization", "load_keyword_normalization_map")
tokenize_for_matching = _LazyImport(".keyword_normalization", "tokenize_for_matching")
tokens_contained = _LazyImport(".keyword_normalization", "tokens_contained")


@app.get("/")
def read_root():
    return {"status": "ok", "service": "Hybrid Variation Evaluation API"}


VARIATION_EVALUATION_MODES = {
    "TYPE1": "quantity_change",
    "TYPE2": "substitution",
    "TYPE3": "quantity_change",
    "TYPE4": "omission",
    "TYPE5": "additional_work",
    "TYPE6": "time_sequence_change",
}


def _safe_dict(value):
    """Return a dict only. Prevents 'str object has no attribute get' errors."""
    return value if isinstance(value, dict) else {}


def _build_variation_proposal_data(project: Dict[str, Any], variation: Dict[str, Any], evaluation_result: Dict[str, Any]) -> Dict[str, Any]:
    project = _safe_dict(project)
    variation = _safe_dict(variation)
    evaluation_result = _safe_dict(evaluation_result)

    used_rate_sources = []

    for idx, line in enumerate(evaluation_result.get("cost_lines", []) or [], start=1):
        if not isinstance(line, dict):
            continue

        used = line.get("used_rate_source")

        # If evaluator gives full source dict, use it
        if isinstance(used, dict):
            minimal = {
                "source_type": used.get("source_type") or line.get("source_type") or "confirmed",
                "source_file": used.get("source_file") or "",
                "item_reference": used.get("item_reference") or line.get("rate_source_id") or "",
                "description": used.get("description") or line.get("description") or "",
                "unit": used.get("unit") or line.get("unit") or "",
                "rate": used.get("rate") or line.get("rate") or 0,
                "confidence": used.get("confidence") or used.get("confidence_score") or "Human confirmed",
                "used_in_line_id": line.get("id") or line.get("line_id") or idx,
            }

        # If evaluator gives only string rate_source, do NOT call .get() on it
        else:
            source_text = line.get("rate_source") or variation.get("confirmed_rate_source") or "Confirmed source"
            minimal = {
                "source_type": "BOQ" if "boq" in str(source_text).lower() else "confirmed",
                "source_file": "",
                "item_reference": line.get("rate_source_id") or variation.get("confirmed_rate_source_id") or variation.get("original_boq_item_ref") or "",
                "description": line.get("description") or variation.get("description") or "",
                "unit": line.get("unit") or variation.get("unit") or "",
                "rate": line.get("rate") or variation.get("confirmed_rate") or 0,
                "confidence": "Human confirmed",
                "used_in_line_id": line.get("id") or line.get("line_id") or idx,
            }

        used_rate_sources.append(minimal)

    uploaded_documents = []
    for file_record in project.get("additional_files", []) or []:
        if isinstance(file_record, dict):
            uploaded_documents.append(file_record.get("filename") or file_record.get("file_path") or "")

    validation = evaluation_result.get("validation", {}) or {}
    if not isinstance(validation, dict):
        validation = {"warnings": [str(validation)], "errors": []}

    time_impact = evaluation_result.get("time_impact", {}) or {}
    if not isinstance(time_impact, dict):
        time_impact = {"message": str(time_impact)}

    return {
        "project_name": (
           variation.get("project_name")
           or project.get("name")
           or "Construction Project"
        ),
        "variation_id": variation.get("id"),
        "variation_type": variation.get("variation_type"),
        "evaluation_mode": variation.get("evaluation_mode"),
        "description": (
            variation.get("description")
            or variation.get("original_description")
            or variation.get("replacement_description")
            or "Variation proposal"
        ),
        "status": variation.get("status", "Under Review"),
        "human_confirmed": variation.get("human_confirmed", False),
        "supporting_documents": variation.get("supporting_documents", []),
        "uploaded_documents": uploaded_documents,

        # Keep both keys because PDF/DOCX generators may use different names
        "rate_sources": used_rate_sources,
        "used_rate_sources": used_rate_sources,

        "cost_lines": evaluation_result.get("cost_lines", []),
        "total_cost_impact": evaluation_result.get("total_cost_impact", 0.0),
        "cost_impact": evaluation_result.get("total_cost_impact", 0.0),
        "time_impact": time_impact,
        "time_impact_result": time_impact,
        "validation": validation,
        "formula_summary": evaluation_result.get("formula_summary", []),
        "assumptions": evaluation_result.get("assumptions", []),
        "missing_information": validation.get("warnings", []) + validation.get("errors", []),
        "recommendation": "QS review required before submission",
    }


def _coerce_activity_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    candidate = _safe_dict(candidate)
    name = str(candidate.get("name") or candidate.get("activity_name") or "").strip()
    activity_id = candidate.get("activity_id") or candidate.get("id")

    try:
        score = float(candidate.get("similarity_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0

    return {
        "name": name,
        "activity_id": activity_id,
        "duration": candidate.get("duration"),
        "is_critical": candidate.get("is_critical"),
        "similarity_score": score,
    }


def _build_activity_candidates(
    search_query: str,
    activities: List[Dict[str, Any]],
    normalization_map: Dict[str, str],
    selected_boq_item: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    # If BOQ item selected, include its description in search
    search_text = search_query
    if selected_boq_item and isinstance(selected_boq_item, dict):
        boq_desc = selected_boq_item.get('description', '')
        if boq_desc and boq_desc.lower() not in search_query.lower():
            search_text = f"{search_query} {boq_desc}"
    
    keywords = tokenize_for_matching(search_text, mapping=normalization_map)
    candidates = []

    for activity in activities or []:
        if not isinstance(activity, dict):
            continue

        name = activity.get("name", "") or activity.get("activity_name", "")
        activity_tokens = set(tokenize_for_matching(name, mapping=normalization_map))

        if not activity_tokens:
            continue

        overlap = len(activity_tokens.intersection(keywords))

        # Extra deterministic trade mapping
        q = search_text.lower()  # Use search_text which includes BOQ description if available
        n = str(name).lower()

        if any(w in q for w in ["excavation", "foundation", "trench"]) and any(w in n for w in ["excavation", "foundation", "trench"]):
            overlap += 3
        if any(w in q for w in ["tile", "tiling", "floor", "granite", "ceramic"]) and any(w in n for w in ["tile", "tiling", "floor", "finish"]):
            overlap += 3
        if any(w in q for w in ["paving", "interlocking", "driveway", "external"]) and any(w in n for w in ["paving", "external", "drainage"]):
            overlap += 3
        if any(w in q for w in ["door", "window"]) and any(w in n for w in ["door", "window"]):
            overlap += 3
        if any(w in q for w in ["ceiling", "gypsum", "panel"]) and any(w in n for w in ["ceiling", "gypsum"]):
            overlap += 3
        if any(w in q for w in ["waterproof", "toilet"]) and any(w in n for w in ["waterproof", "toilet"]):
            overlap += 3
        # Asphalt courses: prefer exact thickness match
        if any(w in q for w in ["asphalt", "wearing course", "base course"]):
            if any(w in n for w in ["asphalt", "wearing course"]):
                overlap += 2
            # Check for thickness matching
            thickness_in_q = None
            for thick in ["40mm", "20mm", "100mm"]:
                if thick in q:
                    thickness_in_q = thick
                    break
            
            if thickness_in_q:
                if thickness_in_q in n:
                    # Perfect match
                    overlap += 3
                else:
                    # Check for conflicting thickness
                    for other_thick in ["40mm", "20mm", "100mm"]:
                        if other_thick != thickness_in_q and other_thick in n:
                            # Penalize mismatch (e.g., query has 40mm but activity has 20mm)
                            overlap = max(0, overlap - 3)
                            break

        if overlap <= 0:
            continue

        score = overlap / max(1, len(activity_tokens))

        candidates.append({
            "name": name,
            "activity_id": activity.get("activity_id") or activity.get("id") or activity.get("task_id"),
            "duration": activity.get("duration"),
            "is_critical": activity.get("is_critical") or activity.get("critical"),
            "float": activity.get("float") or activity.get("total_float"),
            "similarity_score": round(min(score, 1.0), 4),
        })

    candidates.sort(
        key=lambda item: (item.get("similarity_score", 0.0), str(item.get("name", "")).lower()),
        reverse=True
    )

    return candidates[:5]


def _merge_activity_candidates(
    ai_candidates: List[Dict[str, Any]],
    deterministic_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for candidate in (ai_candidates or []) + (deterministic_candidates or []):
        normalized = _coerce_activity_candidate(candidate)
        key = str(normalized.get("activity_id") or normalized.get("name") or "").strip().lower()

        if not key:
            continue

        if key not in merged or normalized.get("similarity_score", 0.0) > merged[key].get("similarity_score", 0.0):
            merged[key] = normalized

    return sorted(
        merged.values(),
        key=lambda item: (item.get("similarity_score", 0.0), str(item.get("name", "")).lower()),
        reverse=True,
    )[:5]

def _normalize_boq_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize BOQ candidate structure to standard field names."""
    if not isinstance(candidate, dict):
        return candidate
    
    return {
        "item_reference": candidate.get("item_reference") or candidate.get("ref") or candidate.get("item_no") or candidate.get("reference"),
        "description": candidate.get("description") or candidate.get("item") or candidate.get("item_description"),
        "unit": candidate.get("unit"),
        "rate": candidate.get("rate"),
        "quantity": candidate.get("quantity") or candidate.get("original_quantity"),
        "original_quantity": candidate.get("original_quantity") or candidate.get("quantity"),
        "new_quantity": candidate.get("new_quantity"),
        "similarity_score": candidate.get("similarity_score", candidate.get("confidence_score", 0.75)),
        "confidence_score": candidate.get("confidence_score", candidate.get("similarity_score", 0.75)),
        "source_type": candidate.get("source_type", "boq"),
        "reason": candidate.get("reason", ""),
    }


def _enrich_activity_candidates_with_project_data(
    candidates: List[Dict[str, Any]], 
    project_activities: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Enrich activity candidates by looking up actual activity data from the project.
    Replaces AI-extracted placeholders with real project data.
    """
    _append_runtime_log("debug_activities.log", message=f"[ENRICH] Called with {len(candidates)} candidates, {len(project_activities)} activities\n")
    
    if not project_activities:
        _append_runtime_log("debug_activities.log", message="[ENRICH] No project activities, returning original candidates\n")
        return candidates
    
    enriched = []
    for candidate in candidates or []:
        activity_id = candidate.get("activity_id")
        
        # Look for matching activity in project
        matched_activity = None
        if activity_id:
            for pa in project_activities:
                if str(pa.get("activity_id") or pa.get("id")) == str(activity_id):
                    matched_activity = pa
                    _append_runtime_log("debug_activities.log", message=f"[ENRICH] Found match for activity {activity_id}: {pa.get('name')}\n")
                    break
        
        if matched_activity:
            # Merge with real project data
            enriched_candidate = {
                **candidate,
                "activity_id": matched_activity.get("activity_id") or matched_activity.get("id"),
                "name": matched_activity.get("name") or matched_activity.get("activity_name") or candidate.get("name"),
                "activity_name": matched_activity.get("name") or matched_activity.get("activity_name") or candidate.get("activity_name"),
                "duration": matched_activity.get("duration") or candidate.get("duration"),
                "is_critical": matched_activity.get("is_critical") or matched_activity.get("critical") or candidate.get("is_critical"),
                "float": matched_activity.get("float") or matched_activity.get("total_float") or candidate.get("float"),
                "productivity": matched_activity.get("productivity") or candidate.get("productivity"),
                "unit": matched_activity.get("unit") or candidate.get("unit"),
            }
            enriched.append(enriched_candidate)
        else:
            if activity_id:
                _append_runtime_log("debug_activities.log", message=f"[ENRICH] No match found for activity {activity_id}\n")
            enriched.append(candidate)
    
    return enriched


def _normalize_activity_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize activity candidate structure to standard field names."""
    if not isinstance(candidate, dict):
        return candidate
    
    return {
        "activity_id": candidate.get("activity_id") or candidate.get("id") or candidate.get("task_id"),
        "activity_name": candidate.get("activity_name") or candidate.get("name"),
        "name": candidate.get("activity_name") or candidate.get("name"),
        "duration": candidate.get("duration"),
        "is_critical": candidate.get("is_critical") or candidate.get("critical"),
        "float": candidate.get("float") or candidate.get("total_float"),
        "productivity": candidate.get("productivity"),
        "unit": candidate.get("unit"),
        "similarity_score": candidate.get("similarity_score", 0.75),
        "confidence_score": candidate.get("confidence_score", candidate.get("similarity_score", 0.75)),
        "reason": candidate.get("reason", ""),
    }


def _extract_first_candidate_ref(candidates: List[Dict[str, Any]]) -> Optional[str]:
    """Get the first BOQ/item reference from candidate list."""
    if not candidates:
        return None

    first = candidates[0] if isinstance(candidates[0], dict) else {}

    for key in ["item_reference", "item_number", "item_no", "item_ref", "code", "ref", "id"]:
        value = first.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def _infer_variation_type_and_mode(message: str, ai_result: Dict[str, Any]) -> tuple[str, str]:
    """
    Reliable fallback variation type inference based on message content.
    Checks for explicit keywords and structural markers (quantity change, substitution, omission, additional work).
    """
    text = f"{message or ''} {ai_result.get('reply', '')}".lower()

    explicit_type = (
        ai_result.get("variation_type")
        or ai_result.get("suggested_type")
        or ai_result.get("type")
    )

    if explicit_type:
        explicit_type = str(explicit_type).upper()
        mode = VARIATION_EVALUATION_MODES.get(explicit_type, ai_result.get("evaluation_mode") or "quantity_change")
        return explicit_type, mode

    # TYPE2: Substitution / Quality Change
    # Look for explicit "change X to Y", "replace X with Y", "substitute X for Y"
    if "type 2" in text or "substitution" in text or "substitut" in text:
        return "TYPE2", "substitution"
    if re.search(r'(?:change|replace|substitut|swap)\s+\w+\s+(?:to|with|for|by)\s+\w+', text):
        return "TYPE2", "substitution"

    # TYPE4: Omission
    if "type 4" in text or "omission" in text or "omit" in text or "remove" in text or "delete" in text:
        return "TYPE4", "omission"

    # TYPE5: Additional Work
    # Only if "additional work" phrase or "new work" appears together, NOT just "additional asphalt" (that's TYPE1)
    if "type 5" in text or "additional work" in text or "new work" in text:
        return "TYPE5", "additional_work"
    # "add X" is ambiguous: could be TYPE1 quantity_increase or TYPE5 new_item
    # Check if it's clearly "new item" vs "increase quantity"
    if re.search(r'\b(?:add|install|construct)\s+(?:new|additional|extra|further)\s+\w+\s+(?:work|item|element|section)\b', text):
        return "TYPE5", "additional_work"

    # TYPE6: Sequence/Timing Change
    if "type 6" in text or "sequence" in text or "timing" in text or "schedule" in text and "change" in text:
        return "TYPE6", "time_sequence_change"

    # TYPE1: Quantity Change (DEFAULT)
    # If message mentions "quantity", "revised", "new", "increased", "reduced", "m2", "m3", etc.
    # This is the default and most common case
    return "TYPE1", "quantity_change"


def _extract_rate_reference_from_text(message: str) -> Optional[str]:
    """
    Extract references such as RB/19, RB-19, BSR/12, HSR/05, Q-SOL-01.
    """
    if not message:
        return None

    match = re.search(r"\b(?:rb|bsr|hsr|q|qt|quo|quotation)[\s/.-]*[a-z0-9-]+\b", message, flags=re.IGNORECASE)
    if not match:
        return None

    raw = match.group(0).strip()
    raw = re.sub(r"\s+", "/", raw)
    raw = raw.replace("-", "/")
    return raw.upper()


def _build_rate_query(
    message: str,
    ai_result: Dict[str, Any],
    final_variation_type: str,
    final_evaluation_mode: str,
) -> str:
    """
    Build better query for rate resolver.

    For TYPE2, the rate query should focus on replacement work, not original BOQ work.
    Example:
    Original = ceramic tiles
    Replacement = polished granite
    Rate ref = RB/19
    """
    extracted_data = ai_result.get("extracted_data", {}) or {}

    replacement_description = (
        ai_result.get("replacement_description")
        or extracted_data.get("replacement_description")
        or extracted_data.get("new_description")
        or extracted_data.get("proposed_description")
        or ""
    )

    original_description = (
        ai_result.get("original_description")
        or extracted_data.get("original_description")
        or ""
    )

    rate_ref = _extract_rate_reference_from_text(message)

    parts = []

    if final_variation_type == "TYPE2" or final_evaluation_mode == "substitution":
        # Prioritise replacement side for substitution.
        parts.extend([
            replacement_description,
            rate_ref or "",
            message,
        ])
    else:
        parts.extend([
            replacement_description,
            original_description,
            rate_ref or "",
            message,
        ])

    return " ".join(str(part) for part in parts if part).strip()

def _normalize_rate_ref(value: Any) -> str:
    """
    RB/19, RB-19, RB 19 -> rb19
    """
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _find_rate_source_by_reference(project: Dict[str, Any], reference: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Direct fallback search for exact rate references such as RB/19.
    This is used when semantic rate resolver returns no candidate.
    """
    if not project or not reference:
        return None

    target = _normalize_rate_ref(reference)

    sources = []
    sources.extend(project.get("rate_sources", []) or [])
    sources.extend(project.get("rate_breakdowns", []) or [])

    for source in sources:
        if not isinstance(source, dict):
            continue

        item_reference = (
            source.get("item_reference")
            or source.get("item_ref")
            or source.get("item_number")
            or source.get("item_no")
            or source.get("code")
            or source.get("ref")
            or source.get("id")
        )

        source_text = " ".join(
            str(value or "")
            for value in [
                item_reference,
                source.get("source_id"),
                source.get("description"),
                source.get("raw_text_excerpt"),
            ]
        )

        if target and target in _normalize_rate_ref(source_text):
            return {
                "source_priority": 0,
                "source_type": source.get("source_type") or "rate_breakdown",
                "source_id": str(source.get("id") or item_reference or reference),
                "source_file": source.get("source_file"),
                "page_number": source.get("page_number"),
                "item_reference": str(item_reference or reference),
                "description": source.get("description") or "",
                "unit": source.get("unit"),
                "rate": source.get("rate") or source.get("unit_rate") or source.get("total_rate"),
                "similarity_score": 1.0,
                "confidence_score": 0.99,
                "reason": "Exact rate reference fallback match from uploaded rate sources",
            }

    return None

def _extract_quantities_from_message(message: str) -> List[Dict[str, Any]]:
    """
    Improved quantity extraction from natural language.
    Example: 'Original quantity is 96 m2, revised total quantity is 58549 m2'
    Returns: [{"value": 96, "unit": "m2", "description": "original"}, {"value": 58549, "unit": "m2", "description": "revised total"}]
    """
    if not message:
        return []

    quantities = []
    message_lower = message.lower()

    # Pattern 1: "revised total quantity is X unit"
    revised_pattern = r"revised\s+total\s+quantity\s+is\s+(\d+(?:[,.]?)\d*)\s*(m2|m3|m|sqm|sq\.m|cu\.m|nos|no|nr|set|item|day|days|kg|t|tonnes|litre|ml)"
    revised_matches = re.findall(revised_pattern, message, flags=re.IGNORECASE)
    for value, unit in revised_matches:
        value_clean = value.replace(",", "").replace(".", "", value.count(".") - 1) if value.count(".") > 1 else value.replace(",", "")
        normalized_unit = unit.lower().replace("sqm", "m2").replace("sq.m", "m2").replace("cu.m", "m3")
        quantities.append({
            "value": float(value_clean),
            "unit": normalized_unit,
            "description": "revised total quantity"
        })

    # Pattern 2: "original quantity is X" or "existing quantity is X"
    original_pattern = r"(?:original|existing|current|old)\s+(?:total\s+)?quantity\s+is\s+(\d+(?:[,.]?)\d*)\s*(m2|m3|m|sqm|sq\.m|cu\.m|nos|no|nr|set|item|day|days|kg|t|tonnes|litre|ml)?"
    original_matches = re.findall(original_pattern, message, flags=re.IGNORECASE)
    for value, unit in original_matches:
        value_clean = value.replace(",", "").replace(".", "", value.count(".") - 1) if value.count(".") > 1 else value.replace(",", "")
        if unit:
            normalized_unit = unit.lower().replace("sqm", "m2").replace("sq.m", "m2").replace("cu.m", "m3")
        else:
            # Try to infer unit from context or use empty
            normalized_unit = ""
        quantities.append({
            "value": float(value_clean),
            "unit": normalized_unit,
            "description": "original quantity"
        })

    # Pattern 3: Generic "X unit" numbers (fallback)
    if not quantities:
        generic_pattern = r"(\d+(?:[,.]?)\d*)\s+(m2|m3|m|sqm|sq\.m|cu\.m|nos|no|nr|set|item|day|days|kg|t|tonnes|litre|ml)"
        generic_matches = re.findall(generic_pattern, message, flags=re.IGNORECASE)
        for value, unit in generic_matches:
            value_clean = value.replace(",", "").replace(".", "", value.count(".") - 1) if value.count(".") > 1 else value.replace(",", "")
            normalized_unit = unit.lower().replace("sqm", "m2").replace("sq.m", "m2").replace("cu.m", "m3")
            quantities.append({
                "value": float(value_clean),
                "unit": normalized_unit,
                "description": "Extracted from user message"
            })

    return quantities


def _build_boq_candidates_from_matches(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert deterministic BOQ matches into frontend-friendly candidate format.
    """
    candidates = []

    for item in matches or []:
        if not isinstance(item, dict):
            continue

        item_ref = (
            item.get("item_reference")
            or item.get("item_number")
            or item.get("item_no")
            or item.get("item_ref")
            or item.get("code")
            or item.get("id")
        )

        candidates.append({
            "source_type": "boq",
            "source_id": str(item.get("id", item_ref or "boq")),
            "item_reference": str(item_ref) if item_ref is not None else None,
            "description": item.get("description", ""),
            "unit": item.get("unit"),
            "rate": item.get("rate"),
            "quantity": item.get("quantity"),
            "similarity_score": item.get("similarity_score", item.get("score", 0.75)),
            "confidence_score": item.get("confidence_score", 0.75),
            "reason": "Deterministic BOQ candidate from uploaded BOQ",
        })

    return candidates[:5]

@app.get("/")
def read_root():
    return {
        "message": "Hybrid Rule-Based and ML-Assisted Variation Evaluation Prototype",
        "version": "2.0.0",
        "status": "running",
        "description": "ML-assisted extraction + rule-based evaluation"
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/variation-types")
def get_variation_types():
    """Get all FIDIC variation types (Static for now)"""
    return {
        "variation_types": [
            {"id": 1, "code": "TYPE1", "name": "Quantity Changes", "evaluation_mode": "quantity_change", "description": "Changes in the quantity of any item of work included in the Contract"},
            {"id": 2, "code": "TYPE2", "name": "Quality/Characteristics Changes", "evaluation_mode": "substitution", "description": "Changes in the quality or other characteristics of any item of work"},
            {"id": 3, "code": "TYPE3", "name": "Levels/Positions/Dimensions Changes", "evaluation_mode": "quantity_change", "description": "Changes in the levels, positions and/or dimensions of any part of the Works"},
            {"id": 4, "code": "TYPE4", "name": "Omission of Work", "evaluation_mode": "omission", "description": "Omission of any work unless it is to be carried out by others"},
            {"id": 5, "code": "TYPE5", "name": "Additional Work/Plant/Materials", "evaluation_mode": "additional_work", "description": "Any additional work, Plant, Materials or services necessary for the Works"},
            {"id": 6, "code": "TYPE6", "name": "Sequence/Timing Changes", "evaluation_mode": "time_sequence_change", "description": "Changes to the sequence or timing of the execution of the Works"}
        ]
    }

# ============================================================================
# FILE UPLOAD ENDPOINTS
# ============================================================================

@app.post("/upload/files")
async def upload_files(
    boq: UploadFile = File(None),
    breakdown: UploadFile = File(None),
    schedule: UploadFile = File(None),
    storage: StorageManager = Depends(get_storage)
):
    """
    Upload core project files (BOQ, Rate Breakdown, Schedule)
    Supports Excel and CSV for BOQ/Schedule, PDF/Excel/CSV for Rate Breakdown
    """
    try:
        upload_dir = _runtime_path("uploaded_files")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Create Project
        proj_name = os.path.splitext(boq.filename)[0] if boq and boq.filename else f"Project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        project = storage.create_project(
            name=proj_name,
            boq_filename=boq.filename if boq else None,
            rate_breakdown_filename=breakdown.filename if breakdown else None,
            schedule_filename=schedule.filename if schedule else None
        )
        project_id = project["id"]
        
        # Initialize engines
        cost_engine = CostEngine(storage)
        time_engine = TimeEngine(storage=storage)
        
        # Initialize session manager and create default session
        session_manager = SessionManager(storage)
        session = session_manager.create_session(
            project_id=project_id,
            metadata={"created_via": "file_upload", "files_uploaded": []}
        )
        
        results = {
            "project_id": project_id,
            "session_id": session["id"],
            "session_key": session["session_key"],
            "boq_items": 0,
            "rate_breakdowns": 0,
            "schedule_tasks": 0,
            "processing_notes": []
        }
        
        # Process BOQ
        if boq:
            if not boq.filename:
                raise HTTPException(status_code=400, detail="BOQ filename is missing")
            path = os.path.join(upload_dir, boq.filename)
            with open(path, "wb") as buffer:
                shutil.copyfileobj(boq.file, buffer)
            
            # Validate BOQ
            validation = cost_engine.validate_boq_file(path)
            if not validation['valid']:
                os.remove(path)
                raise HTTPException(status_code=400, detail={
                    "message": f"BOQ Validation Failed for '{boq.filename}'",
                    "errors": validation['errors']
                })

            boq_data = cost_engine.load_boq(path, project_id) # Returns dict of sheets
            total_items = 0
            for sheet_name, items in boq_data.items():
                count = storage.add_boq_items(project_id, items, sheet_name)
                total_items += count
            
            results["boq_items"] = total_items
            results["processing_notes"].append(f"✓ BOQ processed: {total_items} items across {len(boq_data)} sheets")
            
            # Update session metadata
            session_manager.update_session_metadata(project_id, session["id"], {
                "files_uploaded": ["boq"]
            })
        
        # Process Rate Breakdown
        if breakdown:
            if not breakdown.filename:
                raise HTTPException(status_code=400, detail="Rate breakdown filename is missing")
            path = os.path.join(upload_dir, breakdown.filename)
            with open(path, "wb") as buffer:
                shutil.copyfileobj(breakdown.file, buffer)
            
            # Rate breakdown processing
            if ocr_processor.is_pdf(path):
                df = ocr_processor.process_pdf(path)
                if df is not None:
                    items = cost_engine.save_rate_breakdown_df(df, project_id)
                    if isinstance(items, list):
                        results["rate_breakdowns"] = storage.add_rate_breakdowns(project_id, items)
            else:
                items = cost_engine.load_rate_breakdown(path, project_id)
                if isinstance(items, list):
                    results["rate_breakdowns"] = storage.add_rate_breakdowns(project_id, items)
            
            results["processing_notes"].append(f"✓ Rate breakdown processed: {results['rate_breakdowns']} items")
        
        # Process Schedule
        if schedule:
            if not schedule.filename:
                raise HTTPException(status_code=400, detail="Schedule filename is missing")
            path = os.path.join(upload_dir, schedule.filename)
            with open(path, "wb") as buffer:
                shutil.copyfileobj(schedule.file, buffer)
            
            activities = time_engine.parse_schedule(path, project_id=project_id)
            print(f"[DEBUG] Parsed {len(activities)} activities from schedule")
            results["schedule_tasks"] = storage.add_activities(project_id, activities)
            print(f"[DEBUG] Added {results['schedule_tasks']} activities to project {project_id}")
            results["processing_notes"].append(f"✓ Schedule processed: {results['schedule_tasks']} activities")
        
        print(f"[DEBUG] Upload complete for project {project_id}. Summary: {results}")
        
        return {"status": "success", "data": results}
        
    except Exception as e:
        print(f"UPLOAD ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects")
def get_projects(storage: StorageManager = Depends(get_storage)):
    """List all projects"""
    return {"projects": storage.get_projects()}

@app.get("/debug/project/{project_id}")
def debug_project(project_id: int, storage: StorageManager = Depends(get_storage)):
    """
    Temporary debugging endpoint.
    Use this only during prototype testing to check whether uploaded data is stored.
    """
    project = storage.get_project(project_id)

    if not project:
        return {
            "status": "error",
            "message": f"Project {project_id} not found"
        }

    boq_items = project.get("boq_items", []) or []
    rate_breakdowns = project.get("rate_breakdowns", []) or []
    rate_sources = project.get("rate_sources", []) or []
    activities = project.get("activities", []) or []
    additional_files = project.get("additional_files", []) or []

    def contains_rb19(item):
        text = str(item).lower().replace(" ", "").replace("-", "/")
        return "rb/19" in text or "rb19" in text

    rb19_in_rate_breakdowns = [item for item in rate_breakdowns if contains_rb19(item)]
    rb19_in_rate_sources = [item for item in rate_sources if contains_rb19(item)]

    return {
        "status": "success",
        "project_id": project_id,
        "project_name": project.get("name"),
        "counts": {
            "boq_items": len(boq_items),
            "rate_breakdowns": len(rate_breakdowns),
            "rate_sources": len(rate_sources),
            "activities": len(activities),
            "additional_files": len(additional_files),
        },
        "sample_boq_items": boq_items[:3],
        "sample_rate_breakdowns": rate_breakdowns[:3],
        "sample_rate_sources": rate_sources[:5],
        "sample_activities": activities[:5],
        "additional_files": additional_files,
        "rb19_in_rate_breakdowns": rb19_in_rate_breakdowns[:5],
        "rb19_in_rate_sources": rb19_in_rate_sources[:5],
    }

@app.post("/upload/quotation")
async def upload_quotation(
    file: UploadFile = File(...)
):
    """
    Upload a vendor quotation (PDF, Excel, CSV)
    Extracts rates for use in Star Rate derivation.
    """
    try:
        upload_dir = _runtime_path("uploaded_files")
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = f"quotation_{int(datetime.now().timestamp())}_{file.filename}"
        path = os.path.join(upload_dir, filename)
        
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        extracted_data = []
        
        # Process based on file type
        if ocr_processor.is_pdf(path):
            df = ocr_processor.process_pdf(path, mode='quotation')
            if df is not None and not df.empty:
                extracted_data = df.to_dict('records')
        
        return {
            "status": "success",
            "filename": filename,
            "extracted_items_count": len(extracted_data),
            "preview": extracted_data[:5] if extracted_data else []
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload/additional-files")
async def upload_additional_files(
    project_id: int = Form(...),
    variation_id: Optional[str] = Form(None),
    file_type: str = Form(...),  # 'bsr', 'hsr', 'quotation', 'specification', 'drawing', 'rate_breakdown'
    files: List[UploadFile] = File(...),
    storage: StorageManager = Depends(get_storage)
):
    """Upload additional supporting files (BSR, HSR, Quotations, etc.)"""
    try:
        upload_dir = _runtime_path("uploaded_files", "additional")
        os.makedirs(upload_dir, exist_ok=True)
        
        uploaded_files = []
        extracted_rate_sources = []
        normalized_file_type = file_type.strip().lower()
        
        for file in files:
            # Save file
            file_path = os.path.join(upload_dir, f"{project_id}_{file.filename}")
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Create record in storage
            file_data = {
                "variation_id": variation_id,
                "filename": file.filename,
                "file_type": normalized_file_type,
                "file_path": file_path
            }
            storage.add_additional_file(project_id, file_data)

            file_record = {
                "filename": file.filename,
                "type": normalized_file_type,
                "size": os.path.getsize(file_path)
            }

            if normalized_file_type in {"bsr", "hsr", "quotation", "rate_breakdown"}:
                extracted_items = rate_source_extractor.extract_from_file(file_path, normalized_file_type, source_file=file.filename)
                if extracted_items:
                    stored_count = storage.add_rate_sources(project_id, extracted_items)
                    extracted_rate_sources.extend(extracted_items)
                    file_record["rate_sources_extracted"] = stored_count
                    file_record["preview"] = extracted_items[:5]
                else:
                    file_record["rate_sources_extracted"] = 0
                    file_record["preview"] = []

            uploaded_files.append(file_record)
        
        return {
            "status": "success",
            "files_uploaded": len(uploaded_files),
            "rate_sources_extracted": len(extracted_rate_sources),
            "preview": extracted_rate_sources[:5],
            "files": uploaded_files
        }
        
    except Exception as e:
        print(f"ADDITIONAL FILES UPLOAD ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

# ============================================================================
# SESSION MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/session/create")
def create_session(
    project_id: int,
    metadata: Optional[Dict] = None,
    storage: StorageManager = Depends(get_storage)
):
    """Create a new conversation session"""
    session_manager = SessionManager(storage)
    session = session_manager.create_session(project_id, metadata)
    return session

@app.get("/session/{project_id}/{session_id}")
def get_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    """Get session context"""
    session_manager = SessionManager(storage)
    context = session_manager.get_session_context(project_id, session_id)
    if not context:
        raise HTTPException(status_code=404, detail="Session not found")
    return context

@app.post("/session/{project_id}/{session_id}/continue")
def continue_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    """Continue an existing session"""
    session_manager = SessionManager(storage)
    try:
        context = session_manager.continue_session(project_id, session_id)
        return {"status": "success", "context": context}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/session/{project_id}/{session_id}/close")
def close_session(project_id: int, session_id: int, storage: StorageManager = Depends(get_storage)):
    """Close/complete a session"""
    session_manager = SessionManager(storage)
    success = session_manager.close_session(project_id, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "success", "message": "Session closed"}

# ============================================================================
# CHAT ENDPOINT (Enhanced with FIDIC Workflow)
# ============================================================================

class ChatRequest(pydantic.BaseModel):
    message: str
    project_id: int
    session_id: Optional[int] = None

@app.post("/chat")
async def chat(request: ChatRequest, storage: StorageManager = Depends(get_storage)):
    """
    Enhanced chat endpoint with FIDIC workflow support
    """
    import sys
    print(f"[CHAT-ENDPOINT] Called for project {request.project_id}", file=sys.stderr, flush=True)
    sys.stderr.flush()
    
    try:
        _append_runtime_log("backend", "data", "debug.log", message=f"[CHAT-ENDPOINT] Called for project {request.project_id}\n")
        
        # Initialize managers and engines
        session_manager = SessionManager(storage)
        cost_engine = CostEngine(storage)
        time_engine = TimeEngine(storage=storage)
        
        # Get or create session
        project_id = request.project_id
        if request.session_id:
            session = session_manager.get_session(project_id, request.session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            session = session_manager.create_session(project_id)
        
        session_id = session["id"]
        
        # Save user message
        session_manager.add_message(project_id, session_id, "user", request.message)
        
        # Get conversation history
        history = session_manager.get_conversation_history(project_id, session_id, limit=10)
        
        # 2. Enrich Context for AI
        cost_engine.train_model(project_id)
        session_metadata = session.get("session_metadata", {})
        collected_details = session_metadata.get('collected_details', {})
        
        search_query = request.message
        if len(request.message.split()) < 4:
            affected_items = collected_details.get('affected_items', [])
            if affected_items:
                search_query += " " + " ".join(affected_items)
            user_history = [m['content'] for m in history if m['role'] == 'user'][-3:]
            search_query += " " + " ".join(user_history)

        # Get relevant BOQ items
        relevant_matches = cost_engine.ml_model.find_similar_items(search_query, top_n=20)
        
        project = storage.get_project(project_id)
        # storage.get_project may return None; guard against that
        if not project:
            project = {}
        proj_name = project.get("name", "Unknown Project")
        
        context_str = f"PROJECT NAME: {proj_name}\n"
        context_str += "AVAIALBLE BOQ ITEMS (Top Matches):\n"
        if relevant_matches:
            context_str += "\n".join([f"- {i.get('description')} (Ref: {i.get('item_number')}, Rate: {i.get('rate')}, Qty: {i.get('quantity')})" for i in relevant_matches if i])
        
        # Get relevant activities (with normalization mapping if provided)
        activities = project.get("activities", [])
        activity_debug = f"[CHAT] Project {project_id} has {len(activities)} activities\n"
        if activities:
            activity_debug += f"[CHAT] Sample: {[a.get('activity_id') or a.get('id') for a in activities[:3]]}\n"
            activity_debug += f"[CHAT] Sample: {[a.get('activity_id') or a.get('id') for a in activities[:3]]}\n"
        _append_runtime_log("backend", "data", "debug.log", message=activity_debug)
        normalization_map = load_keyword_normalization_map(project)
        keywords = tokenize_for_matching(search_query, mapping=normalization_map)
        relevant_activities = [
            activity for activity in activities
            if tokens_contained(activity.get('name', ''), keywords, mapping=normalization_map)
        ]
        
        context_str += "\n\nAVAIALBLE ACTIVITIES (Top Matches):\n"
        if relevant_activities:
            context_str += "\n".join([f"- {a.get('name')} (Duration: {a.get('duration')}d, Critical: {a.get('is_critical')})" for a in relevant_activities[:10]])
        else:
            context_str += "\n".join([f"- {a.get('name')} (Duration: {a.get('duration')}d, Critical: {a.get('is_critical')})" for a in activities[:5]])
        
        # 3. Parse instruction with workflow support
        ai_result = cost_engine.ml_model.parse_instruction(
            request.message,
            project_context=context_str,
            chat_history=history,
            session_metadata=session_metadata
        )
        
        if not ai_result:
            return {"reply": "Connection error with AI service.", "proposal": None, "session_id": session_id}
        
        response_text = ai_result.get('reply', "How can I help you today?")
        workflow_state = ai_result.get('workflow_state')

        final_variation_type, final_evaluation_mode = _infer_variation_type_and_mode(
            request.message,
            ai_result,
        )

        extracted_quantities = (
            ai_result.get("extracted_quantities")
            or _extract_quantities_from_message(request.message)
        )

        detected_unit = ai_result.get("unit")
        if not detected_unit and extracted_quantities:
            detected_unit = extracted_quantities[0].get("unit")

        # Use AI BOQ candidates if available and complete; otherwise use deterministic BOQ search matches.
        affected_boq_candidates = ai_result.get("affected_boq_candidates", []) or []
        
        # If AI candidates are returned but incomplete (e.g., only description, no quantity/rate),
        # fall back to deterministic matching or enrich with project data
        if affected_boq_candidates:
            # Check if candidates have quantity/rate data
            has_full_data = any(c.get('quantity') or c.get('rate') for c in affected_boq_candidates if isinstance(c, dict))
            if not has_full_data:
                # AI returned minimal candidates, try to enrich or fall back to deterministic
                ai_descriptions = [c.get('description', '') for c in affected_boq_candidates if isinstance(c, dict)]
                if ai_descriptions:
                    # Try deterministic match using AI's extracted descriptions
                    det_matches = cost_engine.ml_model.find_similar_items(ai_descriptions[0], top_n=5)
                    if det_matches:
                        affected_boq_candidates = det_matches
                    else:
                        # Keep AI candidates, will be normalized to empty fields
                        pass
                else:
                    # No descriptions from AI, use deterministic
                    affected_boq_candidates = _build_boq_candidates_from_matches(relevant_matches)
        else:
            # No AI candidates, use deterministic
            affected_boq_candidates = _build_boq_candidates_from_matches(relevant_matches)

        original_boq_ref = _extract_first_candidate_ref(affected_boq_candidates)

        # Pass selected BOQ item for better activity matching context
        selected_boq = affected_boq_candidates[0] if affected_boq_candidates else None
        _append_runtime_log("debug_activities.log", message=f"[CANDIDATES] Building activity candidates with {len(activities)} activities\n")
        deterministic_activity_candidates = _build_activity_candidates(
            search_query,
            activities,
            normalization_map,
            selected_boq_item=selected_boq,
        )

        merged_activity_candidates = _merge_activity_candidates(
            [],  # Skip AI activity candidates - use deterministic only
            deterministic_activity_candidates,
        )
        
        # Enrich activity candidates with actual project data
        merged_activity_candidates = _enrich_activity_candidates_with_project_data(
            merged_activity_candidates,
            activities
        )

        rate_query = _build_rate_query(
            request.message,
            ai_result,
            final_variation_type,
            final_evaluation_mode,
        )

        exclude_boq_ref = (
            original_boq_ref
            if final_variation_type == "TYPE2" or final_evaluation_mode == "substitution"
            else None
        )

        # First priority: exact rate reference from uploaded rate sources.
        # Example: RB/19 should directly select RB/19 from the uploaded rate breakdown.
        explicit_rate_ref = _extract_rate_reference_from_text(request.message)
        direct_rate_candidate = _find_rate_source_by_reference(project, explicit_rate_ref)

        if direct_rate_candidate:
            rate_candidates = {
                "status": "candidates_found",
                "selected_candidate": direct_rate_candidate,
                "candidates": [direct_rate_candidate],
                "missing_information": [],
            }
        else:
            rate_candidates = rate_resolver.resolve_rate(
                project_id,
                rate_query,
                unit=detected_unit,
                preferred_work_type=project.get("work_type", "building") if project else "building",
                exclude_boq_ref=exclude_boq_ref,
            )

        proposal_data = None

        # Handle workflow states
        if workflow_state == "type_selection":
            suggested_type = ai_result.get('suggested_type')
            if suggested_type:
                session_manager.update_session_metadata(project_id, session_id, {"variation_type": suggested_type})
        
        elif workflow_state == "collecting_details":
            extracted_data = ai_result.get('extracted_data', {})
            current_details = session_metadata.get('collected_details', {})
            current_details.update({k: v for k, v in extracted_data.items() if v is not None})
            
            session_manager.update_session_metadata(project_id, session_id, {"collected_details": current_details})
            
            # IMPORTANT: Do NOT automatically evaluate. Wait for human confirmation.
            # User must call POST /variation/confirm-and-evaluate with confirmed data.

        # Save AI response
        session_manager.add_message(project_id, session_id, "ai", response_text, metadata={
            "workflow_state": workflow_state,
            "has_proposal": proposal_data is not None
        })
        
        # FINAL FALLBACK BEFORE RESPONSE:
        # If a rate reference such as RB/19 exists in the user message,
        # force-search the freshly stored project rate sources.
        if not rate_candidates.get("selected_candidate"):
            fresh_project = storage.get_project(project_id) or project

            ref_match = re.search(
                r"\b(?:rb|bsr|hsr|q|qt|quo|quotation)[\s/.-]*[a-z0-9-]+\b",
                request.message,
                flags=re.IGNORECASE,
            )

            if ref_match and fresh_project:
                target_ref = re.sub(r"[^a-z0-9]", "", ref_match.group(0).lower())

                all_sources = []
                all_sources.extend(fresh_project.get("rate_sources", []) or [])
                all_sources.extend(fresh_project.get("rate_breakdowns", []) or [])

                for source in all_sources:
                    if not isinstance(source, dict):
                        continue

                    source_text = " ".join(
                        str(value or "")
                        for value in [
                            source.get("item_reference"),
                            source.get("item_ref"),
                            source.get("item_number"),
                            source.get("code"),
                            source.get("ref"),
                            source.get("description"),
                            source.get("raw_text_excerpt"),
                            source.get("source_id"),
                            source.get("id"),
                        ]
                    )

                    normalized_source_text = re.sub(r"[^a-z0-9]", "", source_text.lower())

                    if target_ref and target_ref in normalized_source_text:
                        selected = {
                            "source_priority": 0,
                            "source_type": source.get("source_type") or "rate_breakdown",
                            "source_id": str(source.get("id") or source.get("item_reference") or ref_match.group(0)),
                            "source_file": source.get("source_file"),
                            "page_number": source.get("page_number"),
                            "item_reference": source.get("item_reference") or ref_match.group(0).upper(),
                            "description": source.get("description") or "",
                            "unit": source.get("unit"),
                            "rate": source.get("rate") or source.get("unit_rate") or source.get("total_rate"),
                            "similarity_score": 1.0,
                            "confidence_score": 0.99,
                            "reason": "Exact rate reference matched from uploaded rate sources immediately before response",
                        }

                        rate_candidates = {
                            "status": "candidates_found",
                            "selected_candidate": selected,
                            "candidates": [selected],
                            "missing_information": [],
                        }
                        break

        # Normalize candidates for consistent response structure
        normalized_boq_candidates = []
        for c in affected_boq_candidates:
            if isinstance(c, dict):
                normalized = _normalize_boq_candidate(c)
                normalized_boq_candidates.append(normalized)
        
        normalized_activity_candidates = [_normalize_activity_candidate(c) for c in merged_activity_candidates if isinstance(c, dict)]

        return {     
            "reply": response_text,
            "proposal": proposal_data,
            "session_id": session_id,
            "workflow_state": workflow_state,
            "requires_human_confirmation": True,

            "variation_type": final_variation_type,
            "evaluation_mode": final_evaluation_mode,
            "unit": detected_unit,
            "extracted_quantities": extracted_quantities,

            "rate_candidates": rate_candidates.get("candidates", []),
            "selected_rate_candidate": rate_candidates.get("selected_candidate"),
            "affected_boq_candidates": normalized_boq_candidates,
            "affected_activity_candidates": normalized_activity_candidates,
        }
        
    except Exception as e:
        import traceback
        _append_runtime_log("backend", "data", "debug.log", message=f"[ERROR] {e}\n{traceback.format_exc()}")
        print(f"CHAT ERROR: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

# ============================================================================
# VARIATION MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/variation/{project_id}/{variation_id}")
def get_variation(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    """Get variation details"""
    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    return variation

@app.post("/variation/validate/{project_id}/{variation_id}")
def validate_variation(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    """Run QS validation checks on a variation"""
    validator = ValidationEngine(storage)
    project = storage.get_project(project_id)
    variation = storage.get_variation(project_id, variation_id)
    if not project or not variation:
        raise HTTPException(status_code=404, detail="Project or variation not found")
    
    cost_impact = variation.get("cost_impact", 0)
    time_impact = variation.get("time_impact", 0)
    
    results = validator.validate_variation(project, variation, cost_impact, time_impact)
    return results

@app.get("/variation/validation-report/{project_id}/{variation_id}")
def get_validation_report(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    """Get formatted validation report"""
    validator = ValidationEngine(storage)
    report = validator.generate_validation_report(project_id, variation_id)
    return {"report": report}

@app.put("/variation/{project_id}/{variation_id}/details/{detail_id}")
def update_variation_detail_endpoint(
    project_id: int,
    variation_id: int, 
    detail_id: int, 
    updates: dict,
    storage: StorageManager = Depends(get_storage)
):
    """Update a specific variation detail line item"""
    cost_engine = CostEngine(storage)
    updated_detail = cost_engine.update_variation_detail(project_id, variation_id, detail_id, updates)
    
    if not updated_detail:
        raise HTTPException(status_code=404, detail="Variation detail not found")
        
    return {"status": "success", "detail_id": detail_id, "message": "Detail updated"}

@app.post("/variation/{project_id}/{variation_id}/status")
def update_variation_status(
    project_id: int,
    variation_id: int,
    status: str = Body(..., embed=True),
    storage: StorageManager = Depends(get_storage)
):
    """Update variation status (Approved, Rejected, Under Review)"""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    found = False
    for v in project.get("variations", []):
        if v["id"] == variation_id:
            if status not in ["Draft", "Under Review", "Approved", "Rejected"]:
                raise HTTPException(status_code=400, detail="Invalid status")
            v["status"] = status
            v["updated_at"] = datetime.utcnow().isoformat()
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Variation not found")
        
    storage.update_project(project_id, {"variations": project["variations"]})
    return {"status": "success", "variation_id": variation_id, "new_status": status}

# ============================================================================
# VARIATION EVALUATION ENDPOINT (Human Confirmation Required)
# ============================================================================

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

    # Required for TYPE2 substitution where original BOQ lookup may fail
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

@app.post("/variation/{project_id}/confirm-and-evaluate")
async def confirm_and_evaluate(
    project_id: int,
    request: ConfirmEvaluateRequest,
    storage: StorageManager = Depends(get_storage)
):
    """
    Final step: Human-confirmed evaluation using deterministic rule-based logic.
    IMPORTANT: Validates all required fields before proceeding with evaluation.
    """
    try:
        if not request.human_confirmed:
            raise HTTPException(
                status_code=400,
                detail="Variation evaluation requires explicit human confirmation (human_confirmed=true)"
            )

        # VALIDATION: Check required fields based on variation type
        missing_fields = []
        
        # All types require these
        if not request.variation_type:
            missing_fields.append("variation_type")
        if not request.evaluation_mode:
            missing_fields.append("evaluation_mode")
        if not request.unit:
            missing_fields.append("unit")
        if request.confirmed_rate is None or request.confirmed_rate == "":
            missing_fields.append("confirmed_rate")
        if not request.confirmed_rate_source:
            missing_fields.append("confirmed_rate_source")

        # TYPE-SPECIFIC validations
        if request.variation_type == "TYPE1":
            if not request.original_boq_item_ref:
                missing_fields.append("original_boq_item_ref")
            if request.original_quantity is None or request.original_quantity == "":
                missing_fields.append("original_quantity")
            if request.new_quantity is None or request.new_quantity == "":
                missing_fields.append("new_quantity")
        
        elif request.variation_type == "TYPE2":
            if not request.original_boq_item_ref:
                missing_fields.append("original_boq_item_ref")
            if request.original_quantity is None or request.original_quantity == "":
                missing_fields.append("original_quantity")
            if not request.replacement_item_ref and not request.replacement_description:
                missing_fields.append("replacement_item_ref or replacement_description")
            if request.replacement_quantity is None or request.replacement_quantity == "":
                missing_fields.append("replacement_quantity")
        
        elif request.variation_type == "TYPE4":
            if not request.original_boq_item_ref:
                missing_fields.append("original_boq_item_ref")
            if request.original_quantity is None or request.original_quantity == "":
                missing_fields.append("original_quantity")
        
        elif request.variation_type == "TYPE5":
            if not request.replacement_item_ref and not request.replacement_description:
                missing_fields.append("replacement_item_ref or replacement_description")
            if request.replacement_quantity is None or request.replacement_quantity == "":
                missing_fields.append("replacement_quantity")

        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Missing required fields for evaluation",
                    "missing_fields": missing_fields,
                    "message": f"Please complete the following fields before evaluation: {', '.join(missing_fields)}"
                }
            )

        project = storage.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project = _safe_dict(project)

        session_manager = SessionManager(storage)
        session = session_manager.get_session(project_id, request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        request_data = request.model_dump()

        variation_data = {
            "project_id": project_id,
            "project_name": request.project_name,
            "session_id": request.session_id,
            "variation_type": request.variation_type,
            "evaluation_mode": request.evaluation_mode,
            "original_boq_item_ref": request.original_boq_item_ref,
            "replacement_item_ref": request.replacement_item_ref,
            "original_description": request.original_description,
            "replacement_description": request.replacement_description,
            "original_quantity": request.original_quantity,
            "new_quantity": request.new_quantity,
            "replacement_quantity": request.replacement_quantity,
            "unit": request.unit,
            "original_rate": request.original_rate,
            "confirmed_rate": request.confirmed_rate,
            "confirmed_rate_source": request.confirmed_rate_source,
            "confirmed_rate_source_id": request.confirmed_rate_source_id,
            "confirmed_activity_ref": request.confirmed_activity_ref,
            "confirmed_productivity": request.confirmed_productivity,
            "productivity_source": request.productivity_source,
            "supporting_documents": request.supporting_documents,
            "engineer_instruction_ref": request.engineer_instruction_ref,
            "original_drawing_ref": request.original_drawing_ref,
            "revised_drawing_ref": request.revised_drawing_ref,
            "human_confirmed": True,
            "status": "Under Review",
        }

        variation = storage.add_variation(project_id, request.session_id, variation_data)

        if isinstance(variation, dict):
            variation_id = variation.get("id")
        else:
            variation_id = variation

        if not variation_id:
            raise HTTPException(status_code=500, detail="Failed to create variation record")

        evaluation_result = variation_evaluator.evaluate_confirmed_variation(project_id, request_data)
        evaluation_result = _safe_dict(evaluation_result)

        variation_updates = {
            **variation_data,
            **evaluation_result,
            "status": "Calculated",
            "updated_at": datetime.utcnow().isoformat(),
        }

        updated_variation = storage.update_variation(project_id, variation_id, variation_updates)
        variation = updated_variation if isinstance(updated_variation, dict) else {**variation_data, "id": variation_id, **evaluation_result}

        proposal_data = _build_variation_proposal_data(project, variation, evaluation_result)

        output_dir = _runtime_path("backend", "generated_reports")
        os.makedirs(output_dir, exist_ok=True)

        pdf_url = None
        docx_url = None

        # Generate PDF
        try:
            pdf_path = PDFGenerator.generate_variation_proposal(
                proposal_data,
                os.path.join(output_dir, f"variation_proposal_{variation_id}.pdf"),
            )
            pdf_url = f"/download/{os.path.basename(pdf_path)}"
        except Exception as e:
            print(f"PDF generation failed: {e}")

        # Generate DOCX
        try:
            docx_path = DOCXGenerator.generate_variation_proposal(
                proposal_data,
                os.path.join(output_dir, f"variation_proposal_{variation_id}.docx"),
            )
            docx_url = f"/download/{os.path.basename(docx_path)}"
        except Exception as e:
            print(f"DOCX generation failed: {e}")

        storage.update_variation(project_id, variation_id, {
            "pdf_url": pdf_url,
            "docx_url": docx_url,
            "pdf_path": os.path.join(output_dir, f"variation_proposal_{variation_id}.pdf") if pdf_url else None,
            "docx_path": os.path.join(output_dir, f"variation_proposal_{variation_id}.docx") if docx_url else None,
        })

        return {
            "status": "success",
            "variation_id": variation_id,
            "cost_lines": evaluation_result.get("cost_lines", []),
            "total_cost_impact": evaluation_result.get("total_cost_impact", 0.0),
            "time_impact": evaluation_result.get("time_impact", {}),
            "validation": evaluation_result.get("validation", {}),
            "pdf_url": pdf_url,
            "docx_url": docx_url,
            "proposal": proposal_data,
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"EVALUATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
# ============================================================================
# PDF GENERATION ENDPOINT
# ============================================================================

@app.post("/generate-pdf")
async def generate_pdf(request: dict):
    """Generate variation proposal PDF"""
    try:
        output_dir = _runtime_path("backend", "generated_reports")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"variation_proposal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        pdf_path = PDFGenerator.generate_variation_proposal(request, output_path)
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"Variation_Proposal_{request.get('variation_id', 'draft')}.pdf"
        )
    except Exception as e:
        print(f"PDF GENERATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/variation/{project_id}/{variation_id}/generate-docx")
async def generate_variation_docx(project_id: int, variation_id: int, storage: StorageManager = Depends(get_storage)):
    """Generate an editable DOCX report for a stored variation."""
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project = _safe_dict(project)

    variation = storage.get_variation(project_id, variation_id)
    if not variation:
        raise HTTPException(status_code=404, detail="Variation not found")
    variation = _safe_dict(variation)

    evaluation_result = {
        "cost_lines": variation.get("cost_lines", []),
        "total_cost_impact": variation.get("total_cost_impact", 0.0),
        "time_impact": variation.get("time_impact", {}),
        "validation": variation.get("validation", {}),
        "formula_summary": variation.get("formula_summary", []),
        "assumptions": variation.get("assumptions", []),
    }

    proposal_data = _build_variation_proposal_data(project, variation, evaluation_result)

    try:
        output_dir = _runtime_path("backend", "generated_reports")
        os.makedirs(output_dir, exist_ok=True)
        docx_path = DOCXGenerator.generate_variation_proposal(
            proposal_data,
            os.path.join(output_dir, f"variation_proposal_{variation_id}.docx")
        )
        return FileResponse(
            docx_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"Variation_Proposal_{variation_id}.docx"
        )
    except Exception as e:
        print(f"DOCX GENERATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/download/{filename}")
async def download_file(filename: str):
    """Serve generated PDF/DOCX files for download."""
    safe_filename = os.path.basename(filename)

    allowed_extensions = [".pdf", ".docx"]
    if not any(safe_filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(status_code=400, detail="Only PDF and DOCX downloads are allowed")

    file_path = _runtime_path("backend", "generated_reports", safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    if safe_filename.lower().endswith(".pdf"):
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=safe_filename
    )

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
