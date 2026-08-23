from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.route_leg_mode import RouteLegMode
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.bus_leg_intelligence import BusLegIntelligence
    from ..models.geometry import Geometry
    from ..models.money_range import MoneyRange
    from ..models.provenance import Provenance
    from ..models.route_leg_transit_type_0 import RouteLegTransitType0
    from ..models.stop_ref import StopRef
    from ..models.time_estimate import TimeEstimate


T = TypeVar("T", bound="RouteLeg")


@_attrs_define
class RouteLeg:
    """
    Attributes:
        leg_id (str):
        sequence (int):
        mode (RouteLegMode):
        from_ (StopRef):
        to (StopRef):
        duration (TimeEstimate):
        distance_meters (int):
        fare (MoneyRange):
        geometry (Geometry):
        provenance (list[Provenance]):
        expected_start_at (datetime.datetime | None | Unset):
        expected_end_at (datetime.datetime | None | Unset):
        wait_duration (TimeEstimate | Unset):
        travel_duration (TimeEstimate | Unset):
        transit (None | RouteLegTransitType0 | Unset):
        bus_intelligence (BusLegIntelligence | None | Unset):
    """

    leg_id: str
    sequence: int
    mode: RouteLegMode
    from_: StopRef
    to: StopRef
    duration: TimeEstimate
    distance_meters: int
    fare: MoneyRange
    geometry: Geometry
    provenance: list[Provenance]
    expected_start_at: datetime.datetime | None | Unset = UNSET
    expected_end_at: datetime.datetime | None | Unset = UNSET
    wait_duration: TimeEstimate | Unset = UNSET
    travel_duration: TimeEstimate | Unset = UNSET
    transit: None | RouteLegTransitType0 | Unset = UNSET
    bus_intelligence: BusLegIntelligence | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.bus_leg_intelligence import BusLegIntelligence
        from ..models.route_leg_transit_type_0 import RouteLegTransitType0

        leg_id = self.leg_id

        sequence = self.sequence

        mode = self.mode.value

        from_ = self.from_.to_dict()

        to = self.to.to_dict()

        duration = self.duration.to_dict()

        distance_meters = self.distance_meters

        fare = self.fare.to_dict()

        geometry = self.geometry.to_dict()

        provenance = []
        for provenance_item_data in self.provenance:
            provenance_item = provenance_item_data.to_dict()
            provenance.append(provenance_item)

        expected_start_at: None | str | Unset
        if isinstance(self.expected_start_at, Unset):
            expected_start_at = UNSET
        elif isinstance(self.expected_start_at, datetime.datetime):
            expected_start_at = self.expected_start_at.isoformat()
        else:
            expected_start_at = self.expected_start_at

        expected_end_at: None | str | Unset
        if isinstance(self.expected_end_at, Unset):
            expected_end_at = UNSET
        elif isinstance(self.expected_end_at, datetime.datetime):
            expected_end_at = self.expected_end_at.isoformat()
        else:
            expected_end_at = self.expected_end_at

        wait_duration: dict[str, Any] | Unset = UNSET
        if not isinstance(self.wait_duration, Unset):
            wait_duration = self.wait_duration.to_dict()

        travel_duration: dict[str, Any] | Unset = UNSET
        if not isinstance(self.travel_duration, Unset):
            travel_duration = self.travel_duration.to_dict()

        transit: dict[str, Any] | None | Unset
        if isinstance(self.transit, Unset):
            transit = UNSET
        elif isinstance(self.transit, RouteLegTransitType0):
            transit = self.transit.to_dict()
        else:
            transit = self.transit

        bus_intelligence: dict[str, Any] | None | Unset
        if isinstance(self.bus_intelligence, Unset):
            bus_intelligence = UNSET
        elif isinstance(self.bus_intelligence, BusLegIntelligence):
            bus_intelligence = self.bus_intelligence.to_dict()
        else:
            bus_intelligence = self.bus_intelligence

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "legId": leg_id,
                "sequence": sequence,
                "mode": mode,
                "from": from_,
                "to": to,
                "duration": duration,
                "distanceMeters": distance_meters,
                "fare": fare,
                "geometry": geometry,
                "provenance": provenance,
            }
        )
        if expected_start_at is not UNSET:
            field_dict["expectedStartAt"] = expected_start_at
        if expected_end_at is not UNSET:
            field_dict["expectedEndAt"] = expected_end_at
        if wait_duration is not UNSET:
            field_dict["waitDuration"] = wait_duration
        if travel_duration is not UNSET:
            field_dict["travelDuration"] = travel_duration
        if transit is not UNSET:
            field_dict["transit"] = transit
        if bus_intelligence is not UNSET:
            field_dict["busIntelligence"] = bus_intelligence

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bus_leg_intelligence import BusLegIntelligence
        from ..models.geometry import Geometry
        from ..models.money_range import MoneyRange
        from ..models.provenance import Provenance
        from ..models.route_leg_transit_type_0 import RouteLegTransitType0
        from ..models.stop_ref import StopRef
        from ..models.time_estimate import TimeEstimate

        d = dict(src_dict)
        leg_id = d.pop("legId")

        sequence = d.pop("sequence")

        mode = RouteLegMode(d.pop("mode"))

        from_ = StopRef.from_dict(d.pop("from"))

        to = StopRef.from_dict(d.pop("to"))

        duration = TimeEstimate.from_dict(d.pop("duration"))

        distance_meters = d.pop("distanceMeters")

        fare = MoneyRange.from_dict(d.pop("fare"))

        geometry = Geometry.from_dict(d.pop("geometry"))

        provenance = []
        _provenance = d.pop("provenance")
        for provenance_item_data in _provenance:
            provenance_item = Provenance.from_dict(provenance_item_data)

            provenance.append(provenance_item)

        def _parse_expected_start_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expected_start_at_type_0 = datetime.datetime.fromisoformat(data)

                return expected_start_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        expected_start_at = _parse_expected_start_at(d.pop("expectedStartAt", UNSET))

        def _parse_expected_end_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expected_end_at_type_0 = datetime.datetime.fromisoformat(data)

                return expected_end_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        expected_end_at = _parse_expected_end_at(d.pop("expectedEndAt", UNSET))

        _wait_duration = d.pop("waitDuration", UNSET)
        wait_duration: TimeEstimate | Unset
        if isinstance(_wait_duration, Unset):
            wait_duration = UNSET
        else:
            wait_duration = TimeEstimate.from_dict(_wait_duration)

        _travel_duration = d.pop("travelDuration", UNSET)
        travel_duration: TimeEstimate | Unset
        if isinstance(_travel_duration, Unset):
            travel_duration = UNSET
        else:
            travel_duration = TimeEstimate.from_dict(_travel_duration)

        def _parse_transit(data: object) -> None | RouteLegTransitType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                transit_type_0 = RouteLegTransitType0.from_dict(data)

                return transit_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RouteLegTransitType0 | Unset, data)

        transit = _parse_transit(d.pop("transit", UNSET))

        def _parse_bus_intelligence(data: object) -> BusLegIntelligence | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                bus_intelligence_type_0 = BusLegIntelligence.from_dict(data)

                return bus_intelligence_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BusLegIntelligence | None | Unset, data)

        bus_intelligence = _parse_bus_intelligence(d.pop("busIntelligence", UNSET))

        route_leg = cls(
            leg_id=leg_id,
            sequence=sequence,
            mode=mode,
            from_=from_,
            to=to,
            duration=duration,
            distance_meters=distance_meters,
            fare=fare,
            geometry=geometry,
            provenance=provenance,
            expected_start_at=expected_start_at,
            expected_end_at=expected_end_at,
            wait_duration=wait_duration,
            travel_duration=travel_duration,
            transit=transit,
            bus_intelligence=bus_intelligence,
        )

        return route_leg
