# ADR 0001: Deep module boundaries

Status: accepted, 2026-07-29

## Decision

Keep Dagster orchestration shallow. Place input registration, scientific
execution, artifact publication, normalized persistence, quality policy, and
ATB projection behind cohesive interfaces.

## Consequences

The same `SampleProcessor` can run from Dagster, a CLI, or a test. SQL and
Bactopia output details do not leak into assets. There are fewer public
concepts than implementation steps, and tests can exercise domain contracts
without a Dagster daemon or Slurm cluster.
