from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.provider_status_status import ProviderStatusStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="ProviderStatus")


@_attrs_define
class ProviderStatus:
    """
    Attributes:
        provider (str):
        status (ProviderStatusStatus):
        latency_ms (int):
        cache (bool):
        operation (None | str | Unset):
        message_code (None | str | Unset):
    """

    provider: str
    status: ProviderStatusStatus
    latency_ms: int
    cache: bool
    operation: None | str | Unset = UNSET
    message_code: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        status = self.status.value

        latency_ms = self.latency_ms

        cache = self.cache

        operation: None | str | Unset
        if isinstance(self.operation, Unset):
            operation = UNSET
        else:
            operation = self.operation

        message_code: None | str | Unset
        if isinstance(self.message_code, Unset):
            message_code = UNSET
        else:
            message_code = self.message_code

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "provider": provider,
                "status": status,
                "latencyMs": latency_ms,
                "cache": cache,
            }
        )
        if operation is not UNSET:
            field_dict["operation"] = operation
        if message_code is not UNSET:
            field_dict["messageCode"] = message_code

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        provider = d.pop("provider")

        status = ProviderStatusStatus(d.pop("status"))

        latency_ms = d.pop("latencyMs")

        cache = d.pop("cache")

        def _parse_operation(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        operation = _parse_operation(d.pop("operation", UNSET))

        def _parse_message_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        message_code = _parse_message_code(d.pop("messageCode", UNSET))

        provider_status = cls(
            provider=provider,
            status=status,
            latency_ms=latency_ms,
            cache=cache,
            operation=operation,
            message_code=message_code,
        )

        return provider_status
