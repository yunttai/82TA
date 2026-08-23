from enum import Enum


class GeometryEncoding(str, Enum):
    GEOJSON = "GEOJSON"
    NONE = "NONE"
    POLYLINE = "POLYLINE"

    def __str__(self) -> str:
        return str(self.value)
