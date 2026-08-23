from enum import Enum


class RoutingReadinessResponse200Status(str, Enum):
    DEGRADED = "degraded"
    READY = "ready"

    def __str__(self) -> str:
        return str(self.value)
