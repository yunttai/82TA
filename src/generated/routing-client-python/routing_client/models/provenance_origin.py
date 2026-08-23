from enum import Enum


class ProvenanceOrigin(str, Enum):
    HISTORICAL_PROXY = "HISTORICAL_PROXY"
    MODEL_PREDICTED = "MODEL_PREDICTED"
    OBSERVED = "OBSERVED"
    PROVIDER_ESTIMATE = "PROVIDER_ESTIMATE"
    UNKNOWN = "UNKNOWN"
    USER_INPUT = "USER_INPUT"

    def __str__(self) -> str:
        return str(self.value)
