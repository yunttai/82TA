# Service Product Test Matrix

| 영역 | Producer | Consumer | 필수 검증 |
|---|---|---|---|
| Public route response | Service serializer | TS client/query | shape·wrapper·null·enum |
| Routing response | Routing OpenAPI | Python generated client | field·unit·unknown enum |
| UI route | router config | links/navigation | 존재·dynamic param |
| Search state | backend state | UI branch | reachable·dead state |
| Capability | support API | form control | unsupported hidden/disabled |
| Reason/warning | registry | label renderer | 1:1·generic fallback |
| Service DB | DBML/migration | ORM/query | null·index·retention |
| Privacy | request/log | log sink | exact coordinate·token 없음 |

## Fixture Matrix

- complete with all recommendations
- partial without bus data
- partial with ETA fallback
- no feasible strict budget
- transit provider unavailable
- expired result
- unknown warning enum
- geometry partial
- upstream stop
- Taxi Bridge

## Browser Matrix

- current Chromium·Edge
- current Safari mobile equivalent 검토
- Android PWA install flow
- reduced motion·keyboard navigation·screen width

## Security

- IDOR on search/history/favorite
- CSRF state changes
- XSS place/provider strings
- guest token guess/reuse
- login brute force/rate limit
- localStorage credential absence
