# ADR 0003: UUID identity and immutable submissions

Status: accepted, 2026-07-29

## Decision

Assign UUID4 values to batches, samples, analyses, and artifacts. Preserve
those UUIDs across export/import. Reconcile independent records only through
exact, non-null namespaced identifiers.

A `READY` batch is immutable after registration. Any manifest or read
fingerprint change invalidates the existing record and requires a new
submission.

## Consequences

Laboratories can merge databases without filename collisions or invented
public accessions. Corrected files create an auditable new identity rather
than silently rewriting scientific history.
