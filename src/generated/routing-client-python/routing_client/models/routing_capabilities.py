from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.routing_capabilities_bus_intelligence_coverage import RoutingCapabilitiesBusIntelligenceCoverage
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.routing_capabilities_features import RoutingCapabilitiesFeatures
    from ..models.routing_capabilities_models_item import RoutingCapabilitiesModelsItem
    from ..models.routing_capabilities_providers_item import RoutingCapabilitiesProvidersItem
    from ..models.routing_capabilities_region import RoutingCapabilitiesRegion


T = TypeVar("T", bound="RoutingCapabilities")


@_attrs_define
class RoutingCapabilities:
    """
    Attributes:
        generated_at (datetime.datetime):
        region (RoutingCapabilitiesRegion):
        features (RoutingCapabilitiesFeatures):
        providers (list[RoutingCapabilitiesProvidersItem]):
        models (list[RoutingCapabilitiesModelsItem]):
        degraded (list[str]):
        bus_intelligence_coverage (RoutingCapabilitiesBusIntelligenceCoverage | Unset): Optional exact source for the
            public coverage projection. Absence maps to UNKNOWN.
    """

    generated_at: datetime.datetime
    region: RoutingCapabilitiesRegion
    features: RoutingCapabilitiesFeatures
    providers: list[RoutingCapabilitiesProvidersItem]
    models: list[RoutingCapabilitiesModelsItem]
    degraded: list[str]
    bus_intelligence_coverage: RoutingCapabilitiesBusIntelligenceCoverage | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        generated_at = self.generated_at.isoformat()

        region = self.region.to_dict()

        features = self.features.to_dict()

        providers = []
        for providers_item_data in self.providers:
            providers_item = providers_item_data.to_dict()
            providers.append(providers_item)

        models = []
        for models_item_data in self.models:
            models_item = models_item_data.to_dict()
            models.append(models_item)

        degraded = self.degraded

        bus_intelligence_coverage: str | Unset = UNSET
        if not isinstance(self.bus_intelligence_coverage, Unset):
            bus_intelligence_coverage = self.bus_intelligence_coverage.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "generatedAt": generated_at,
                "region": region,
                "features": features,
                "providers": providers,
                "models": models,
                "degraded": degraded,
            }
        )
        if bus_intelligence_coverage is not UNSET:
            field_dict["busIntelligenceCoverage"] = bus_intelligence_coverage

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.routing_capabilities_features import RoutingCapabilitiesFeatures
        from ..models.routing_capabilities_models_item import RoutingCapabilitiesModelsItem
        from ..models.routing_capabilities_providers_item import RoutingCapabilitiesProvidersItem
        from ..models.routing_capabilities_region import RoutingCapabilitiesRegion

        d = dict(src_dict)
        generated_at = datetime.datetime.fromisoformat(d.pop("generatedAt"))

        region = RoutingCapabilitiesRegion.from_dict(d.pop("region"))

        features = RoutingCapabilitiesFeatures.from_dict(d.pop("features"))

        providers = []
        _providers = d.pop("providers")
        for providers_item_data in _providers:
            providers_item = RoutingCapabilitiesProvidersItem.from_dict(providers_item_data)

            providers.append(providers_item)

        models = []
        _models = d.pop("models")
        for models_item_data in _models:
            models_item = RoutingCapabilitiesModelsItem.from_dict(models_item_data)

            models.append(models_item)

        degraded = cast(list[str], d.pop("degraded"))

        _bus_intelligence_coverage = d.pop("busIntelligenceCoverage", UNSET)
        bus_intelligence_coverage: RoutingCapabilitiesBusIntelligenceCoverage | Unset
        if isinstance(_bus_intelligence_coverage, Unset):
            bus_intelligence_coverage = UNSET
        else:
            bus_intelligence_coverage = RoutingCapabilitiesBusIntelligenceCoverage(_bus_intelligence_coverage)

        routing_capabilities = cls(
            generated_at=generated_at,
            region=region,
            features=features,
            providers=providers,
            models=models,
            degraded=degraded,
            bus_intelligence_coverage=bus_intelligence_coverage,
        )

        return routing_capabilities
