# ADR 0002: One compute allocation per sample

Status: accepted, 2026-07-29

## Decision

Represent validated input, Bactopia output, normalized results, quality, and
ATB export as one Dagster multi-asset compute boundary. Invoke
`dagster-slurm` once from that boundary.

Bactopia core, CheckM2, and Sylph run sequentially through Nextflow's local
executor inside the allocation.

## Consequences

Slurm receives exactly one allocation per sample. Intermediate steps remain
visible as logical assets and persisted provenance, but do not incur separate
queue waits. Nested Slurm submission is unsupported in v1.
