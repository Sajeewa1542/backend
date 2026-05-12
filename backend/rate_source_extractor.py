from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .ocr_processor import ocr_processor

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


class RateSourceExtractor:
    def __init__(self):
        self._ref_pattern = re.compile(
            r"(?P<ref>\b(?:RB|BSR|HSR|Q|QT|QUO|QUOTATION)[\s/.-]*[A-Z0-9-]+\b|\b\d+[A-Z]?(?:[./-]\d+)+\b)",
            re.IGNORECASE,
        )

    def extract_from_file(self, file_path: str, source_type: str, source_file: Optional[str] = None) -> List[Dict[str, Any]]:
        source_file = source_file or os.path.basename(file_path)
        normalized = self._normalize_source_type(source_type)

        if file_path.lower().endswith((".csv", ".xlsx", ".xls")):
            return self._extract_from_tabular(file_path, normalized, source_file)

        if file_path.lower().endswith(".pdf"):
            return self._extract_from_pdf(file_path, normalized, source_file)

        return []

    def _normalize_source_type(self, source_type: str) -> str:
        source_type = (source_type or "").strip().lower()
        if source_type in {"bsr", "hsr", "quotation", "rate_breakdown"}:
            return source_type.upper() if source_type in {"bsr", "hsr"} else source_type
        return source_type or "rate_breakdown"

    def _extract_from_tabular(self, file_path: str, source_type: str, source_file: str) -> List[Dict[str, Any]]:
        """
        Extract rate sources from CSV/Excel.

        Important improvement:
        - Excel files may have multiple sheets.
        - Read all sheets, not only the first sheet.
        - If structured column extraction fails, use messy row fallback.
        """
        try:
            if file_path.lower().endswith((".xlsx", ".xls")):
                sheets = pd.read_excel(file_path, sheet_name=None)
            else:
                try:
                    sheets = {"Sheet1": pd.read_csv(file_path)}
                except UnicodeDecodeError:
                    sheets = {"Sheet1": pd.read_csv(file_path, encoding="latin1")}
        except Exception as e:
            print(f"Rate source tabular extraction failed: {e}")
            return []

        candidates: List[Dict[str, Any]] = []

        for sheet_name, df in sheets.items():
            if df is None or df.empty:
                continue

            df = df.copy()
            df.columns = [str(col).strip().lower() for col in df.columns]

            column_map = self._detect_columns(list(df.columns))

            sheet_candidates: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                candidate = self._row_to_candidate(row, column_map, source_type, source_file)
                if candidate:
                    candidate["source_sheet"] = str(sheet_name)
                    sheet_candidates.append(candidate)

            if not sheet_candidates:
                sheet_candidates = self._extract_from_messy_rows(df, source_type, source_file)
                for candidate in sheet_candidates:
                    candidate["source_sheet"] = str(sheet_name)

            candidates.extend(sheet_candidates)

        return self._dedupe_candidates(candidates)

    def _extract_from_messy_rows(self, df: pd.DataFrame, source_type: str, source_file: str) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        current_ref = None
        current_description = None

        for row_number, row in df.iterrows():
            values = [self._safe_text(value) for value in row.tolist() if self._safe_text(value)]
            if not values:
                continue

            first_cell = values[0]
            row_text = " ".join(values)
            reference_match = self._ref_pattern.match(first_cell)
            if reference_match:
                current_ref = reference_match.group("ref")
                current_description = " ".join(values[1:]).strip()
                row_rate = self._extract_last_rate(values)
                if row_rate is not None:
                    candidates.append(self._build_candidate(
                        source_type=source_type,
                        source_file=source_file,
                        page_number=None,
                        item_reference=current_ref,
                        description=current_description or first_cell,
                        unit=self._extract_unit(row_text),
                        rate=row_rate,
                        raw_text_excerpt=row_text,
                        confidence=0.64 if current_description else 0.58,
                    ))
                continue

            if any(keyword in row_text.lower() for keyword in ["total net unit rate", "total rate", "unit rate", "rate for"]):
                row_rate = self._extract_last_rate(values)
                if row_rate is not None:
                    candidates.append(self._build_candidate(
                        source_type=source_type,
                        source_file=source_file,
                        page_number=None,
                        item_reference=current_ref,
                        description=current_description or row_text,
                        unit=self._extract_unit(row_text),
                        rate=row_rate,
                        raw_text_excerpt=row_text,
                        confidence=0.61 if current_ref else 0.56,
                    ))

        return [candidate for candidate in candidates if candidate]

    def _build_candidate(
        self,
        source_type: str,
        source_file: str,
        page_number: Optional[int],
        item_reference: Optional[str],
        description: str,
        unit: Optional[str],
        rate: float,
        raw_text_excerpt: str,
        confidence: float,
    ) -> Dict[str, Any]:
        return {
            "id": None,
            "source_type": source_type,
            "source_file": source_file,
            "page_number": page_number,
            "item_reference": item_reference,
            "description": description or "",
            "unit": unit or None,
            "rate": rate,
            "material_cost": None,
            "labour_cost": None,
            "plant_cost": None,
            "overhead_profit": None,
            "supplier": None,
            "quotation_date": None,
            "confidence_score": round(min(confidence, 0.99), 2),
            "raw_text_excerpt": raw_text_excerpt[:280],
        }

    def _extract_last_rate(self, values: List[str]) -> Optional[float]:
        for value in reversed(values):
            rate = self._safe_float(value)
            if rate is not None:
                return rate
        return None

    def _detect_columns(self, columns: List[str]) -> Dict[str, Optional[str]]:
        """
        Detect columns more safely.

        Previous issue:
        'item' could accidentally match description columns.
        This version prioritises exact/common QS column names.
        """

        normalized_columns = [str(col).strip().lower() for col in columns]

        def find_exact(*names: str) -> Optional[str]:
            for name in names:
                for column in normalized_columns:
                    if column == name:
                        return column
            return None

        def find_contains(*needles: str) -> Optional[str]:
            for column in normalized_columns:
                if any(needle in column for needle in needles):
                    return column
            return None

        item_reference = (
            find_exact(
                "item reference",
                "item ref",
                "item no",
                "item number",
                "item_reference",
                "item_ref",
                "ref",
                "code",
                "reference",
            )
            or find_contains("item reference", "item ref", "item no", "item number", "ref", "code")
        )

        description = (
            find_exact(
                "description",
                "item description",
                "work description",
                "particulars",
                "particular",
                "desc",
            )
            or find_contains("description", "particular", "work item", "scope")
        )

        unit = (
            find_exact("unit", "uom", "u/m", "measure", "measurement unit")
            or find_contains("unit", "uom")
        )

        rate = (
            find_exact("rate", "unit rate", "total rate", "net rate", "price")
            or find_contains("unit rate", "total rate", "net rate", "rate", "price")
        )

        return {
            "item_reference": item_reference,
            "description": description,
            "unit": unit,
            "rate": rate,
            "material_cost": find_contains("material"),
            "labour_cost": find_contains("labour", "labor"),
            "plant_cost": find_contains("plant", "equipment"),
            "overhead_profit": find_contains("overhead", "profit", "ohp"),
            "supplier": find_contains("supplier", "vendor", "company"),
            "quotation_date": find_contains("date", "quotation date"),
        }
    
    def _row_to_candidate(self, row: pd.Series, column_map: Dict[str, Optional[str]], source_type: str, source_file: str) -> Optional[Dict[str, Any]]:
        raw_excerpt = self._build_raw_excerpt(row)

        description = self._safe_text(row.get(column_map.get("description")))
        item_reference = self._safe_text(row.get(column_map.get("item_reference")))
        unit = self._safe_text(row.get(column_map.get("unit")))
        rate = self._safe_float(row.get(column_map.get("rate")))

        # Fallback: recover item reference from full row text.
        if not item_reference:
            ref_match = self._ref_pattern.search(raw_excerpt)
            if ref_match:
                item_reference = self._clean_reference(ref_match.group("ref"))

        # Fallback: recover unit from full row text.
        if not unit:
            unit = self._extract_unit(raw_excerpt) or ""

        # Fallback: recover rate from row values if rate column detection failed.
        if rate is None:
            row_values = [self._safe_text(value) for value in row.tolist() if self._safe_text(value)]
            rate = self._extract_last_rate(row_values)

        # Fallback: recover description from raw row text.
        if not description:
            description = raw_excerpt
            if item_reference:
                description = description.replace(item_reference, "", 1).strip(" -:;,.|")

        if not description and not item_reference:
            return None

        if rate is None:
            return None

        confidence = 0.55
        if description:
            confidence += 0.15
        if item_reference:
            confidence += 0.15
        if unit:
            confidence += 0.05

        return {
            "id": None,
            "source_type": source_type,
            "source_file": source_file,
            "page_number": None,
            "item_reference": item_reference or None,
            "description": description or "",
            "unit": unit or None,
            "rate": rate,
            "material_cost": self._safe_float(row.get(column_map.get("material_cost"))),
            "labour_cost": self._safe_float(row.get(column_map.get("labour_cost"))),
            "plant_cost": self._safe_float(row.get(column_map.get("plant_cost"))),
            "overhead_profit": self._safe_float(row.get(column_map.get("overhead_profit"))),
            "supplier": self._safe_text(row.get(column_map.get("supplier"))) or None,
            "quotation_date": self._safe_text(row.get(column_map.get("quotation_date"))) or None,
            "confidence_score": round(min(confidence, 0.99), 2),
            "raw_text_excerpt": raw_excerpt,
        }

    def _build_raw_excerpt(self, row: pd.Series) -> str:
        values = [str(value) for value in row.tolist() if pd.notna(value) and str(value).strip()]
        return " | ".join(values[:6])[:280]

    def _extract_from_pdf(self, file_path: str, source_type: str, source_file: str) -> List[Dict[str, Any]]:
        readable_candidates = self._extract_text_pdf(file_path, source_type, source_file)
        if readable_candidates:
            return readable_candidates

        return self._extract_via_ocr(file_path, source_type, source_file)

    def _extract_text_pdf(self, file_path: str, source_type: str, source_file: str) -> List[Dict[str, Any]]:
        if PdfReader is None:
            return []

        try:
            reader = PdfReader(file_path)
        except Exception:
            return []

        candidates: List[Dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""

            if not text.strip():
                continue

            page_candidates = self._extract_from_text_block(text, source_type, source_file, page_number)
            candidates.extend(page_candidates)

        return candidates

    def _extract_via_ocr(self, file_path: str, source_type: str, source_file: str) -> List[Dict[str, Any]]:
        try:
            df = ocr_processor.process_pdf(file_path, mode="quotation" if source_type == "quotation" else "boq")
        except Exception:
            return []

        if df is None or df.empty:
            return []

        candidates: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            candidate = {
                "id": None,
                "source_type": source_type,
                "source_file": source_file,
                "page_number": None,
                "item_reference": self._safe_text(row.get("item_ref") or row.get("item_reference")) or None,
                "description": self._safe_text(row.get("description")) or "",
                "unit": self._safe_text(row.get("unit")) or None,
                "rate": self._safe_float(row.get("rate") or row.get("total_rate")),
                "material_cost": self._safe_float(row.get("material_cost")),
                "labour_cost": self._safe_float(row.get("labor_cost") or row.get("labour_cost")),
                "plant_cost": self._safe_float(row.get("plant_cost")),
                "overhead_profit": self._safe_float(row.get("overhead_profit")),
                "supplier": None,
                "quotation_date": None,
                "confidence_score": 0.58 if str(row.get("description", "")).strip() else 0.45,
                "raw_text_excerpt": self._build_raw_excerpt(row),
            }
            if candidate["rate"] is not None:
                candidates.append(candidate)

        return candidates

    def _extract_from_text_block(self, text: str, source_type: str, source_file: str, page_number: int) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            candidate = self._parse_text_line(line, source_type, source_file, page_number)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _parse_text_line(self, line: str, source_type: str, source_file: str, page_number: int) -> Optional[Dict[str, Any]]:
        numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", line)
        if not numbers:
            return None

        rate = self._safe_float(numbers[-1])
        if rate is None:
            return None

        reference_match = self._ref_pattern.search(line)
        item_reference = reference_match.group("ref") if reference_match else None

        description = line
        if item_reference:
            description = line.replace(item_reference, "", 1).strip("-:;,. ")

        confidence = 0.52
        if item_reference:
            confidence += 0.1
        if description and len(description) > 15:
            confidence += 0.15

        return {
            "id": None,
            "source_type": source_type,
            "source_file": source_file,
            "page_number": page_number,
            "item_reference": item_reference,
            "description": description[:250],
            "unit": self._extract_unit(line),
            "rate": rate,
            "material_cost": None,
            "labour_cost": None,
            "plant_cost": None,
            "overhead_profit": None,
            "supplier": None,
            "quotation_date": None,
            "confidence_score": round(min(confidence, 0.99), 2),
            "raw_text_excerpt": line[:280],
        }

    def _extract_unit(self, text: str) -> Optional[str]:
        unit_match = re.search(r"\b(m2|m3|nr|m|kg|l|lot|item|days?|hrs?)\b", text, re.IGNORECASE)
        return unit_match.group(1) if unit_match else None

    def _clean_reference(self, value: Any) -> str:
        """
        Clean item references but keep readable QS format.

        RB 19 / RB-19 / RB.19 -> RB/19
        6.03 remains 6.03
        """
        text = self._safe_text(value)
        if not text:
            return ""

        text = re.sub(r"\s+", "/", text.strip())
        text = text.replace("-", "/")

        if re.match(r"^[A-Za-z]+[./]\d+", text):
            prefix = re.match(r"^[A-Za-z]+", text).group(0).upper()
            number = re.sub(r"^[A-Za-z]+[./]?", "", text)
            return f"{prefix}/{number}"

        return text

    def _dedupe_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            key = "::".join([
                str(candidate.get("source_type") or "").lower(),
                str(candidate.get("source_file") or "").lower(),
                str(candidate.get("item_reference") or "").lower(),
                str(candidate.get("description") or "").lower(),
                str(candidate.get("rate") or ""),
            ])

            existing = best.get(key)
            if existing is None:
                best[key] = candidate
                continue

            if float(candidate.get("confidence_score") or 0) > float(existing.get("confidence_score") or 0):
                best[key] = candidate

        return list(best.values())

    def _safe_text(self, value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip()

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "").replace("Rs.", "").replace("Rs", "").strip()
            return float(value)
        except Exception:
            return None


rate_source_extractor = RateSourceExtractor()