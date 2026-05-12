"""
Validation Engine for QS Checks
Implements validation logic for variation proposals
"""
from typing import Dict, List, Any, Optional
from .storage_manager import StorageManager


class ValidationEngine:
    """Handles QS validation checks for variation proposals"""
    
    def __init__(self, storage: StorageManager = None):
        self.storage = storage

    def validate_confirmed_variation(self, project: Dict[str, Any], request_data: Dict[str, Any], evaluation_result: Dict[str, Any]) -> Dict[str, Any]:
        validation_results = {
            "valid": True,
            "warnings": [],
            "errors": [],
        }

        variation_type = str(request_data.get("variation_type", "")).upper()
        evaluation_mode = str(request_data.get("evaluation_mode", "")).lower()
        supporting_documents = request_data.get("supporting_documents") or []
        confirmed_rate_source = str(request_data.get("confirmed_rate_source", "")).strip().lower()
        original_ref = request_data.get("original_boq_item_ref")
        replacement_ref = request_data.get("replacement_item_ref")
        confirmed_activity_ref = request_data.get("confirmed_activity_ref")

        if not request_data.get("human_confirmed"):
            validation_results["errors"].append("human confirmation missing")
            validation_results["valid"] = False

        if not original_ref and evaluation_mode not in {"additional_work"}:
            validation_results["errors"].append("BOQ reference missing")
            validation_results["valid"] = False

        if confirmed_rate_source in {"bsr", "hsr", "quotation"} and not supporting_documents:
            validation_results["errors"].append("external source claimed but no document reference provided")
            validation_results["valid"] = False

        if evaluation_mode == "substitution":
            if not original_ref or not replacement_ref:
                validation_results["errors"].append("Type 2 substitution missing original or replacement side")
                validation_results["valid"] = False

        if evaluation_mode == "omission" and self._total_from_lines(evaluation_result.get("cost_lines")) > 0:
            validation_results["errors"].append("omission with positive amount")
            validation_results["valid"] = False

        if evaluation_mode == "additional_work" and self._total_from_lines(evaluation_result.get("cost_lines")) < 0:
            validation_results["errors"].append("additional work with negative amount")
            validation_results["valid"] = False

        if evaluation_result.get("manual_confirmation_required"):
            validation_results["warnings"].append("manual confirmation required for unresolved rate or productivity evidence")

        time_impact = evaluation_result.get("time_impact") or {}
        if time_impact.get("manual_required"):
            if not confirmed_activity_ref:
                validation_results["errors"].append("time impact without activity mapping")
                validation_results["valid"] = False
            if not request_data.get("productivity_source"):
                validation_results["errors"].append("time impact without productivity source")
                validation_results["valid"] = False

        if time_impact.get("eot_days", 0) and not time_impact.get("cpm_proof"):
            validation_results["errors"].append("EOT claimed without CPM proof")
            validation_results["valid"] = False

        if request_data.get("engineer_instruction_ref") in (None, ""):
            validation_results["warnings"].append("Missing Engineer's Instruction warning")

        if variation_type == "TYPE3" and not self._has_drawing_support(supporting_documents):
            validation_results["warnings"].append("missing original/revised drawing warning")

        if confirmed_rate_source in {"bsr", "hsr", "quotation"}:
            confidence = self._best_rate_confidence(project, request_data)
            if confidence is not None and confidence < 0.6:
                validation_results["warnings"].append("low extraction confidence for external rate source")

        return validation_results
    
    def validate_variation(self, project, variation, cost_impact, time_impact) -> Dict[str, Any]:
        """
        Comprehensive validation on a variation proposal.
        Checks for missing information, logical consistency, and professional QS standards.
        """
        validation_results = {
            'valid': True,
            'warnings': [],
            'errors': []
        }
        
        # Check 1: Missing Engineer's Instruction
        if not variation.get('engineer_instruction_ref'):
            validation_results['warnings'].append("Missing Engineer's Instruction reference")
        
        # Check 2: Missing drawings
        if 'TYPE3' in str(variation.get('variation_type', '')):  # Position changes
            if not variation.get('supporting_documents') or 'drawing' not in str(variation.get('supporting_documents', '')).lower():
                validation_results['warnings'].append("Position variation missing original/revised drawings")
        
        # Check 3: Missing BOQ reference
        if not variation.get('confirmed_boq_item_id'):
            if 'TYPE4' not in str(variation.get('variation_type', '')):  # Not an omission
                validation_results['warnings'].append("Missing BOQ item reference for cost evaluation")
        
        # Check 4: Missing rate source
        if cost_impact != 0 and not variation.get('confirmed_rate_source'):
            validation_results['warnings'].append("Missing rate source evidence for cost calculation")
        
        # Check 5: Missing activity mapping for time claims
        if time_impact != 0 and not variation.get('confirmed_activity_id'):
            validation_results['warnings'].append("Time impact claimed but no activity mapping provided")
        
        # Check 6: Missing productivity source
        if time_impact != 0 and not variation.get('productivity_source'):
            validation_results['warnings'].append("Missing productivity source for time calculation")
        
        # Check 7: Missing human confirmation
        if not variation.get('human_confirmed'):
            validation_results['errors'].append("Variation must be confirmed by human before evaluation")
            validation_results['valid'] = False
        
        # Check 8: Time impact without CPM proof
        if time_impact != 0:
            activities = project.get('activities', [])
            confirmed_activity = next((a for a in activities if a.get('id') == variation.get('confirmed_activity_id')), None)
            if not confirmed_activity:
                validation_results['errors'].append("Time impact claimed but activity not found in CPM")
                validation_results['valid'] = False
        
        # Check 9: Omission with positive amount
        if 'TYPE4' in str(variation.get('variation_type', '')):  # Omission
            if cost_impact > 0:
                validation_results['errors'].append("Omission variation should have negative (debit) cost impact")
                validation_results['valid'] = False
        
        # Check 10: Excessive rate increase
        if variation.get('confirmed_boq_item_id'):
            boq_item = next(
                (b for b in project.get('boq_items', []) if b.get('id') == variation.get('confirmed_boq_item_id')),
                None
            )
            if boq_item and variation.get('confirmed_rate'):
                rate_increase_pct = ((variation.get('confirmed_rate') - boq_item.get('rate', 0)) / boq_item.get('rate', 1)) * 100
                if rate_increase_pct > 50:
                    validation_results['warnings'].append(f"Rate increase of {rate_increase_pct:.1f}% exceeds typical thresholds - requires justification")
        
        # Check 11: Unsupported quotation/BSR/HSR source
        rate_source = variation.get('confirmed_rate_source', '').lower()
        if rate_source in ['bsr', 'hsr', 'quotation']:
            if not variation.get('supporting_documents'):
                validation_results['errors'].append(f"Claimed rate from {rate_source.upper()} but no supporting document provided")
                validation_results['valid'] = False
        
        return validation_results

    def _best_rate_confidence(self, project: Dict[str, Any], request_data: Dict[str, Any]) -> Optional[float]:
        best_confidence = None
        for source in project.get("rate_sources", []):
            if request_data.get("confirmed_rate_source_id") and str(source.get("id")) != str(request_data.get("confirmed_rate_source_id")):
                continue
            confidence = source.get("confidence_score")
            if confidence is None:
                continue
            confidence = float(confidence)
            if best_confidence is None or confidence > best_confidence:
                best_confidence = confidence
        return best_confidence

    def _has_drawing_support(self, supporting_documents: List[Any]) -> bool:
        for document in supporting_documents:
            if "drawing" in str(document).lower() or ".dwg" in str(document).lower():
                return True
        return False

    def _total_from_lines(self, cost_lines: Optional[List[Dict[str, Any]]]) -> float:
        if not cost_lines:
            return 0.0
        return sum(float(line.get("amount", 0.0)) for line in cost_lines)
    
    def check_double_counting(self, variation: Dict) -> Dict[str, Any]:
        """Check for potential double counting of costs"""
        result = {'passed': True, 'warnings': [], 'errors': [], 'details': {}}
        
        details = variation.get('details', [])
        if not details: return result
        
        boq_item_ids = [d.get('boq_item_id') for d in details if d.get('boq_item_id')]
        duplicates = [item_id for item_id in set(boq_item_ids) if boq_item_ids.count(item_id) > 1]
        
        if duplicates:
            result['warnings'].append(f"Potential double counting: BOQ items {duplicates} appear multiple times")
            result['details']['duplicate_items'] = duplicates
        
        descriptions = [d.get('original_description', '').lower() for d in details]
        for i, desc1 in enumerate(descriptions):
            for j, desc2 in enumerate(descriptions[i+1:], start=i+1):
                common_words = set(desc1.split()) & set(desc2.split())
                if len(common_words) > 3:
                    result['warnings'].append(f"Potential overlap between item {i+1} and {j+1}: similar descriptions")
        
        return result
    
    def validate_omission_valuation(self, variation: Dict) -> Dict[str, Any]:
        """Validate that omissions are correctly valued"""
        result = {'passed': True, 'warnings': [], 'errors': [], 'details': {}}
        
        # Assuming variation_type check (FIDIC Type 4 is omission)
        metadata = variation.get('metadata', {})
        if metadata.get('variation_type') == 'TYPE4':
            details = variation.get('details', [])
            for detail in details:
                if detail.get('cost_impact', 0) > 0:
                    result['errors'].append(f"Omission item '{detail.get('original_description')}' has positive cost impact.")
                    result['passed'] = False
                
                if detail.get('new_quantity', 0) >= detail.get('original_quantity', 0):
                    result['warnings'].append(f"Omission item '{detail.get('original_description')}' has new quantity >= original.")
        
        elif variation.get('details'):
            for detail in variation['details']:
                if detail.get('new_quantity', 0) < 0:
                    result['warnings'].append(f"Item '{detail.get('original_description')}' has negative quantity.")
        
        return result
    
    def verify_delay_propagation(self, project_id: int, variation: Dict) -> Dict[str, Any]:
        """Verify that delay propagation logic is correct"""
        result = {'passed': True, 'warnings': [], 'errors': [], 'details': {}}
        
        if variation.get('time_impact', 0) == 0:
            return result
        
        affected_activities = variation.get('affected_activities') or []
        if not affected_activities:
            result['warnings'].append(f"Variation claims {variation['time_impact']} days EOT but no activities identified")
            return result
        
        project = self.storage.get_project(project_id)
        activities = [a for a in project.get('activities', []) if a['activity_id'] in affected_activities]
        critical_activities = [a for a in activities if a.get('is_critical') == 1]
        
        if variation['time_impact'] > 0 and not critical_activities:
            result['warnings'].append("EOT claimed but affected activities are not on critical path.")
        
        total_activity_duration = sum(a.get('duration', 0) for a in activities)
        if variation['time_impact'] > total_activity_duration * 2:
            result['warnings'].append(f"EOT seems excessive compared to activity durations.")
        
        return result
    
    def check_rate_reasonableness(self, variation: Dict) -> Dict[str, Any]:
        """Check if rates are reasonable compared to original BOQ"""
        result = {'passed': True, 'warnings': [], 'errors': [], 'details': {}}
        
        details = variation.get('details', [])
        if not details: return result
        
        excessive_increases = []
        for detail in details:
            orig_rate = detail.get('original_rate', 0)
            new_rate = detail.get('new_rate', 0)
            if orig_rate > 0:
                rate_increase_pct = ((new_rate - orig_rate) / orig_rate) * 100
                if rate_increase_pct > 50:
                    excessive_increases.append({'item': detail.get('original_description'), 'increase_pct': rate_increase_pct})
                    result['warnings'].append(f"Item '{detail.get('original_description')}': Rate increased by {rate_increase_pct:.1f}%")
        
        result['details']['excessive_increases'] = excessive_increases
        return result
    
    def _format_validation_notes(self, validation_results: Dict) -> str:
        """Format validation results into readable notes"""
        notes = []
        
        if validation_results['status'] == 'passed':
            notes.append("All validation checks passed.")
        elif validation_results['status'] == 'warnings':
            notes.append(f"Validation passed with {len(validation_results['warnings'])} warning(s):")
            for warning in validation_results['warnings']:
                notes.append(f"  - {warning}")
        else:
            notes.append(f"Validation failed with {len(validation_results['errors'])} error(s):")
            for error in validation_results['errors']:
                notes.append(f"  - {error}")
        
        return "\n".join(notes)
    
    def generate_validation_report(self, project_id: int, variation_id: int) -> str:
        """Generate a comprehensive validation report"""
        validation_results = self.validate_variation(project_id, variation_id)
        
        report = []
        report.append("=" * 60)
        report.append("VARIATION VALIDATION REPORT")
        report.append("=" * 60)
        report.append(f"Variation ID: {variation_id}")
        report.append(f"Overall Status: {validation_results['status'].upper()}")
        report.append("")
        
        # Individual checks
        report.append("VALIDATION CHECKS:")
        report.append("-" * 60)
        for check_name, check_result in validation_results['checks'].items():
            status = "✓ PASS" if check_result['passed'] else "✗ FAIL"
            report.append(f"{check_name.replace('_', ' ').title()}: {status}")
            
            if check_result.get('warnings'):
                for warning in check_result['warnings']:
                    report.append(f"  ⚠ {warning}")
            
            if check_result.get('errors'):
                for error in check_result['errors']:
                    report.append(f"  ✗ {error}")
        
        report.append("")
        report.append("=" * 60)
        
        return "\n".join(report)
