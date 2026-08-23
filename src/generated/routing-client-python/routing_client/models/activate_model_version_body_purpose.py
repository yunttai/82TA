from enum import Enum


class ActivateModelVersionBodyPurpose(str, Enum):
    BUS_ETA = "BUS_ETA"
    CALIBRATION = "CALIBRATION"
    SEAT_RISK = "SEAT_RISK"
    TAXI_DISPATCH_WAIT = "TAXI_DISPATCH_WAIT"

    def __str__(self) -> str:
        return str(self.value)
