from enum import Enum


class RoutingCapabilitiesProvidersItemDocumentationState(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return str(self.value)
