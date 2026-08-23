from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="OptimizeRouteResponseComputationCandidateCounts")


@_attrs_define
class OptimizeRouteResponseComputationCandidateCounts:
    """
    Attributes:
        generated (int):
        coarse_pruned (int):
        fully_evaluated (int):
        pareto (int):
    """

    generated: int
    coarse_pruned: int
    fully_evaluated: int
    pareto: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        generated = self.generated

        coarse_pruned = self.coarse_pruned

        fully_evaluated = self.fully_evaluated

        pareto = self.pareto

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "generated": generated,
                "coarsePruned": coarse_pruned,
                "fullyEvaluated": fully_evaluated,
                "pareto": pareto,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        generated = d.pop("generated")

        coarse_pruned = d.pop("coarsePruned")

        fully_evaluated = d.pop("fullyEvaluated")

        pareto = d.pop("pareto")

        optimize_route_response_computation_candidate_counts = cls(
            generated=generated,
            coarse_pruned=coarse_pruned,
            fully_evaluated=fully_evaluated,
            pareto=pareto,
        )

        optimize_route_response_computation_candidate_counts.additional_properties = d
        return optimize_route_response_computation_candidate_counts

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
