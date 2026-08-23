"""Precision-first canonical transport entity mapping.

The package intentionally accepts provider-agnostic value objects rather than
provider payloads or ORM models.  Persistence adapters can project these
results onto the canonical ``provider_entity``, ``entity_mapping`` and
``mapping_review`` tables.
"""

from .fingerprint import candidate_fingerprint, mapping_cache_key, provider_fingerprint
from .catalog import (
    CatalogQuery,
    DisabledGitsRoadLinkIdentityRepository,
    GbisCatalogRepository,
    GitsRoadLinkIdentityRecord,
    GitsRoadLinkIdentityRepository,
    InMemoryGbisCatalogRepository,
    InMemoryGitsRoadLinkIdentityRepository,
    enrich_selected_gits_road_link_target,
    geometry_similarity,
)
from .extractors import (
    CanonicalIdentityExtractionError,
    TransitProvider,
    extract_provider_identity,
)
from .gold_set import (
    ConfusionMatrix,
    GoldReviewProvenance,
    GoldSetCase,
    GoldSetEvaluation,
    GoldSetMetrics,
    ProviderGoldMetrics,
    evaluate_gold_set,
)
from .models import (
    CanonicalRouteCandidate,
    GITS_ROAD_LINK_IDENTITY_VERSION,
    GitsRoadLinkIdentity,
    MAX_GITS_ROAD_LINK_IDS,
    MappingGrade,
    MappingResult,
    PersistedMappingResolution,
    ProviderMappingInput,
    ReviewDisposition,
    StopSignal,
    ValidityWindow,
    gits_road_link_identity_fingerprint,
    gits_road_link_normalized_identity,
)
from .normalization import (
    normalize_branch,
    normalize_direction,
    normalize_route_name,
    normalize_stop_name,
)
from .pipeline import (
    AcceptedHighMappingEntry,
    AcceptedHighMappingRepository,
    InMemoryMappingReviewRepository,
    MappingPipelineResult,
    MappingReviewRepository,
    ReviewQueueEntry,
    TransportMappingPipeline,
)
from .postgres import (
    MappingDatabaseError,
    MappingDatabaseUnavailable,
    MappingQueryBoundsError,
    MappingRowSchemaError,
    PostgisGbisCatalogRepository,
    PostgisGitsRoadLinkIdentityRepository,
    PostgresAcceptedHighMappingRepository,
    PostgresMappingReviewRepository,
    SqlDatabase,
    SqlSession,
)
from .reviewed_gold import representative_reviewed_gold_cases
from .scoring import DEFAULT_MAPPING_VERSION, map_candidate

__all__ = [
    "CanonicalRouteCandidate",
    "CanonicalIdentityExtractionError",
    "CatalogQuery",
    "ConfusionMatrix",
    "DEFAULT_MAPPING_VERSION",
    "DisabledGitsRoadLinkIdentityRepository",
    "GbisCatalogRepository",
    "GITS_ROAD_LINK_IDENTITY_VERSION",
    "GitsRoadLinkIdentity",
    "GitsRoadLinkIdentityRecord",
    "GitsRoadLinkIdentityRepository",
    "GoldReviewProvenance",
    "GoldSetCase",
    "GoldSetEvaluation",
    "GoldSetMetrics",
    "InMemoryGbisCatalogRepository",
    "InMemoryGitsRoadLinkIdentityRepository",
    "InMemoryMappingReviewRepository",
    "AcceptedHighMappingEntry",
    "AcceptedHighMappingRepository",
    "MappingGrade",
    "MAX_GITS_ROAD_LINK_IDS",
    "MappingDatabaseError",
    "MappingDatabaseUnavailable",
    "MappingQueryBoundsError",
    "MappingResult",
    "PersistedMappingResolution",
    "MappingRowSchemaError",
    "ProviderMappingInput",
    "ProviderGoldMetrics",
    "ReviewDisposition",
    "ReviewQueueEntry",
    "StopSignal",
    "ValidityWindow",
    "TransitProvider",
    "TransportMappingPipeline",
    "PostgisGbisCatalogRepository",
    "PostgisGitsRoadLinkIdentityRepository",
    "PostgresAcceptedHighMappingRepository",
    "PostgresMappingReviewRepository",
    "SqlDatabase",
    "SqlSession",
    "candidate_fingerprint",
    "evaluate_gold_set",
    "enrich_selected_gits_road_link_target",
    "extract_provider_identity",
    "geometry_similarity",
    "gits_road_link_identity_fingerprint",
    "gits_road_link_normalized_identity",
    "map_candidate",
    "mapping_cache_key",
    "normalize_branch",
    "normalize_direction",
    "normalize_route_name",
    "normalize_stop_name",
    "provider_fingerprint",
    "representative_reviewed_gold_cases",
    "MappingPipelineResult",
    "MappingReviewRepository",
]
