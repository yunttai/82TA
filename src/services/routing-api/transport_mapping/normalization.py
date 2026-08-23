"""Conservative deterministic normalization for transport identities."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


_NON_WORD = re.compile(r"[^0-9a-zA-Z가-힣]+")
_ROUTE_SUFFIXES = ("번버스", "버스노선", "버스", "노선", "번")
_STOP_SUFFIXES = ("버스정류장", "정류장")
_DIRECTION_ALIASES = {
    "상행선": "UP",
    "상행": "UP",
    "하행선": "DOWN",
    "하행": "DOWN",
    "인바운드": "INBOUND",
    "아웃바운드": "OUTBOUND",
}


def _compact(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    compact = _NON_WORD.sub("", normalized)
    return compact or None


def _drop_one_suffix(value: str | None, suffixes: tuple[str, ...]) -> str | None:
    compact = _compact(value)
    if compact is None:
        return None
    for suffix in suffixes:
        if compact.endswith(suffix) and len(compact) > len(suffix):
            return compact[: -len(suffix)]
    return compact


def normalize_route_name(value: str | None) -> str | None:
    return _drop_one_suffix(value, _ROUTE_SUFFIXES)


def normalize_stop_name(value: str | None) -> str | None:
    return _drop_one_suffix(value, _STOP_SUFFIXES)


def normalize_direction(value: str | None) -> str | None:
    compact = _compact(value)
    if compact is None:
        return None
    return _DIRECTION_ALIASES.get(compact, compact.upper())


def normalize_branch(value: str | None) -> str | None:
    compact = _compact(value)
    return compact.upper() if compact is not None else None


def normalize_type(value: str | None) -> str | None:
    compact = _compact(value)
    return compact.upper() if compact is not None else None


def name_similarity(left: str | None, right: str | None, *, kind: str) -> float | None:
    normalizer = normalize_route_name if kind == "route" else normalize_stop_name
    a = normalizer(left)
    b = normalizer(right)
    if a is None or b is None:
        return None
    if a == b:
        return 1.0
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 6)
