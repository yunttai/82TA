from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.optimize_route_response_status import OptimizeRouteResponseStatus

if TYPE_CHECKING:
    from ..models.optimize_route_response_computation import OptimizeRouteResponseComputation
    from ..models.optimize_route_response_model_versions_item import OptimizeRouteResponseModelVersionsItem
    from ..models.optimize_route_response_recommendations import OptimizeRouteResponseRecommendations
    from ..models.provider_status import ProviderStatus
    from ..models.route_candidate import RouteCandidate


T = TypeVar("T", bound="OptimizeRouteResponse")


@_attrs_define
class OptimizeRouteResponse:
    """
    Attributes:
        contract_version (str):
        request_id (str):
        status (OptimizeRouteResponseStatus):
        generated_at (datetime.datetime):
        expires_at (datetime.datetime):
        computation (OptimizeRouteResponseComputation):
        recommendations (OptimizeRouteResponseRecommendations):
        routes (list[RouteCandidate]):
        pareto_route_ids (list[str]):
        provider_status (list[ProviderStatus]):
        model_versions (list[OptimizeRouteResponseModelVersionsItem]):
        warning_codes (list[str]):
    """

    contract_version: str
    request_id: str
    status: OptimizeRouteResponseStatus
    generated_at: datetime.datetime
    expires_at: datetime.datetime
    computation: OptimizeRouteResponseComputation
    recommendations: OptimizeRouteResponseRecommendations
    routes: list[RouteCandidate]
    pareto_route_ids: list[str]
    provider_status: list[ProviderStatus]
    model_versions: list[OptimizeRouteResponseModelVersionsItem]
    warning_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        contract_version = self.contract_version

        request_id = self.request_id

        status = self.status.value

        generated_at = self.generated_at.isoformat()

        expires_at = self.expires_at.isoformat()

        computation = self.computation.to_dict()

        recommendations = self.recommendations.to_dict()

        routes = []
        for routes_item_data in self.routes:
            routes_item = routes_item_data.to_dict()
            routes.append(routes_item)

        pareto_route_ids = self.pareto_route_ids

        provider_status = []
        for provider_status_item_data in self.provider_status:
            provider_status_item = provider_status_item_data.to_dict()
            provider_status.append(provider_status_item)

        model_versions = []
        for model_versions_item_data in self.model_versions:
            model_versions_item = model_versions_item_data.to_dict()
            model_versions.append(model_versions_item)

        warning_codes = self.warning_codes

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "contractVersion": contract_version,
                "requestId": request_id,
                "status": status,
                "generatedAt": generated_at,
                "expiresAt": expires_at,
                "computation": computation,
                "recommendations": recommendations,
                "routes": routes,
                "paretoRouteIds": pareto_route_ids,
                "providerStatus": provider_status,
                "modelVersions": model_versions,
                "warningCodes": warning_codes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.optimize_route_response_computation import OptimizeRouteResponseComputation
        from ..models.optimize_route_response_model_versions_item import OptimizeRouteResponseModelVersionsItem
        from ..models.optimize_route_response_recommendations import OptimizeRouteResponseRecommendations
        from ..models.provider_status import ProviderStatus
        from ..models.route_candidate import RouteCandidate

        d = dict(src_dict)
        contract_version = d.pop("contractVersion")

        request_id = d.pop("requestId")

        status = OptimizeRouteResponseStatus(d.pop("status"))

        generated_at = datetime.datetime.fromisoformat(d.pop("generatedAt"))

        expires_at = datetime.datetime.fromisoformat(d.pop("expiresAt"))

        computation = OptimizeRouteResponseComputation.from_dict(d.pop("computation"))

        recommendations = OptimizeRouteResponseRecommendations.from_dict(d.pop("recommendations"))

        routes = []
        _routes = d.pop("routes")
        for routes_item_data in _routes:
            routes_item = RouteCandidate.from_dict(routes_item_data)

            routes.append(routes_item)

        pareto_route_ids = cast(list[str], d.pop("paretoRouteIds"))

        provider_status = []
        _provider_status = d.pop("providerStatus")
        for provider_status_item_data in _provider_status:
            provider_status_item = ProviderStatus.from_dict(provider_status_item_data)

            provider_status.append(provider_status_item)

        model_versions = []
        _model_versions = d.pop("modelVersions")
        for model_versions_item_data in _model_versions:
            model_versions_item = OptimizeRouteResponseModelVersionsItem.from_dict(model_versions_item_data)

            model_versions.append(model_versions_item)

        warning_codes = cast(list[str], d.pop("warningCodes"))

        optimize_route_response = cls(
            contract_version=contract_version,
            request_id=request_id,
            status=status,
            generated_at=generated_at,
            expires_at=expires_at,
            computation=computation,
            recommendations=recommendations,
            routes=routes,
            pareto_route_ids=pareto_route_ids,
            provider_status=provider_status,
            model_versions=model_versions,
            warning_codes=warning_codes,
        )

        return optimize_route_response
