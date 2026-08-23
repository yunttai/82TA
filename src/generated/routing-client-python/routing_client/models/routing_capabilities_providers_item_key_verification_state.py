from enum import Enum


class RoutingCapabilitiesProvidersItemKeyVerificationState(str, Enum):
    FAILED = "FAILED"
    KEY_VERIFIED = "KEY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"

    def __str__(self) -> str:
        return str(self.value)
