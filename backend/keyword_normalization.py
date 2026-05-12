from __future__ import annotations

import re
import json
import os
from typing import Dict, Iterable, List, Optional


def load_keyword_normalization_map(project: Optional[Dict[str, object]] = None) -> Dict[str, str]:
    project_map = {}
    if project and isinstance(project.get("keyword_normalization_map"), dict):
        project_map = project.get("keyword_normalization_map")  # type: ignore[assignment]

    file_path = os.path.join(os.path.dirname(__file__), "keyword_normalization_map.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    file_map = {str(k).lower(): str(v).lower() for k, v in data.items() if k and v}
                    project_map = {**file_map, **{str(k).lower(): str(v).lower() for k, v in project_map.items() if k and v}}
        except Exception:
            pass

    return {str(k).lower(): str(v).lower() for k, v in project_map.items() if k and v}


def normalize_text_for_matching(text: str, mapping: Optional[Dict[str, str]] = None) -> str:
    normalized = (text or "").lower()
    if not mapping:
        return normalized

    phrase_keys = [key for key in mapping.keys() if any(ch.isspace() for ch in str(key))]
    for key in sorted(phrase_keys, key=lambda k: len(str(k)), reverse=True):
        replacement = mapping.get(key)
        if not replacement:
            continue
        pattern = r"\b" + re.escape(str(key).lower()) + r"\b"
        normalized = re.sub(pattern, str(replacement).lower(), normalized)

    return normalized


def tokenize_for_matching(text: str, mapping: Optional[Dict[str, str]] = None) -> List[str]:
    normalized = normalize_text_for_matching(text, mapping=mapping)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if not mapping:
        return tokens

    mapped: List[str] = []
    for token in tokens:
        replacement = mapping.get(token)
        mapped.append((replacement or token).lower())
    return mapped


def tokens_contained(haystack: str, needles: Iterable[str], mapping: Optional[Dict[str, str]] = None) -> bool:
    haystack_tokens = set(tokenize_for_matching(haystack, mapping=mapping))
    for needle in needles:
        if needle and needle in haystack_tokens:
            return True
    return False