from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.problem_details_safe_context import ProblemDetailsSafeContext
    from ..models.problem_details_violations_item import ProblemDetailsViolationsItem


T = TypeVar("T", bound="ProblemDetails")


@_attrs_define
class ProblemDetails:
    """
    Attributes:
        type_ (str):
        title (str):
        status (int):
        code (str):
        retryable (bool):
        correlation_id (str):
        violations (list[ProblemDetailsViolationsItem]):
        safe_context (ProblemDetailsSafeContext):
        detail (None | str | Unset):
    """

    type_: str
    title: str
    status: int
    code: str
    retryable: bool
    correlation_id: str
    violations: list[ProblemDetailsViolationsItem]
    safe_context: ProblemDetailsSafeContext
    detail: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        title = self.title

        status = self.status

        code = self.code

        retryable = self.retryable

        correlation_id = self.correlation_id

        violations = []
        for violations_item_data in self.violations:
            violations_item = violations_item_data.to_dict()
            violations.append(violations_item)

        safe_context = self.safe_context.to_dict()

        detail: None | str | Unset
        if isinstance(self.detail, Unset):
            detail = UNSET
        else:
            detail = self.detail

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "type": type_,
                "title": title,
                "status": status,
                "code": code,
                "retryable": retryable,
                "correlationId": correlation_id,
                "violations": violations,
                "safeContext": safe_context,
            }
        )
        if detail is not UNSET:
            field_dict["detail"] = detail

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.problem_details_safe_context import ProblemDetailsSafeContext
        from ..models.problem_details_violations_item import ProblemDetailsViolationsItem

        d = dict(src_dict)
        type_ = d.pop("type")

        title = d.pop("title")

        status = d.pop("status")

        code = d.pop("code")

        retryable = d.pop("retryable")

        correlation_id = d.pop("correlationId")

        violations = []
        _violations = d.pop("violations")
        for violations_item_data in _violations:
            violations_item = ProblemDetailsViolationsItem.from_dict(violations_item_data)

            violations.append(violations_item)

        safe_context = ProblemDetailsSafeContext.from_dict(d.pop("safeContext"))

        def _parse_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail = _parse_detail(d.pop("detail", UNSET))

        problem_details = cls(
            type_=type_,
            title=title,
            status=status,
            code=code,
            retryable=retryable,
            correlation_id=correlation_id,
            violations=violations,
            safe_context=safe_context,
            detail=detail,
        )

        return problem_details
