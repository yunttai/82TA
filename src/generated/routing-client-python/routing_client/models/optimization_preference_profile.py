from enum import Enum


class OptimizationPreferenceProfile(str, Enum):
    BALANCED = "BALANCED"
    EFFICIENT = "EFFICIENT"
    FASTEST = "FASTEST"
    STABLE = "STABLE"

    def __str__(self) -> str:
        return str(self.value)
