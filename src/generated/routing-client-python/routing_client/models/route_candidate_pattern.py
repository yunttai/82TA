from enum import Enum


class RouteCandidatePattern(str, Enum):
    TAXI_ONLY = "TAXI_ONLY"
    TAXI_TRANSIT = "TAXI_TRANSIT"
    TAXI_TRANSIT_TAXI = "TAXI_TRANSIT_TAXI"
    TRANSIT_ONLY = "TRANSIT_ONLY"
    TRANSIT_TAXI = "TRANSIT_TAXI"
    TRANSIT_TAXI_BRIDGE_TRANSIT = "TRANSIT_TAXI_BRIDGE_TRANSIT"
    UPSTREAM_STOP_TAXI_TRANSIT = "UPSTREAM_STOP_TAXI_TRANSIT"

    def __str__(self) -> str:
        return str(self.value)
