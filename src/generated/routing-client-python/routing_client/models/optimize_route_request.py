from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

from ..models.optimize_route_request_requested_recommendations_item import (
    OptimizeRouteRequestRequestedRecommendationsItem,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.optimization_preference import OptimizationPreference
    from ..models.optimize_route_request_client_context import OptimizeRouteRequestClientContext
    from ..models.optimize_route_request_destination import OptimizeRouteRequestDestination
    from ..models.optimize_route_request_origin import OptimizeRouteRequestOrigin
    from ..models.route_constraints import RouteConstraints


T = TypeVar("T", bound="OptimizeRouteRequest")


@_attrs_define
class OptimizeRouteRequest:
    """
    Attributes:
        contract_version (Literal['1.0']): Major compatibility family. Compatible 1.x contract minors retain this wire
            value.
        request_id (str):
        origin (OptimizeRouteRequestOrigin):
        destination (OptimizeRouteRequestDestination):
        departure_time (datetime.datetime):
        constraints (RouteConstraints):
        preference (OptimizationPreference):
        requested_recommendations (list[OptimizeRouteRequestRequestedRecommendationsItem]):
        client_context (OptimizeRouteRequestClientContext):
        arrival_deadline (datetime.datetime | None | Unset):
    """

    contract_version: Literal["1.0"]
    request_id: str
    origin: OptimizeRouteRequestOrigin
    destination: OptimizeRouteRequestDestination
    departure_time: datetime.datetime
    constraints: RouteConstraints
    preference: OptimizationPreference
    requested_recommendations: list[OptimizeRouteRequestRequestedRecommendationsItem]
    client_context: OptimizeRouteRequestClientContext
    arrival_deadline: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        contract_version = self.contract_version

        request_id = self.request_id

        origin = self.origin.to_dict()

        destination = self.destination.to_dict()

        departure_time = self.departure_time.isoformat()

        constraints = self.constraints.to_dict()

        preference = self.preference.to_dict()

        requested_recommendations = []
        for requested_recommendations_item_data in self.requested_recommendations:
            requested_recommendations_item = requested_recommendations_item_data.value
            requested_recommendations.append(requested_recommendations_item)

        client_context = self.client_context.to_dict()

        arrival_deadline: None | str | Unset
        if isinstance(self.arrival_deadline, Unset):
            arrival_deadline = UNSET
        elif isinstance(self.arrival_deadline, datetime.datetime):
            arrival_deadline = self.arrival_deadline.isoformat()
        else:
            arrival_deadline = self.arrival_deadline

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "contractVersion": contract_version,
                "requestId": request_id,
                "origin": origin,
                "destination": destination,
                "departureTime": departure_time,
                "constraints": constraints,
                "preference": preference,
                "requestedRecommendations": requested_recommendations,
                "clientContext": client_context,
            }
        )
        if arrival_deadline is not UNSET:
            field_dict["arrivalDeadline"] = arrival_deadline

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.optimization_preference import OptimizationPreference
        from ..models.optimize_route_request_client_context import OptimizeRouteRequestClientContext
        from ..models.optimize_route_request_destination import OptimizeRouteRequestDestination
        from ..models.optimize_route_request_origin import OptimizeRouteRequestOrigin
        from ..models.route_constraints import RouteConstraints

        d = dict(src_dict)
        contract_version = cast(Literal["1.0"], d.pop("contractVersion"))
        if contract_version != "1.0":
            raise ValueError(f"contractVersion must match const '1.0', got '{contract_version}'")

        request_id = d.pop("requestId")

        origin = OptimizeRouteRequestOrigin.from_dict(d.pop("origin"))

        destination = OptimizeRouteRequestDestination.from_dict(d.pop("destination"))

        departure_time = datetime.datetime.fromisoformat(d.pop("departureTime"))

        constraints = RouteConstraints.from_dict(d.pop("constraints"))

        preference = OptimizationPreference.from_dict(d.pop("preference"))

        requested_recommendations = []
        _requested_recommendations = d.pop("requestedRecommendations")
        for requested_recommendations_item_data in _requested_recommendations:
            requested_recommendations_item = OptimizeRouteRequestRequestedRecommendationsItem(
                requested_recommendations_item_data
            )

            requested_recommendations.append(requested_recommendations_item)

        client_context = OptimizeRouteRequestClientContext.from_dict(d.pop("clientContext"))

        def _parse_arrival_deadline(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                arrival_deadline_type_0 = datetime.datetime.fromisoformat(data)

                return arrival_deadline_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        arrival_deadline = _parse_arrival_deadline(d.pop("arrivalDeadline", UNSET))

        optimize_route_request = cls(
            contract_version=contract_version,
            request_id=request_id,
            origin=origin,
            destination=destination,
            departure_time=departure_time,
            constraints=constraints,
            preference=preference,
            requested_recommendations=requested_recommendations,
            client_context=client_context,
            arrival_deadline=arrival_deadline,
        )

        return optimize_route_request
