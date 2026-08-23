from enum import Enum


class RouteConstraintsAllowedModesItem(str, Enum):
    BUS = "BUS"
    GTX = "GTX"
    SUBWAY = "SUBWAY"
    TAXI = "TAXI"
    TRAIN = "TRAIN"
    TRANSFER = "TRANSFER"
    WAIT = "WAIT"
    WALK = "WALK"

    def __str__(self) -> str:
        return str(self.value)
