from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .storage_manager import StorageManager, storage_manager


@dataclass
class RateCandidate:
    source_priority: int
    source_type: str
    source_id: str
    source_file: Optional[str]
    page_number: Optional[int]
    item_reference: Optional[str]
    description: str
    unit: Optional[str]
    rate: float
    similarity_score: float
    confidence_score: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_priority": self.source_priority,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_file": self.source_file,
            "page_number": self.page_number,
            "item_reference": self.item_reference,
            "description": self.description,
            "unit": self.unit,
            "rate": self.rate,
            "similarity_score": round(float(self.similarity_score), 4),
            "confidence_score": round(float(self.confidence_score), 4),
            "reason": self.reason,
        }


class RateResolver:
    MIN_SIMILARITY = 0.55

    def __init__(self, storage: Optional[StorageManager] = None):
        self.storage = storage or storage_manager

    def resolve_rate(
        self,
        project_id,
        query,
        unit: Optional[str] = None,
        preferred_work_type: str = "building",
        exclude_boq_ref: Optional[str] = None,
        min_similarity: float = MIN_SIMILARITY,
    ) -> Dict[str, Any]:
        project = self.storage.get_project(project_id)
        if not project:
            return {
                "status": "manual_required",
                "selected_candidate": None,
                "candidates": [],
                "missing_information": ["project not found"],
            }

        boq_items = [item for item in project.get("boq_items", []) if item]
        rate_sources = project.get("rate_sources", []) or []

        # Include core uploaded rate breakdowns also.
        # Core rate breakdown files may be stored under "rate_breakdowns",
        # while additional BSR/HSR/quotation files are stored under "rate_sources".
        core_rate_breakdowns = project.get("rate_breakdowns", []) or []
        normalized_core_breakdowns = []

        for item in core_rate_breakdowns:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("source_type", "rate_breakdown")
            row.setdefault("source_file", project.get("rate_breakdown_filename", "Rate Breakdown"))
            normalized_core_breakdowns.append(row)

        rate_sources = rate_sources + normalized_core_breakdowns
        query_text = self._normalize_text(query)
        unit_text = self._normalize_text(unit)
        query_refs = self._extract_reference_tokens(query_text)

        candidates: List[RateCandidate] = []

        exact_boq = self._find_exact_boq_match(boq_items, query_text, exclude_boq_ref)
        if exact_boq:
            candidates.append(exact_boq)

        similar_boq = self._rank_similar_boq_items(boq_items, query_text, unit_text, exclude_boq_ref, min_similarity)
        candidates.extend(similar_boq)

        rate_breakdowns = [
            source
            for source in rate_sources
            if self._normalize_text(source.get("source_type")) == "rate_breakdown"
        ]

        preferred_primary = "bsr" if "road" not in self._normalize_text(preferred_work_type) else "hsr"
        preferred_secondary = "hsr" if preferred_primary == "bsr" else "bsr"

        preferred_primary_sources = [
            s for s in rate_sources
            if self._normalize_text(s.get("source_type")) == preferred_primary
        ]

        preferred_secondary_sources = [
            s for s in rate_sources
            if self._normalize_text(s.get("source_type")) == preferred_secondary
        ]

        quotation_sources = [
            s for s in rate_sources
            if self._normalize_text(s.get("source_type")) == "quotation"
        ]

        # Exact BSR / HSR / quotation reference matching first.
        # Example: BSR/12, HSR/05, Q-SOL-01
        candidates.extend(
            self._find_exact_rate_source_matches(
                preferred_primary_sources,
                query_refs,
                query_text,
                unit_text,
                source_priority=0,
                label=preferred_primary.upper(),
            )
        )

        candidates.extend(
            self._find_exact_rate_source_matches(
                preferred_secondary_sources,
                query_refs,
                query_text,
                unit_text,
                source_priority=0,
                label=preferred_secondary.upper(),
            )
        )

        candidates.extend(
            self._find_exact_rate_source_matches(
                quotation_sources,
                query_refs,
                query_text,
                unit_text,
                source_priority=0,
                label="quotation",
            )
        )

        # Then normal semantic ranking according to hierarchy.
        candidates.extend(
            self._rank_rate_sources(
                preferred_primary_sources,
                query_text,
                unit_text,
                source_priority=4,
                label=preferred_primary.upper(),
                min_similarity=min_similarity,
            )
        )

        candidates.extend(
            self._rank_rate_sources(
                preferred_secondary_sources,
                query_text,
                unit_text,
                source_priority=5,
                label=preferred_secondary.upper(),
                min_similarity=min_similarity,
            )
        )

        candidates.extend(
            self._rank_rate_sources(
                quotation_sources,
                query_text,
                unit_text,
                source_priority=6,
                label="quotation",
                min_similarity=min_similarity,
            )
        )

        filtered_candidates = [candidate for candidate in candidates if candidate.rate is not None]
        filtered_candidates = self._dedupe_candidates(filtered_candidates)
        filtered_candidates.sort(key=lambda item: self._candidate_sort_key(item, unit_text, query_refs))

        status = "candidates_found" if filtered_candidates else "manual_required"
        selected_candidate = filtered_candidates[0].to_dict() if filtered_candidates else None

        missing_information: List[str] = []
        if not query_text:
            missing_information.append("description query")
        if not unit_text:
            missing_information.append("unit")

        return {
            "status": status,
            "selected_candidate": selected_candidate,
            "candidates": [candidate.to_dict() for candidate in filtered_candidates],
            "missing_information": missing_information,
        }

    def _find_exact_boq_match(self, boq_items: List[Dict[str, Any]], query_text: str, exclude_boq_ref: Optional[str]) -> Optional[RateCandidate]:
        """
        Find BOQ item by exact reference match (highest priority).
        Filters out header rows like "Bill", "Item Ref", "Substructure", etc.
        """
        if not query_text:
            return None

        # Common header/section keywords to skip
        header_keywords = {"bill", "item ref", "description", "qty", "unit", "rate", "amount", 
                          "substructure", "superstructure", "section", "schedule", "summary", "total"}

        query_text_norm = self._normalize_text(query_text)
        
        # First pass: exact reference match (highest priority)
        extracted_refs = self._extract_reference_tokens(query_text_norm)
        
        for item in boq_items:
            if exclude_boq_ref and self._normalize_text(item.get("item_number")) == self._normalize_text(exclude_boq_ref):
                continue

            # Skip header rows
            description = self._normalize_text(item.get("description"))
            if description in header_keywords or any(kw == description for kw in header_keywords):
                continue

            item_ref = self._first_value(item, ["item_number", "item_no", "item_ref", "code", "ref", "id", "pay_item"])
            item_ref_norm = self._normalize_text(item_ref)
            
            # Check for exact reference match
            if item_ref_norm and (item_ref_norm == query_text_norm or item_ref_norm in extracted_refs):
                return RateCandidate(
                    source_priority=1,
                    source_type="boq",
                    source_id=str(item.get("id", item_ref or "boq")),
                    source_file=item.get("source_file") or item.get("boq_filename"),
                    page_number=None,
                    item_reference=str(item_ref) if item_ref is not None else None,
                    description=str(item.get("description", "")),
                    unit=item.get("unit"),
                    rate=self._to_float(item.get("rate"), 0.0),
                    similarity_score=1.0,
                    confidence_score=0.99,
                    reason=f"Exact BOQ reference match: {item_ref}",
                )
            
            # Check for exact description match
            if description and description == query_text_norm:
                return RateCandidate(
                    source_priority=1,
                    source_type="boq",
                    source_id=str(item.get("id", item_ref or "boq")),
                    source_file=item.get("source_file") or item.get("boq_filename"),
                    page_number=None,
                    item_reference=str(item_ref) if item_ref is not None else None,
                    description=str(item.get("description", "")),
                    unit=item.get("unit"),
                    rate=self._to_float(item.get("rate"), 0.0),
                    similarity_score=1.0,
                    confidence_score=0.98,
                    reason="Exact BOQ description match",
                )
        
        return None

    def _rank_similar_boq_items(
        self,
        boq_items: List[Dict[str, Any]],
        query_text: str,
        unit_text: str,
        exclude_boq_ref: Optional[str],
        min_similarity: float,
    ) -> List[RateCandidate]:
        rows: List[Dict[str, Any]] = []
        texts: List[str] = []
        for item in boq_items:
            if exclude_boq_ref and self._reference_matches(item, exclude_boq_ref):
                continue
            description = self._normalize_text(item.get("description"))
            if not description:
                continue
            texts.append(description)
            rows.append(item)

        return self._rank_rows(
            rows,
            texts,
            query_text,
            unit_text,
            source_priority=2,
            source_type="boq",
            label="similar BOQ/pro-rata item",
            min_similarity=min_similarity,
        )

    def _find_exact_rate_source_matches(
        self,
        sources: List[Dict[str, Any]],
        query_refs: set[str],
        query_text: str,
        unit_text: str,
        source_priority: int,
        label: str,
    ) -> List[RateCandidate]:
        """
        Exact reference matching for uploaded rate sources.
        This is critical when user says: 'Granite rate is RB/19'.
        Exact reference should beat weak semantic matching.
        """
        if not sources:
            return []

        normalized_refs = {self._normalize_ref(ref) for ref in query_refs if ref}
        matches: List[RateCandidate] = []

        for source in sources:
            item_reference = self._first_value(
                source,
                ["item_reference", "item_ref", "item_number", "item_no", "code", "ref", "id"],
            )

            source_id = source.get("id", item_reference or label)
            source_text = " ".join(
                str(value or "")
                for value in [
                    item_reference,
                    source.get("source_id"),
                    source.get("code"),
                    source.get("ref"),
                    source.get("description"),
                ]
            ).lower()

            source_ref_norm = self._normalize_ref(item_reference)
            source_id_norm = self._normalize_ref(source_id)

            exact_ref_match = (
                source_ref_norm in normalized_refs
                or source_id_norm in normalized_refs
                or any(ref and ref in self._normalize_ref(source_text) for ref in normalized_refs)
            )

            if not exact_ref_match:
                continue

            rate = self._to_float(
                source.get("rate") or source.get("total_rate") or source.get("unit_rate"),
                None,
            )
            if rate is None:
                continue

            row_unit = self._normalize_text(source.get("unit"))
            confidence = 0.99
            if unit_text and row_unit and unit_text != row_unit:
                confidence = 0.92

            matches.append(
                RateCandidate(
                    source_priority=source_priority,
                    source_type=self._normalize_text(source.get("source_type")) or label,
                    source_id=str(source_id),
                    source_file=source.get("source_file"),
                    page_number=source.get("page_number"),
                    item_reference=str(item_reference) if item_reference is not None else None,
                    description=str(source.get("description", "")),
                    unit=source.get("unit"),
                    rate=rate,
                    similarity_score=1.0,
                    confidence_score=confidence,
                    reason=f"Exact {label} reference match",
                )
            )

        return matches

    def _rank_rate_sources(
        self,
        sources: List[Dict[str, Any]],
        query_text: str,
        unit_text: str,
        source_priority: int,
        label: str,
        min_similarity: float,
    ) -> List[RateCandidate]:
        rows: List[Dict[str, Any]] = []
        texts: List[str] = []
        for source in sources:
            description = self._normalize_text(source.get("description"))
            if not description:
                continue
            rows.append(source)
            texts.append(description)
        return self._rank_rows(
            rows,
            texts,
            query_text,
            unit_text,
            source_priority=source_priority,
            source_type=label,
            label=label,
            min_similarity=min_similarity,
        )

    def _rank_rows(
        self,
        rows: List[Dict[str, Any]],
        texts: List[str],
        query_text: str,
        unit_text: str,
        source_priority: int,
        source_type: str,
        label: str,
        min_similarity: float,
    ) -> List[RateCandidate]:
        if not rows or not texts or not query_text:
            return []

        # Filter out unrelated candidates (unit mismatch, conflicting keywords)
        filtered_rows = []
        filtered_texts = []
        filtered_indices = []
        
        query_unit_norm = self._normalize_text(unit_text) if unit_text else ""
        conflicting_keywords = self._get_conflicting_keywords(query_text)
        
        for idx, (row, text) in enumerate(zip(rows, texts)):
            row_unit = self._normalize_text(row.get("unit", ""))
            row_text = self._normalize_text(text)
            
            # Skip if unit explicitly doesn't match (e.g., m2 in query but m in row)
            if query_unit_norm and row_unit and query_unit_norm != row_unit:
                # Still allow if unit similarity is high (e.g., m vs m2), but penalize
                if not self._are_similar_units(query_unit_norm, row_unit):
                    continue
            
            # Skip if row has conflicting keywords (e.g., "PVC pipe" when query is "asphalt")
            if conflicting_keywords and any(kw in row_text for kw in conflicting_keywords):
                continue
            
            filtered_rows.append(row)
            filtered_texts.append(text)
            filtered_indices.append(idx)
        
        if not filtered_rows:
            return []

        corpus = filtered_texts + [query_text]
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform(corpus)
        similarities = cosine_similarity(matrix[-1], matrix[:-1]).flatten()

        ranked: List[RateCandidate] = []
        for row, similarity in zip(filtered_rows, similarities):
            similarity_value = float(similarity)
            if similarity_value < float(min_similarity):
                continue

            rate = self._to_float(row.get("rate") or row.get("total_rate") or row.get("unit_rate"), None)
            if rate is None:
                continue

            row_unit = self._normalize_text(row.get("unit"))
            confidence = max(0.4, min(0.95, similarity_value + 0.15))
            if row.get("confidence_score") is not None:
                confidence = max(confidence, self._to_float(row.get("confidence_score"), confidence))
            if row_unit and query_unit_norm and query_unit_norm == row_unit:
                confidence = min(0.99, confidence + 0.07)

            trade_or_section = self._normalize_text(row.get("trade") or row.get("work_section") or row.get("work_type"))
            if trade_or_section and trade_or_section in self._normalize_text(query_text):
                confidence = min(0.99, confidence + 0.05)

            item_reference = self._first_value(row, ["item_reference", "item_ref", "item_number", "item_no", "code", "ref", "id"])
            ranked.append(
                RateCandidate(
                    source_priority=source_priority,
                    source_type=self._normalize_text(row.get("source_type")) or source_type,
                    source_id=str(row.get("id", item_reference or label)),
                    source_file=row.get("source_file"),
                    page_number=row.get("page_number"),
                    item_reference=str(item_reference) if item_reference is not None else None,
                    description=str(row.get("description", "")),
                    unit=row.get("unit"),
                    rate=rate,
                    similarity_score=similarity_value,
                    confidence_score=float(confidence),
                    reason=f"Matched {label}",
                )
            )

        ranked.sort(key=lambda candidate: (-candidate.similarity_score, -candidate.confidence_score))
        return ranked[:5]

    def _dedupe_candidates(self, candidates: List[RateCandidate]) -> List[RateCandidate]:
        best_by_key: Dict[str, RateCandidate] = {}
        for candidate in candidates:
            key = f"{self._normalize_text(candidate.source_type)}::{self._normalize_text(candidate.source_id)}"
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = candidate
                continue
            if (candidate.source_priority, -candidate.confidence_score, -candidate.similarity_score) < (
                existing.source_priority,
                -existing.confidence_score,
                -existing.similarity_score,
            ):
                best_by_key[key] = candidate
        return list(best_by_key.values())

    def _get_conflicting_keywords(self, query_text: str) -> set[str]:
        """
        Identify conflicting keywords that would indicate unrelated items.
        E.g., if query mentions "asphalt", exclude items with "pvc", "pipe", "door", etc.
        """
        query_norm = self._normalize_text(query_text)
        
        # Mapping of primary keywords to unrelated keywords to exclude
        exclusion_map = {
            "asphalt": {"pvc", "pipe", "door", "tile", "granite", "ceramic", "ceiling", "gypsum"},
            "pvc": {"asphalt", "granite", "tile", "ceramic", "door", "ceiling"},
            "door": {"asphalt", "tile", "pipe", "pvc", "ceiling", "granite"},
            "tile": {"asphalt", "pipe", "pvc", "ceiling", "gypsum"},
            "granite": {"asphalt", "pipe", "pvc", "ceiling"},
            "ceramic": {"asphalt", "pipe", "pvc", "ceiling"},
            "ceiling": {"asphalt", "door", "tile", "pipe", "pvc", "excavation"},
            "excavation": {"ceiling", "tile", "door", "asphalt"},
        }
        
        # Check which primary keywords are in the query
        for primary, exclusions in exclusion_map.items():
            if primary in query_norm:
                return exclusions
        
        return set()

    def _are_similar_units(self, unit1: str, unit2: str) -> bool:
        """
        Check if two units are similar/compatible (e.g., m and m2 for area context).
        """
        unit1_norm = self._normalize_text(unit1)
        unit2_norm = self._normalize_text(unit2)
        
        if unit1_norm == unit2_norm:
            return True
        
        # Allow m/m2 mismatch only if context suggests it
        # (This is conservative - we prefer exact unit matching)
        similar_groups = [
            {"m", "m2", "sqm"},
            {"kg", "t", "tonnes"},
            {"l", "ml", "litre"},
        ]
        
        for group in similar_groups:
            if unit1_norm in group and unit2_norm in group:
                return True
        
        return False

    def _candidate_sort_key(self, candidate: RateCandidate, unit_text: str, query_refs: set[str]):
        unit_match = 1 if unit_text and self._normalize_text(candidate.unit) == unit_text else 0

        normalized_refs = {self._normalize_ref(ref) for ref in query_refs if ref}
        candidate_ref = self._normalize_ref(candidate.item_reference)
        candidate_source_id = self._normalize_ref(candidate.source_id)

        reference_match = 1 if normalized_refs and (
            candidate_ref in normalized_refs or candidate_source_id in normalized_refs
        ) else 0

        return (
            candidate.source_priority,
            -reference_match,
            -unit_match,
            -candidate.confidence_score,
            -candidate.similarity_score,
        )

    def _extract_reference_tokens(self, text: str) -> set[str]:
        """
        Extract references such as:
        6.03, 10.02, RB/19, RB-19, RB 19, BSR/12, HSR-07, Q-SOL-01
        """
        if not text:
            return set()

        text = str(text).lower()

        patterns = [
            r"\b(?:rb|bsr|hsr|q|qt|quo|quotation)[\s/.-]*[a-z0-9-]+\b",
            r"\b\d+[a-z]?(?:[./-]\d+)+\b",
            r"\b[a-z]{1,4}\d+[a-z]?(?:[./-]\d+)*\b",
        ]

        refs: set[str] = set()
        for pattern in patterns:
            for match in re.findall(pattern, text):
                cleaned = match.strip().lower()
                refs.add(cleaned)
                refs.add(self._normalize_ref(cleaned))

        return {ref for ref in refs if ref}
    
    def _normalize_ref(self, value: Any) -> str:
        """
        Normalize references for comparison.
        RB/19, RB-19, RB 19 => rb19
        6.03 => 603
        """
        if value is None:
            return ""
        return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())

    def _reference_matches(self, item: Dict[str, Any], target: str) -> bool:
        target_text = self._normalize_text(target)
        if not target_text:
            return False
        for field in ["item_number", "item_no", "item_ref", "code", "ref", "id"]:
            candidate = self._normalize_text(item.get(field))
            if candidate and candidate == target_text:
                return True
        return False

    def _first_value(self, item: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
        return None

    def _normalize_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    def _to_float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None or value == "":
            return default
        try:
            return float(str(value).replace(",", "").replace("Rs.", "").replace("Rs", "").strip())
        except Exception:
            return default


rate_resolver = RateResolver()