# Workers Scope

- Workstream 2 owns collectors, data quality, training/evaluation jobs.
- Jobs are idempotent, checkpointed, quota-aware, replayable, and observable.
- Online requests never perform training or bulk preprocessing.
