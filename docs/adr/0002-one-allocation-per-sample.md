# ADR 0002: One compute allocation per sample

Status: accepted, 2026-07-29

## Decision

Represent validated input, Bactopia output, normalized results, quality, and
ATB export as one Dagster multi-asset compute boundary. Invoke
`dagster-slurm` once from that boundary.

Bactopia core, CheckM2, and Sylph run sequentially through Nextflow's local
executor inside the allocation.

Each phase is an internal checkpoint boundary. The application records phase
status and output checksums in the result database, while the retained
filesystem workspace contains the checkpoint manifest. Retries validate the
last successful phase and resume the remaining Bactopia workflow within the
same allocation model.

## Consequences

Slurm receives exactly one allocation per sample. Intermediate steps remain
visible as logical assets and persisted provenance, but do not incur separate
queue waits. Nested Slurm submission is unsupported in v1.
