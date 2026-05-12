from __future__ import annotations

from typing import Any, Dict, List, Optional

from .rate_resolver import RateResolver
from .storage_manager import StorageManager, storage_manager
from .validation_engine import ValidationEngine


class VariationEvaluator:
    def __init__(self, storage: Optional[StorageManager] = None):
        self.storage = storage or storage_manager
        self.rate_resolver = RateResolver(self.storage)
        self.validation_engine = ValidationEngine(self.storage)

    def evaluate_confirmed_variation(self, project_id: int, request_data: Dict[str, Any]) -> Dict[str, Any]:
        if not request_data.get("human_confirmed"):
            raise ValueError("human_confirmed must be true before evaluation")

        project = self.storage.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        variation_type = str(request_data.get("variation_type", "")).upper().strip()
        evaluation_mode = str(request_data.get("evaluation_mode", "")).strip().lower()

        # Fallback mapping if frontend sends variation type but not evaluation mode
        if not evaluation_mode:
            evaluation_mode = {
                "TYPE1": "quantity_change",
                "TYPE2": "substitution",
                "TYPE3": "quantity_change",
                "TYPE4": "omission",
                "TYPE5": "additional_work",
                "TYPE6": "time_sequence_change",
            }.get(variation_type, "quantity_change")

        original_quantity = self._to_float(request_data.get("original_quantity"), None)
        new_quantity = self._to_float(request_data.get("new_quantity"), None)
        replacement_quantity = self._to_float(request_data.get("replacement_quantity"), None)

        confirmed_rate = self._to_float(request_data.get("confirmed_rate"), None)
        original_rate_from_request = self._to_float(request_data.get("original_rate"), None)
        confirmed_productivity = self._to_float(request_data.get("confirmed_productivity"), None)

        original_ref = self._normalize(request_data.get("original_boq_item_ref"))
        replacement_ref = self._normalize(request_data.get("replacement_item_ref"))

        confirmed_rate_source = self._normalize(request_data.get("confirmed_rate_source"))
        confirmed_rate_source_id = self._normalize(request_data.get("confirmed_rate_source_id"))

        original_boq = self.storage.get_boq_item(project_id, original_ref) if original_ref else None
        replacement_boq = self.storage.get_boq_item(project_id, replacement_ref) if replacement_ref else None

        original_description = self._description_for(original_boq, request_data.get("original_description"))
        replacement_description = self._description_for(replacement_boq, request_data.get("replacement_description"))

        unit = self._unit_for(original_boq or replacement_boq, request_data.get("unit"))

        cost_lines: List[Dict[str, Any]] = []
        formula_summary: List[str] = []
        manual_confirmation_required = False

        # ---------- COST EVALUATION ----------
        if evaluation_mode == "quantity_change":
            if original_quantity is None or new_quantity is None:
                manual_confirmation_required = True

            rate = confirmed_rate if confirmed_rate is not None else self._extract_rate(original_boq)

            if rate is None or original_quantity is None or new_quantity is None:
                manual_confirmation_required = True
            else:
                qty_delta = new_quantity - original_quantity
                amount = qty_delta * rate
                formula = f"({new_quantity} - {original_quantity}) x {rate}"

                cost_lines.append(self._build_cost_line(
                    line_type="quantity_change",
                    description=original_description,
                    quantity=qty_delta,
                    unit=unit,
                    rate=rate,
                    rate_source=confirmed_rate_source or f"BOQ Item {original_ref}",
                    rate_source_id=confirmed_rate_source_id or original_ref or self._source_id_from_item(original_boq),
                    formula=formula,
                    amount=amount,
                    used_rate_source={
                        "source_type": "BOQ" if (confirmed_rate_source or "").lower().startswith("boq") or original_ref else "confirmed",
                        "source_file": "",
                        "item_reference": confirmed_rate_source_id or original_ref or self._source_id_from_item(original_boq),
                        "description": original_description,
                        "unit": unit,
                        "rate": rate,
                        "confidence": "Human confirmed",
                    }
                ))
                formula_summary.append(f"Quantity change: {formula} = {amount}")

        elif evaluation_mode == "omission" or variation_type == "TYPE4":
            if original_quantity is None:
                manual_confirmation_required = True

            rate = confirmed_rate if confirmed_rate is not None else self._extract_rate(original_boq)

            if rate is None or original_quantity is None:
                manual_confirmation_required = True
            else:
                amount = (0 - original_quantity) * rate
                formula = f"(0 - {original_quantity}) x {rate}"

                cost_lines.append(self._build_cost_line(
                    line_type="omission",
                    description=original_description,
                    quantity=original_quantity,
                    unit=unit,
                    rate=rate,
                    rate_source=confirmed_rate_source or f"BOQ Item {original_ref}",
                    rate_source_id=confirmed_rate_source_id or original_ref or self._source_id_from_item(original_boq),
                    formula=formula,
                    amount=amount,
                    used_rate_source={
                        "source_type": "BOQ",
                        "source_file": "",
                        "item_reference": confirmed_rate_source_id or original_ref or self._source_id_from_item(original_boq),
                        "description": original_description,
                        "unit": unit,
                        "rate": rate,
                        "confidence": "Human confirmed",
                    }
                ))
                formula_summary.append(f"Omission: {formula} = {amount}")

        elif evaluation_mode == "substitution" or variation_type == "TYPE2":
            if original_quantity is None:
                manual_confirmation_required = True

            if replacement_quantity is None:
                # For most Type 2 substitutions, replacement quantity is same as original quantity
                replacement_quantity = original_quantity

            original_rate = original_rate_from_request if original_rate_from_request is not None else self._extract_rate(original_boq)
            replacement_rate = confirmed_rate if confirmed_rate is not None else self._extract_rate(replacement_boq)

            if original_rate is None or replacement_rate is None or original_quantity is None or replacement_quantity is None:
                manual_confirmation_required = True
            else:
                omission_amount = (0 - original_quantity) * original_rate
                addition_amount = replacement_quantity * replacement_rate

                omission_formula = f"(0 - {original_quantity}) x {original_rate}"
                addition_formula = f"{replacement_quantity} x {replacement_rate}"

                cost_lines.append(self._build_cost_line(
                    line_type="omission",
                    description=original_description,
                    quantity=original_quantity,
                    unit=unit,
                    rate=original_rate,
                    rate_source=f"BOQ Item {original_ref}",
                    rate_source_id=original_ref or self._source_id_from_item(original_boq),
                    formula=omission_formula,
                    amount=omission_amount,
                    used_rate_source={
                        "source_type": "BOQ",
                        "source_file": "",
                        "item_reference": original_ref or self._source_id_from_item(original_boq),
                        "description": original_description,
                        "unit": unit,
                        "rate": original_rate,
                        "confidence": "Human confirmed",
                    }
                ))

                cost_lines.append(self._build_cost_line(
                    line_type="addition",
                    description=replacement_description or "Replacement item",
                    quantity=replacement_quantity,
                    unit=unit,
                    rate=replacement_rate,
                    rate_source=confirmed_rate_source or "Confirmed replacement source",
                    rate_source_id=confirmed_rate_source_id or replacement_ref or self._source_id_from_item(replacement_boq),
                    formula=addition_formula,
                    amount=addition_amount,
                    used_rate_source={
                        "source_type": self._source_type_from_text(confirmed_rate_source),
                        "source_file": "",
                        "item_reference": confirmed_rate_source_id or replacement_ref or self._source_id_from_item(replacement_boq),
                        "description": replacement_description or "Replacement item",
                        "unit": unit,
                        "rate": replacement_rate,
                        "confidence": "Human confirmed",
                    }
                ))

                formula_summary.append(f"Substitution omission: {omission_formula} = {omission_amount}")
                formula_summary.append(f"Substitution addition: {addition_formula} = {addition_amount}")
                formula_summary.append(f"Net substitution impact = {addition_amount} + ({omission_amount}) = {addition_amount + omission_amount}")

        elif evaluation_mode == "additional_work" or variation_type == "TYPE5":
            qty = new_quantity if new_quantity is not None else replacement_quantity

            if qty is None:
                manual_confirmation_required = True

            rate = confirmed_rate if confirmed_rate is not None else self._extract_rate(replacement_boq or original_boq)

            if rate is None or qty is None:
                manual_confirmation_required = True
            else:
                amount = qty * rate
                formula = f"{qty} x {rate}"

                cost_lines.append(self._build_cost_line(
                    line_type="addition",
                    description=replacement_description or original_description or "Additional work",
                    quantity=qty,
                    unit=unit,
                    rate=rate,
                    rate_source=confirmed_rate_source or "Confirmed rate source",
                    rate_source_id=confirmed_rate_source_id or replacement_ref or original_ref,
                    formula=formula,
                    amount=amount,
                    used_rate_source={
                        "source_type": self._source_type_from_text(confirmed_rate_source),
                        "source_file": "",
                        "item_reference": confirmed_rate_source_id or replacement_ref or original_ref,
                        "description": replacement_description or original_description or "Additional work",
                        "unit": unit,
                        "rate": rate,
                        "confidence": "Human confirmed",
                    }
                ))
                formula_summary.append(f"Additional work: {formula} = {amount}")

        else:
            manual_confirmation_required = True

        total_cost_impact = sum(float(line.get("amount", 0.0)) for line in cost_lines)

        # ---------- TIME EVALUATION ----------
        time_impact = self._evaluate_time_impact(
            project_id=project_id,
            request_data=request_data,
            evaluation_mode=evaluation_mode,
            variation_type=variation_type,
            original_quantity=original_quantity,
            new_quantity=new_quantity,
            replacement_quantity=replacement_quantity,
            confirmed_productivity=confirmed_productivity
        )

        # ---------- VALIDATION ----------
        validation = self.validation_engine.validate_confirmed_variation(project, request_data, {
            "cost_lines": cost_lines,
            "total_cost_impact": total_cost_impact,
            "time_impact": time_impact,
            "manual_confirmation_required": manual_confirmation_required,
        })

        if not isinstance(validation, dict):
            validation = {"valid": False, "warnings": [str(validation)], "errors": []}

        if time_impact.get("manual_required"):
            validation.setdefault("warnings", [])
            message = time_impact.get("message") or "Time impact cannot be finalised because activity/productivity information is missing."
            if message not in validation["warnings"]:
                validation["warnings"].append(message)

        return {
            "cost_lines": cost_lines,
            "total_cost_impact": float(total_cost_impact),
            "time_impact": time_impact,
            "validation": validation,
            "formula_summary": formula_summary,
            "manual_confirmation_required": manual_confirmation_required,
        }

    def _evaluate_time_impact(
        self,
        project_id: int,
        request_data: Dict[str, Any],
        evaluation_mode: str,
        variation_type: str,
        original_quantity: Optional[float],
        new_quantity: Optional[float],
        replacement_quantity: Optional[float],
        confirmed_productivity: Optional[float],
    ) -> Dict[str, Any]:

        activity_ref = self._normalize(
            request_data.get("confirmed_activity_ref")
            or request_data.get("confirmed_activity_id")
            or request_data.get("activity_ref")
            or request_data.get("activity_id")
        )

        productivity_source = self._normalize(request_data.get("productivity_source"))

        if not activity_ref:
            return {
                "activity_ref": "",
                "activity_name": "",
                "productivity": confirmed_productivity,
                "productivity_source": productivity_source,
                "additional_duration": 0,
                "is_critical": False,
                "original_float": 0,
                "delay_absorbed_by_float": False,
                "eot_days": 0,
                "formula": "",
                "manual_required": True,
                "cpm_proof": False,
                "message": "Time impact cannot be finalised because activity mapping is missing."
            }

        if confirmed_productivity is None or confirmed_productivity <= 0:
            return {
                "activity_ref": activity_ref,
                "activity_name": "",
                "productivity": confirmed_productivity,
                "productivity_source": productivity_source,
                "additional_duration": 0,
                "is_critical": False,
                "original_float": 0,
                "delay_absorbed_by_float": False,
                "eot_days": 0,
                "formula": "",
                "manual_required": True,
                "cpm_proof": False,
                "message": "Time impact cannot be finalised because productivity evidence is missing."
            }

        activity = self.storage.get_activity(project_id, activity_ref)
        activity = activity if isinstance(activity, dict) else {}
        activity_found = bool(activity)

        activity_name = (
            activity.get("name")
            or activity.get("activity_name")
            or activity.get("task_name")
            or f"Activity {activity_ref}"
        )

        is_critical = self._is_critical(activity)
        original_float = self._activity_float(activity)

        if evaluation_mode == "omission" or variation_type == "TYPE4":
            additional_duration = 0.0
            formula = "Omission does not create additional duration"

        elif evaluation_mode == "substitution" or variation_type == "TYPE2":
            qty_for_time = replacement_quantity if replacement_quantity is not None else original_quantity

            if qty_for_time is None:
                return {
                    "activity_ref": activity_ref,
                    "activity_name": activity_name,
                    "productivity": confirmed_productivity,
                    "productivity_source": productivity_source,
                    "additional_duration": 0,
                    "is_critical": is_critical,
                    "original_float": original_float,
                    "delay_absorbed_by_float": False,
                    "eot_days": 0,
                    "formula": "",
                    "manual_required": True,
                    "cpm_proof": activity_found,
                    "message": "Time impact cannot be finalised because replacement quantity is missing."
                }

            original_duration = self._to_float(activity.get("duration"), 0.0) if activity_found else 0.0
            replacement_duration = qty_for_time / confirmed_productivity
            additional_duration = max(0.0, replacement_duration - original_duration)
            formula = f"max(0, ({qty_for_time} / {confirmed_productivity}) - {original_duration})"

        elif evaluation_mode == "additional_work" or variation_type == "TYPE5":
            qty_for_time = new_quantity if new_quantity is not None else replacement_quantity

            if qty_for_time is None:
                return {
                    "activity_ref": activity_ref,
                    "activity_name": activity_name,
                    "productivity": confirmed_productivity,
                    "productivity_source": productivity_source,
                    "additional_duration": 0,
                    "is_critical": is_critical,
                    "original_float": original_float,
                    "delay_absorbed_by_float": False,
                    "eot_days": 0,
                    "formula": "",
                    "manual_required": True,
                    "cpm_proof": activity_found,
                    "message": "Time impact cannot be finalised because additional work quantity is missing."
                }

            additional_duration = qty_for_time / confirmed_productivity
            formula = f"{qty_for_time} / {confirmed_productivity}"

        else:
            if original_quantity is None or new_quantity is None:
                return {
                    "activity_ref": activity_ref,
                    "activity_name": activity_name,
                    "productivity": confirmed_productivity,
                    "productivity_source": productivity_source,
                    "additional_duration": 0,
                    "is_critical": is_critical,
                    "original_float": original_float,
                    "delay_absorbed_by_float": False,
                    "eot_days": 0,
                    "formula": "",
                    "manual_required": True,
                    "cpm_proof": activity_found,
                    "message": "Time impact cannot be finalised because original/new quantity is missing."
                }

            qty_delta = max(0.0, new_quantity - original_quantity)
            additional_duration = qty_delta / confirmed_productivity
            formula = f"({new_quantity} - {original_quantity}) / {confirmed_productivity}"

        # If activity is not found in the uploaded programme, calculate duration but do not claim EOT.
        if not activity_found:
            return {
                "activity_ref": activity_ref,
                "activity_name": activity_name,
                "productivity": confirmed_productivity,
                "productivity_source": productivity_source,
                "additional_duration": round(additional_duration, 2),
                "is_critical": False,
                "original_float": 0,
                "delay_absorbed_by_float": False,
                "eot_days": 0,
                "formula": formula,
                "manual_required": False,
                "cpm_proof": False,
                "message": "Additional duration was calculated from productivity, but EOT cannot be finalised without CPM activity proof."
            }

        if is_critical:
            eot_days = additional_duration
            delay_absorbed_by_float = False
        else:
            eot_days = max(0.0, additional_duration - original_float)
            delay_absorbed_by_float = additional_duration <= original_float

        return {
            "activity_ref": activity_ref,
            "activity_name": activity_name,
            "productivity": confirmed_productivity,
            "productivity_source": productivity_source,
            "additional_duration": round(additional_duration, 2),
            "is_critical": is_critical,
            "original_float": original_float,
            "delay_absorbed_by_float": delay_absorbed_by_float,
            "eot_days": round(eot_days, 2),
            "formula": formula,
            "manual_required": False,
            "cpm_proof": True,
            "message": ""
        }

    def _build_cost_line(
        self,
        line_type: str,
        description: str,
        quantity: float,
        unit: Optional[str],
        rate: float,
        rate_source: str,
        rate_source_id: Optional[str],
        formula: str,
        amount: float,
        used_rate_source: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "line_type": line_type,
            "description": description or "",
            "quantity": float(quantity),
            "unit": unit or "",
            "rate": float(rate),
            "rate_source": rate_source or "",
            "rate_source_id": rate_source_id or "",
            "formula": formula,
            "amount": float(amount),
            "used_rate_source": used_rate_source or {}
        }

    def _description_for(self, item: Optional[Dict[str, Any]], fallback: Any) -> str:
        if fallback not in (None, ""):
            return str(fallback)
        if isinstance(item, dict):
            for key in ["description", "Description", "item_description", "name"]:
                if item.get(key) not in (None, ""):
                    return str(item.get(key))
        return ""

    def _unit_for(self, item: Optional[Dict[str, Any]], fallback: Any) -> str:
        if fallback not in (None, ""):
            return str(fallback)
        if isinstance(item, dict):
            for key in ["unit", "Unit", "uom", "UOM"]:
                if item.get(key) not in (None, ""):
                    return str(item.get(key))
        return ""

    def _extract_rate(self, item: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(item, dict):
            return None
        for key in ["rate", "unit_rate", "Rate", "Unit Rate", "total_rate", "price"]:
            if item.get(key) not in (None, ""):
                return self._to_float(item.get(key), None)
        return None

    def _source_id_from_item(self, item: Optional[Dict[str, Any]]) -> str:
        if not isinstance(item, dict):
            return ""
        for key in ["id", "item_reference", "item_ref", "item_number", "item_no", "code", "ref"]:
            if item.get(key) not in (None, ""):
                return str(item.get(key))
        return ""

    def _is_critical(self, activity: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(activity, dict):
            return False
        value = activity.get("is_critical", activity.get("critical", False))
        if isinstance(value, str):
            return value.strip().lower() in ["true", "yes", "1", "critical"]
        return bool(value)

    def _activity_float(self, activity: Optional[Dict[str, Any]]) -> float:
        if not isinstance(activity, dict):
            return 0.0
        for key in ["total_float", "float", "Float", "slack"]:
            if activity.get(key) not in (None, ""):
                return self._to_float(activity.get(key), 0.0) or 0.0
        return 0.0

    def _source_type_from_text(self, text: Any) -> str:
        source = str(text or "").lower()
        if "boq" in source:
            return "BOQ"
        if "rate breakdown" in source or "rb/" in source:
            return "rate_breakdown"
        if "bsr" in source:
            return "BSR"
        if "hsr" in source:
            return "HSR"
        if "quotation" in source or "quote" in source:
            return "quotation"
        return "confirmed"

    def _normalize(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _to_float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value in (None, ""):
            return default
        try:
            return float(str(value).replace(",", "").replace("Rs.", "").replace("Rs", "").strip())
        except Exception:
            return default


variation_evaluator = VariationEvaluator()