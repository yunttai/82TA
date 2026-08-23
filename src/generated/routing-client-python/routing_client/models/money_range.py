from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

from ..models.money_range_origin import MoneyRangeOrigin

T = TypeVar("T", bound="MoneyRange")


@_attrs_define
class MoneyRange:
    """
    Attributes:
        currency (Literal['KRW']):
        expected (int):
        lower (int):
        upper (int):
        origin (MoneyRangeOrigin):
    """

    currency: Literal["KRW"]
    expected: int
    lower: int
    upper: int
    origin: MoneyRangeOrigin

    def to_dict(self) -> dict[str, Any]:
        currency = self.currency

        expected = self.expected

        lower = self.lower

        upper = self.upper

        origin = self.origin.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "currency": currency,
                "expected": expected,
                "lower": lower,
                "upper": upper,
                "origin": origin,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        currency = cast(Literal["KRW"], d.pop("currency"))
        if currency != "KRW":
            raise ValueError(f"currency must match const 'KRW', got '{currency}'")

        expected = d.pop("expected")

        lower = d.pop("lower")

        upper = d.pop("upper")

        origin = MoneyRangeOrigin(d.pop("origin"))

        money_range = cls(
            currency=currency,
            expected=expected,
            lower=lower,
            upper=upper,
            origin=origin,
        )

        return money_range
