"""Shared helpers for job scanners."""
from __future__ import annotations

import re
from typing import Iterable

ENGINEERING_PATTERNS = re.compile(
    r"\b("
    r"software\s+engineer|research\s+engineer|member\s+of\s+technical\s+staff|"
    r"ml\s+engineer|machine\s+learning\s+engineer|backend\s+engineer|"
    r"frontend\s+engineer|full[\s-]?stack|devops|sre|site\s+reliability|"
    r"infrastructure\s+engineer|data\s+engineer|platform\s+engineer|"
    r"kernel\s+engineer|systems\s+engineer|performance\s+engineer|"
    r"coding|programming|implement(ation|ing)|write\s+code|hands[\s-]?on\s+code|"
    r"leetcode|system\s+design\s+interview"
    r")\b",
    re.IGNORECASE,
)

POSITIVE_PATTERNS = re.compile(
    r"\b("
    r"tutor|ai\s+tutor|human\s+data|research\s+scientist|pure\s+math|"
    r"applied\s+math|statistics\s+tutor|physics\s+tutor|earth\s+science|"
    r"finance\s+expert|policy|safety\s+research|interpretability|"
    r"alignment\s+research|fellows?\s+program|curriculum|pedagogy|"
    r"mathematical|theoretical|first[\s-]?principles"
    r")\b",
    re.IGNORECASE,
)

REMOTE_PATTERNS = re.compile(
    r"\b(remote|remote[\s-]?friendly|work\s+from\s+home|wfh|fully\s+remote)\b",
    re.IGNORECASE,
)


def is_engineering_role(title: str, description: str = "") -> bool:
    text = f"{title} {description[:2000]}"
    return bool(ENGINEERING_PATTERNS.search(text))


def looks_applicable(title: str, description: str = "", location: str = "") -> bool:
    if is_engineering_role(title, description):
        return False
    text = f"{title} {location} {description[:1500]}"
    is_remote = bool(REMOTE_PATTERNS.search(text)) or "remote" in location.lower()
    has_positive = bool(POSITIVE_PATTERNS.search(text))
    return is_remote or has_positive
