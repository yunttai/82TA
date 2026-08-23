from enum import Enum


class ActivateModelVersionBodyEnvironment(str, Enum):
    DEV = "dev"
    PROD = "prod"
    STAGING = "staging"

    def __str__(self) -> str:
        return str(self.value)
