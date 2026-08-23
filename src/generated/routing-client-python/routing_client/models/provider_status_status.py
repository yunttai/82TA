from enum import Enum


class ProviderStatusStatus(str, Enum):
    BAD_RESPONSE = "BAD_RESPONSE"
    DISABLED = "DISABLED"
    OK = "OK"
    PARTIAL = "PARTIAL"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:
        return str(self.value)
