from __future__ import annotations

from typing import Any

from .contracts import CanonicalContracts, ContractError, LockedFixtures


def project_public_response(
    routing_response: dict[str, Any],
    contracts: CanonicalContracts,
    fixtures: LockedFixtures,
    support: dict[str, Any] | None = None,
    public_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    private_errors = contracts.validate("private", "OptimizeRouteResponse", routing_response)
    if private_errors:
        raise ContractError("canonical Routing response failed private schema validation")

    routes = {route["routeId"]: route for route in routing_response["routes"]}
    recommendation_ids = routing_response["recommendations"]
    strict_budget = bool(public_request and public_request["taxiBudget"]["strict"])
    budget_max = public_request["taxiBudget"]["maxAmount"] if public_request else None
    for route in routes.values():
        duration = route["totalDuration"]
        if duration["p90Seconds"] < duration["p50Seconds"]:
            raise ContractError("Routing response violates P90 >= P50")
        if strict_budget and route["taxiCost"]["upper"] > budget_max:
            raise ContractError("Routing response violates the strict taxi budget")
    if routing_response["status"] == "COMPLETE":
        missing = [
            identifier
            for identifier in recommendation_ids.values()
            if identifier is not None and identifier not in routes
        ]
        if missing:
            raise ContractError("COMPLETE Routing response references a missing route")
    canonical_support = support or fixtures.get("public_response")["support"]
    baseline = routes.get(recommendation_ids.get("publicTransitOnly"))

    response = {
        "contractVersion": routing_response["contractVersion"],
        "searchId": routing_response["requestId"],
        "status": routing_response["status"],
        "generatedAt": routing_response["generatedAt"],
        "expiresAt": routing_response["expiresAt"],
        "baseline": baseline,
        "recommendations": {
            "fastest": routes.get(recommendation_ids.get("fastest")),
            "stable": routes.get(recommendation_ids.get("stable")),
            "efficient": routes.get(recommendation_ids.get("efficient")),
            "publicTransitOnly": routes.get(recommendation_ids.get("publicTransitOnly")),
        },
        "paretoFrontier": [
            {
                "routeId": route_id,
                "taxiCostUpper": routes[route_id]["taxiCost"]["upper"],
                "p50Seconds": routes[route_id]["totalDuration"]["p50Seconds"],
                "p90Seconds": routes[route_id]["totalDuration"]["p90Seconds"],
            }
            for route_id in routing_response["paretoRouteIds"]
            if route_id in routes
        ],
        "warnings": list(routing_response["warningCodes"]),
        "support": canonical_support,
    }
    public_errors = contracts.validate("public", "PublicRouteSearchResponse", response)
    if public_errors:
        raise ContractError("projected response failed public schema validation")
    return response
