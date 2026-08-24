from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "src/generated/routing-client-python"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_api.settings")

import django  # noqa: E402


django.setup()

from django.apps import apps  # noqa: E402
from django.test import SimpleTestCase  # noqa: E402
from django.urls import Resolver404, resolve  # noqa: E402
from routing_client.models.optimize_route_request import OptimizeRouteRequest  # noqa: E402
from routing_client.models.optimize_route_response import OptimizeRouteResponse  # noqa: E402

from journeys.contracts import CanonicalContracts, LockedFixtures  # noqa: E402
from journeys.gateway import RoutingEnvelope, public_to_private  # noqa: E402
from journeys.models import RouteSearch, SavedPlace, WGS84PointField  # noqa: E402


PUBLIC_OPENAPI = REPOSITORY_ROOT / "src/contracts/openapi/service-public.v1.yaml"
PRIVATE_OPENAPI = REPOSITORY_ROOT / "src/contracts/openapi/routing-private.v1.yaml"
SERVICE_DBML = REPOSITORY_ROOT / "src/contracts/database/service-db.dbml"
CODE_REGISTRY = REPOSITORY_ROOT / "src/contracts/codes/reason-warning-error-codes.yaml"
WEB_SOURCE = REPOSITORY_ROOT / "src/apps/web/src"
PUBLIC_WRAPPER = WEB_SOURCE / "shared/api/publicService.ts"
GENERATED_TS = REPOSITORY_ROOT / "src/generated/service-client-ts/schema.gen.ts"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _concrete_path(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000001", template)


class ServiceFullBoundaryTests(SimpleTestCase):
    maxDiff = None

    def test_every_public_openapi_path_resolves_to_django(self) -> None:
        public = _yaml(PUBLIC_OPENAPI)
        unresolved: list[str] = []
        for template in public["paths"]:
            try:
                resolve(_concrete_path(template))
            except Resolver404:
                unresolved.append(template)
        self.assertEqual(unresolved, [])

    def test_generated_ts_and_react_wrapper_cover_public_operations(self) -> None:
        public = _yaml(PUBLIC_OPENAPI)
        generated = GENERATED_TS.read_text(encoding="utf-8")
        wrapper = PUBLIC_WRAPPER.read_text(encoding="utf-8")
        missing_generated: list[str] = []
        missing_wrapper: list[str] = []
        for path, path_item in public["paths"].items():
            if path not in generated:
                missing_generated.append(path)
            if path not in wrapper:
                missing_wrapper.append(path)
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation_id = operation["operationId"]
                if operation_id not in generated:
                    missing_generated.append(f"{method.upper()} {path} ({operation_id})")
        self.assertEqual(missing_generated, [])
        self.assertEqual(missing_wrapper, [])

    def test_browser_uses_generated_public_types_and_has_no_private_boundary_calls(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(WEB_SOURCE.rglob("*"))
            if path.suffix in {".ts", ".tsx"}
        )
        wrapper = PUBLIC_WRAPPER.read_text(encoding="utf-8")
        self.assertIn('from "@82ta/service-client"', wrapper)
        for forbidden in (
            "/v1/routes/optimize",
            "routing.internal",
            "GBIS",
            "KAKAO_MOBILITY",
            "providerStatus",
            "modelVersions",
        ):
            self.assertNotIn(forbidden, source)

    def test_locked_fixtures_round_trip_generated_private_models(self) -> None:
        fixtures = LockedFixtures()
        contracts = CanonicalContracts()
        request = fixtures.get("routing_request")
        response = fixtures.get("routing_response")
        self.assertEqual(contracts.validate("private", "OptimizeRouteRequest", request), [])
        self.assertEqual(contracts.validate("private", "OptimizeRouteResponse", response), [])
        typed_request = OptimizeRouteRequest.from_dict(request).to_dict()
        typed_response = OptimizeRouteResponse.from_dict(response).to_dict()
        self.assertEqual(contracts.validate("private", "OptimizeRouteRequest", typed_request), [])
        self.assertEqual(contracts.validate("private", "OptimizeRouteResponse", typed_response), [])
        self.assertEqual(typed_response["requestId"], response["requestId"])
        self.assertEqual(typed_response["status"], response["status"])

    def test_public_to_private_translation_is_schema_valid_and_service_safe(self) -> None:
        fixtures = LockedFixtures()
        public_request = fixtures.get("public_request")
        private_request = public_to_private(
            public_request,
            RoutingEnvelope(
                correlation_id="qa-correlation",
                idempotency_key="qa-idempotency-key",
                request_deadline="2026-08-23T14:00:00+09:00",
            ),
        )
        self.assertEqual(CanonicalContracts().validate("private", "OptimizeRouteRequest", private_request), [])
        encoded = json.dumps(private_request, ensure_ascii=False)
        for forbidden in (
            "displayName",
            "providerPlaceId",
            "saveToHistory",
            "guestToken",
            "userId",
            "email",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_service_dbml_tables_match_orm_and_initial_migration(self) -> None:
        dbml_tables = set(
            re.findall(r"^Table\s+([a-z0-9_]+)\s*\{", SERVICE_DBML.read_text(encoding="utf-8"), re.MULTILINE)
        )
        orm_tables = {
            model._meta.db_table
            for model in apps.get_app_config("journeys").get_models()
        }
        migration_source = (
            SERVICE_ROOT / "journeys/migrations/0001_initial.py"
        ).read_text(encoding="utf-8")
        migration_tables = set(re.findall(r'"db_table":\s*"([a-z0-9_]+)"', migration_source))
        self.assertEqual(orm_tables, dbml_tables)
        self.assertEqual(migration_tables, dbml_tables)

    def test_dbml_geography_is_postgis_backed_in_model_and_migration(self) -> None:
        dbml = SERVICE_DBML.read_text(encoding="utf-8")
        migration = (
            SERVICE_ROOT / "journeys/migrations/0001_initial.py"
        ).read_text(encoding="utf-8")

        self.assertRegex(dbml, r"coordinate geography \[not null\]")
        self.assertRegex(dbml, r"origin_coordinate geography \[not null\]")
        self.assertRegex(dbml, r"destination_coordinate geography \[not null\]")
        self.assertIsInstance(SavedPlace._meta.get_field("coordinate"), WGS84PointField)
        self.assertIsInstance(RouteSearch._meta.get_field("origin_coordinate"), WGS84PointField)
        self.assertIsInstance(RouteSearch._meta.get_field("destination_coordinate"), WGS84PointField)
        self.assertIn('return "geography(Point,4326)"', (SERVICE_ROOT / "journeys/models.py").read_text(encoding="utf-8"))
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis', migration)

    def test_offline_and_uncertain_retry_preserve_user_control_and_idempotency(self) -> None:
        hook = (WEB_SOURCE / "features/route-search/useRouteSearch.ts").read_text(encoding="utf-8")
        app = (WEB_SOURCE / "app/App.tsx").read_text(encoding="utf-8")
        form = (WEB_SOURCE / "features/route-search/SearchForm.tsx").read_text(encoding="utf-8")
        wrapper = PUBLIC_WRAPPER.read_text(encoding="utf-8")
        component_test = (WEB_SOURCE / "app/App.test.tsx").read_text(encoding="utf-8")

        self.assertIn("lastAttempt.current = { request, idempotencyKey }", hook)
        self.assertIn("execute(lastAttempt.current.request, lastAttempt.current.idempotencyKey)", hook)
        self.assertIn("createRouteSearch(request, idempotencyKey)", hook)
        self.assertIn('"Idempotency-Key": idempotencyKey', wrapper)
        self.assertIn("offline={!online}", app)
        self.assertIn("if (offline) return", form)
        self.assertIn("disabled={busy || offline}", form)
        self.assertIn("retries an uncertain network result with the exact same body and idempotency key", component_test)

    def test_generated_client_sources_are_present_and_not_ignored(self) -> None:
        required = (
            "src/generated/generate-clients.sh",
            "src/generated/verify-reproducibility.sh",
            "src/generated/service-client-ts/schema.gen.ts",
            "src/generated/service-client-ts/client.gen.ts",
            "src/generated/routing-client-python/routing_client/client.py",
            "src/generated/routing-client-python/routing_client/models/optimize_route_request.py",
        )
        for relative in required:
            self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", relative],
                cwd=REPOSITORY_ROOT,
                check=False,
            )
            self.assertEqual(ignored.returncode, 1, relative)

    def test_web_links_have_reachable_static_and_dynamic_pages(self) -> None:
        app = (WEB_SOURCE / "app/App.tsx").read_text(encoding="utf-8")
        pages = (WEB_SOURCE / "pages/ServicePages.tsx").read_text(encoding="utf-8")
        results = (WEB_SOURCE / "features/route-results/ResultPanel.tsx").read_text(encoding="utf-8")
        for path in (
            "/",
            "/history",
            "/favorites",
            "/me",
            "/account",
            "/places",
            "/preferences",
            "/support",
            "/privacy",
        ):
            self.assertIn(f'"{path}"', app + pages)
        self.assertIn(r"^\/searches\/([^/]+)$", app)
        self.assertIn(r"^\/searches\/([^/]+)\/routes\/([^/]+)$", app)
        self.assertIn(r"^\/searches\/([^/]+)\/routes\/([^/]+)\/bus\/([^/]+)$", app)
        self.assertIn("/searches/${encodeURIComponent(searchId)}", pages + results)

    def test_search_states_capabilities_and_code_registry_reach_ui(self) -> None:
        registry = _yaml(CODE_REGISTRY)
        hook = (WEB_SOURCE / "features/route-search/useRouteSearch.ts").read_text(encoding="utf-8")
        form = (WEB_SOURCE / "features/route-search/SearchForm.tsx").read_text(encoding="utf-8")
        panel = (WEB_SOURCE / "features/route-results/ResultPanel.tsx").read_text(encoding="utf-8")
        generated = GENERATED_TS.read_text(encoding="utf-8")

        for state in registry["enums"]["SearchStatus"]:
            self.assertIn(f'"{state}"', hook + panel + generated)
        for code in registry["reasonCodes"]:
            self.assertIn(code, panel)
        for code in registry["warningCodes"]:
            self.assertIn(code, panel)
        for feature in (
            "currentTransit",
            "futureTransit",
            "currentTaxi",
            "futureTaxi",
            "multiDestinationTaxi",
            "busSeatRisk",
            "busEtaModel",
            "taxiBridge",
            "realtimeRerouting",
        ):
            self.assertIn(feature, panel)
        self.assertIn("capabilities?.features?.taxiBridge !== true", form)
        self.assertIn(
            "capabilities?.features?.busSeatRisk === true && draft.avoidHighBusSeatRisk",
            form,
        )

    def test_bus_unknown_stale_low_confidence_and_high_gate_are_explicit(self) -> None:
        panel = (WEB_SOURCE / "features/route-results/ResultPanel.tsx").read_text(encoding="utf-8")
        self.assertIn('mappingGrade === "HIGH"', panel)
        self.assertNotIn('mappingGrade === "HIGH" || mappingGrade === "MEDIUM"', panel)
        generated = GENERATED_TS.read_text(encoding="utf-8")
        for coverage in ("LIVE", "PARTIAL", "HISTORICAL", "UNSUPPORTED", "UNKNOWN"):
            self.assertIn(f'"{coverage}"', generated)
        self.assertIn("intelligence.coverage", panel)
        for token in (
            "UNKNOWN",
            "DATA_STALE",
            "BUS_MAPPING_LOW_CONFIDENCE",
            "정보 없음",
            "boardabilityProxy",
            "실제 탑승을 보장하지 않습니다.",
        ):
            self.assertIn(token, panel)
        self.assertNotIn("승차 가능성 대용값", panel)


if __name__ == "__main__":
    import unittest

    unittest.main()
