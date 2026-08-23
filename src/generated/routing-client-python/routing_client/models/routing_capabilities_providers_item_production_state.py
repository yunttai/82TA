from enum import Enum


class RoutingCapabilitiesProvidersItemProductionState(str, Enum):
    BLOCKED = "BLOCKED"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    UNAPPROVED = "UNAPPROVED"

    def __str__(self) -> str:
        return str(self.value)
