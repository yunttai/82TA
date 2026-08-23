from enum import Enum


class RoutingCapabilitiesBusIntelligenceCoverage(str, Enum):
    HISTORICAL = "HISTORICAL"
    LIVE = "LIVE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"

    def __str__(self) -> str:
        return str(self.value)
