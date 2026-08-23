from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="TaxiBudget")


@_attrs_define
class TaxiBudget:
    """
    Attributes:
        currency (Literal['KRW']):
        max_amount (int):
        strict (bool):
    """

    currency: Literal["KRW"]
    max_amount: int
    strict: bool

    def to_dict(self) -> dict[str, Any]:
        currency = self.currency

        max_amount = self.max_amount

        strict = self.strict

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "currency": currency,
                "maxAmount": max_amount,
                "strict": strict,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        currency = cast(Literal["KRW"], d.pop("currency"))
        if currency != "KRW":
            raise ValueError(f"currency must match const 'KRW', got '{currency}'")

        max_amount = d.pop("maxAmount")

        strict = d.pop("strict")

        taxi_budget = cls(
            currency=currency,
            max_amount=max_amount,
            strict=strict,
        )

        return taxi_budget
