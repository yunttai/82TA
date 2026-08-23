from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.optimize_route_response_computation_cache import OptimizeRouteResponseComputationCache
    from ..models.optimize_route_response_computation_candidate_counts import (
        OptimizeRouteResponseComputationCandidateCounts,
    )


T = TypeVar("T", bound="OptimizeRouteResponseComputation")


@_attrs_define
class OptimizeRouteResponseComputation:
    """
    Attributes:
        duration_ms (int):
        ranking_policy_version (str):
        candidate_counts (OptimizeRouteResponseComputationCandidateCounts):
        cache (OptimizeRouteResponseComputationCache):
        mapping_version (None | str | Unset):
    """

    duration_ms: int
    ranking_policy_version: str
    candidate_counts: OptimizeRouteResponseComputationCandidateCounts
    cache: OptimizeRouteResponseComputationCache
    mapping_version: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        duration_ms = self.duration_ms

        ranking_policy_version = self.ranking_policy_version

        candidate_counts = self.candidate_counts.to_dict()

        cache = self.cache.to_dict()

        mapping_version: None | str | Unset
        if isinstance(self.mapping_version, Unset):
            mapping_version = UNSET
        else:
            mapping_version = self.mapping_version

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "durationMs": duration_ms,
                "rankingPolicyVersion": ranking_policy_version,
                "candidateCounts": candidate_counts,
                "cache": cache,
            }
        )
        if mapping_version is not UNSET:
            field_dict["mappingVersion"] = mapping_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.optimize_route_response_computation_cache import OptimizeRouteResponseComputationCache
        from ..models.optimize_route_response_computation_candidate_counts import (
            OptimizeRouteResponseComputationCandidateCounts,
        )

        d = dict(src_dict)
        duration_ms = d.pop("durationMs")

        ranking_policy_version = d.pop("rankingPolicyVersion")

        candidate_counts = OptimizeRouteResponseComputationCandidateCounts.from_dict(d.pop("candidateCounts"))

        cache = OptimizeRouteResponseComputationCache.from_dict(d.pop("cache"))

        def _parse_mapping_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mapping_version = _parse_mapping_version(d.pop("mappingVersion", UNSET))

        optimize_route_response_computation = cls(
            duration_ms=duration_ms,
            ranking_policy_version=ranking_policy_version,
            candidate_counts=candidate_counts,
            cache=cache,
            mapping_version=mapping_version,
        )

        return optimize_route_response_computation
