# Boundary Verification Matrix

1. Public OpenAPI ↔ Service serializers ↔ TS generated client ↔ React hooks
2. Private OpenAPI ↔ Routing serializers ↔ Python generated client ↔ RoutingGateway
3. Service DBML ↔ Service models ↔ migrations ↔ retention jobs
4. Routing DBML ↔ Routing models ↔ repositories ↔ partition/index queries
5. Reason/warning/error registry ↔ Routing generation ↔ Service projection ↔ UI rendering
6. Capability registry ↔ `/v1/capabilities` ↔ public support API ↔ disabled UI controls
7. Feature schema ↔ training builder ↔ online builder ↔ model artifact metadata
8. Provider fixture ↔ adapter ↔ canonical model ↔ route candidate ↔ replay expected result
