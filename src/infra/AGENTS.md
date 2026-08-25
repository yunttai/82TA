# Infrastructure Scope

- Joint stewardship. Existing infrastructure and active deployment workflows are the maintenance baseline.
- GCE is the required and only supported cloud compute platform under ADR-0012. Do not add another cloud path or dual-cloud parity without a superseding explicit architecture decision. The exact GCE topology may evolve from implementation evidence.
- Do not promote demo/development settings to production solely because a deployment filename or target document differs; that requires environment-specific acceptance.
- Preserve public Service/private Routing network boundary, database-per-context, least privilege, secrets management, rollback, backups, observability and cost controls.
