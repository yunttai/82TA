from enum import Enum


class OptimizeRouteResponseStatus(str, Enum):
    COMPLETE = "COMPLETE"
    NO_FEASIBLE_ROUTE = "NO_FEASIBLE_ROUTE"
    PARTIAL = "PARTIAL"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"

    def __str__(self) -> str:
        return str(self.value)
