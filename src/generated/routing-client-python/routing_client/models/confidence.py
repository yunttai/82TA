from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..models.confidence_grade import ConfidenceGrade

T = TypeVar("T", bound="Confidence")


@_attrs_define
class Confidence:
    """
    Attributes:
        score (float):
        grade (ConfidenceGrade):
    """

    score: float
    grade: ConfidenceGrade

    def to_dict(self) -> dict[str, Any]:
        score = self.score

        grade = self.grade.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "score": score,
                "grade": grade,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        score = d.pop("score")

        grade = ConfidenceGrade(d.pop("grade"))

        confidence = cls(
            score=score,
            grade=grade,
        )

        return confidence
