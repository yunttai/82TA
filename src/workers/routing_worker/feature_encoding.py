"""Versioned, deterministic numeric encoding shared by training and serving.

The canonical 22-field vectors intentionally retain route/direction provenance and
missingness strings.  LightGBM receives only this encoded projection; neither the
trainer nor a runtime may invent its own coercion rules.
"""

from __future__ import annotations

from hashlib import sha256
from math import isfinite, nan
from typing import Mapping

from .feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)


FEATURE_ENCODING_VERSION = "worker-feature-encoding-v1"
_CATEGORICAL_FEATURES = frozenset(
    {"route_id", "direction", "context_missing_flags", "missing_flags"}
)
_EMPTY_CATEGORY_IS_NO_MISSING = frozenset(
    {"context_missing_flags", "missing_flags"}
)
_BOOLEAN_FEATURES = frozenset({"traffic_incident_present"})
_MAX_CATEGORY_UTF8_BYTES = 4_096


class FeatureEncodingError(ValueError):
    """Raised when a vector cannot be projected without implicit coercion."""


def _expected(family: str) -> tuple[str, tuple[str, ...]]:
    if family == "ETA":
        return ETA_SCHEMA_VERSION, ETA_FEATURE_NAMES
    if family == "SEAT_RISK":
        return SEAT_SCHEMA_VERSION, SEAT_FEATURE_NAMES
    raise FeatureEncodingError("feature encoding family must be ETA or SEAT_RISK")


def _category(name: str, value: object) -> float:
    if not isinstance(value, str):
        raise FeatureEncodingError(f"{name} must be a string category")
    if value == "" and name not in _EMPTY_CATEGORY_IS_NO_MISSING:
        raise FeatureEncodingError(f"{name} must be non-blank")
    if value != "" and not value.strip():
        raise FeatureEncodingError(f"{name} must be non-blank")
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_CATEGORY_UTF8_BYTES:
        raise FeatureEncodingError(f"{name} exceeds the categorical byte limit")
    payload = b"\x00".join(
        (FEATURE_ENCODING_VERSION.encode("ascii"), name.encode("ascii"), encoded)
    )
    # Stable unsigned 53-bit projection: exactly representable as a Python float.
    integer = int.from_bytes(sha256(payload).digest()[:8], "big") >> 11
    return integer / float((1 << 53) - 1)


def encode_feature_values(
    *,
    family: str,
    feature_schema_version: str,
    feature_names: tuple[str, ...],
    values: tuple[object, ...],
) -> tuple[float, ...]:
    """Encode one exact canonical vector for LightGBM.

    ``None`` is retained as IEEE NaN for LightGBM missing-value handling. Numeric
    zero and boolean ``False`` remain distinct from missing. Strings are stable,
    versioned categorical hashes rather than process-random ``hash()`` values.
    """

    expected_version, expected_names = _expected(family)
    if (
        feature_schema_version != expected_version
        or tuple(feature_names) != expected_names
    ):
        raise FeatureEncodingError("feature schema/version is not the canonical family schema")
    immutable_values = tuple(values)
    if len(immutable_values) != len(expected_names):
        raise FeatureEncodingError("feature names and values must have equal length")
    result: list[float] = []
    for name, value in zip(expected_names, immutable_values, strict=True):
        if value is None:
            result.append(nan)
        elif name in _CATEGORICAL_FEATURES:
            result.append(_category(name, value))
        elif name in _BOOLEAN_FEATURES:
            if not isinstance(value, bool):
                raise FeatureEncodingError(f"{name} must be boolean or missing")
            result.append(1.0 if value else 0.0)
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FeatureEncodingError(f"{name} must be numeric or missing")
            numeric = float(value)
            if not isfinite(numeric):
                raise FeatureEncodingError(f"{name} must be finite when observed")
            result.append(numeric)
    return tuple(result)


def encode_feature_mapping(
    *,
    family: str,
    feature_schema_version: str,
    feature_names: tuple[str, ...],
    values: Mapping[str, object],
) -> tuple[float, ...]:
    """Training-side mapping adapter for the same serving encoder."""

    if set(values) != set(feature_names) or len(values) != len(feature_names):
        raise FeatureEncodingError("training row keys must exactly match feature names")
    return encode_feature_values(
        family=family,
        feature_schema_version=feature_schema_version,
        feature_names=feature_names,
        values=tuple(values[name] for name in feature_names),
    )


def feature_schema_document(*, family: str) -> dict[str, object]:
    """Return the strict inert schema document expected by native loaders."""

    version, names = _expected(family)
    return {
        "family": family,
        "fullFeatureSchemaVersion": version,
        "orderedFeatureNames": list(names),
        "encodingVersion": FEATURE_ENCODING_VERSION,
    }


__all__ = [
    "FEATURE_ENCODING_VERSION",
    "FeatureEncodingError",
    "encode_feature_mapping",
    "encode_feature_values",
    "feature_schema_document",
]
