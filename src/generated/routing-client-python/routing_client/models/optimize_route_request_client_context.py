from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="OptimizeRouteRequestClientContext")


@_attrs_define
class OptimizeRouteRequestClientContext:
    """
    Attributes:
        locale (str):  Default: 'ko-KR'.
        timezone (Literal['Asia/Seoul']):
    """

    timezone: Literal["Asia/Seoul"]
    locale: str = "ko-KR"

    def to_dict(self) -> dict[str, Any]:
        locale = self.locale

        timezone = self.timezone

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "locale": locale,
                "timezone": timezone,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        locale = d.pop("locale")

        timezone = cast(Literal["Asia/Seoul"], d.pop("timezone"))
        if timezone != "Asia/Seoul":
            raise ValueError(f"timezone must match const 'Asia/Seoul', got '{timezone}'")

        optimize_route_request_client_context = cls(
            locale=locale,
            timezone=timezone,
        )

        return optimize_route_request_client_context
