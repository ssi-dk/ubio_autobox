# ADR 0004: Latest-compatible version policy

Status: accepted, 2026-07-29

## Context

The original design named Bactopia 4.0.0, Dagster generally, and the ATB
2025-05 schema. The implementation should use current software where possible,
while reproducible scientific output requires explicit compatibility pins.

## Decision

Use the newest mutually compatible versions verified at each release:

- Bactopia 4.0.0, the current documented output/CLI contract.
- Nextflow 26.04.6, the current Linux resolution for Bactopia 4.0.0.
- `dagster-slurm` 1.15.1.
- Dagster 1.13.x, constrained by `dagster-slurm` 1.15.1.
- AllTheBacteria 2025-05, the latest complete aggregate metadata model.

Lock exact transitive versions in `pixi.lock`. Record runtime Bactopia,
Nextflow, container digest, and reference database versions per analysis.

## Upgrade process

1. Check current upstream releases and compatibility constraints.
2. Capture representative new output fixtures without patient data.
3. Run input, parser, schema, migration, and orchestration contract tests.
4. Review ATB columns, order, types, and quality semantics field by field.
5. Update the compatibility table, lockfile, fixtures, and schema version in
   one reviewed change.

Do not float scientific software or schema versions in production. “Latest”
means newest reviewed compatible baseline, not unpinned runtime resolution.
