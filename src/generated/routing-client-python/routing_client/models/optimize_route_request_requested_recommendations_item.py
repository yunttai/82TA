from enum import Enum


class OptimizeRouteRequestRequestedRecommendationsItem(str, Enum):
    EFFICIENT = "EFFICIENT"
    FASTEST = "FASTEST"
    PUBLIC_TRANSIT_ONLY = "PUBLIC_TRANSIT_ONLY"
    STABLE = "STABLE"

    def __str__(self) -> str:
        return str(self.value)
