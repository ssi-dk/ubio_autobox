# ubio_autobox Rebuild

**Final project root:** `/Users/b246297/Documents/PublicHealthBox`  
**Canonical repository:** [ssi-dk/ubio_autobox](https://github.com/ssi-dk/ubio_autobox)  
**Git transport:** `git@github.com:ssi-dk/ubio_autobox.git`

## Implementation status — 2026-07-29

The rebuild described below is implemented on
`codex/rebuild-ubio-autobox`. The archive branch and tag are verified on the
remote, the old wrapper repository is preserved as a verified local bundle,
and the source-layout implementation passes formatting, linting, strict
typing, 27 unit/contract/integration tests, Alembic migration coverage, and
Dagster definition loading.

Two deployment acceptance checks require infrastructure unavailable in this
workspace and remain explicit operator smoke tests:

- Run a real tiny-read Bactopia 4 analysis through Docker Compose on a Linux
  Docker host.
- Submit the fixture payload to the target Slurm cluster and confirm one
  allocation plus output parity.

The fake-runner tracer bullet exercises the same lifecycle, persistence,
artifact publication, and ATB projection paths in both local and synthetic
Slurm configurations. It does not stand in for those two infrastructure
checks.

## 1. Mandatory Git safety and workspace setup

This phase must complete before project code changes.

### Preserve the existing implementation

The original implementation from `main` is preserved at commit
`4c65085117674bde1e0227ebef17efd251c4337f` by:

- Archive branch: `ubio_autobox`
- Annotated tag: `archive/pre-rebuild-2026-07-29`

Both references must remain read-only snapshots and must not receive rebuild
commits. GitHub's default branch is unchanged and `main` must never be
force-pushed.

### Normalize the workspace

The old one-commit `PublicHealthBox` wrapper repository is preserved as a
verified Git bundle under `.git/local-backups/`. The final workspace contains
one checkout rooted at `/Users/b246297/Documents/PublicHealthBox`, with:

```text
origin = git@github.com:ssi-dk/ubio_autobox.git
implementation branch = codex/rebuild-ubio-autobox
```

## 2. Product goal

Build a laboratory-oriented service that:

1. Watches an input directory for Illumina paired-end samples.
2. Processes each ready sample automatically with Bactopia.
3. Runs one Dagster partition and one Slurm allocation per sample.
4. Extracts Bactopia, CheckM2, Sylph, assembly, and run statistics.
5. Persists normalized results using SQLAlchemy.
6. Supports DuckDB locally without coupling the design to DuckDB.
7. Allows database backends such as Microsoft SQL Server.
8. Exports DataFrames and Parquet tables compatible with the
   AllTheBacteria 2025-05 schema.
9. Records globally unique identifiers and enough provenance to merge
   databases safely.

Importing the public AllTheBacteria dataset and generating comparative reports
are deferred to a later release. V1 produces comparison-compatible data.

## 3. Rebuild policy and target structure

Preserve useful prototype ideas—Dagster, Pixi, DuckDB, and dynamic per-sample
processing—but make a clean architectural break.

Do not preserve:

- The prototype Python interface or asset names.
- The existing DuckDB schema.
- The monolithic `illumina_workflow.py` design.
- Direct SQL embedded in Dagster assets.
- Relative runtime paths.
- Shell-interpolated commands.
- A Boolean-only processing status.

Adopt:

```text
PublicHealthBox/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── pyproject.toml
├── pixi.toml
├── pixi.lock
├── src/ubio_autobox/
│   ├── config.py
│   ├── cli.py
│   ├── definitions.py
│   ├── domain/
│   ├── ingest/
│   ├── execution/
│   ├── persistence/
│   ├── projection/
│   └── orchestration/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── atb-field-mapping.md
│   └── adr/
└── deploy/
    ├── docker-compose.yml
    ├── config.local.example.yaml
    └── config.slurm.example.yaml
```

Use Python 3.11. Consolidate packaging and tool settings into
`pyproject.toml`. Retain Pixi for development commands while keeping Bactopia
in pinned Linux containers.

### Version policy

The numeric versions in this plan are compatibility baselines, not a request
to preserve outdated dependencies. At implementation and each release, use
the newest mutually compatible versions and lock the resolved environment.
As verified on 2026-07-29:

- Bactopia 4.0.0 is the current documented Bactopia contract.
- Nextflow 26.04.6 is the current compatible Linux resolution.
- `dagster-slurm` 1.15.1 is current and constrains Dagster to 1.13.x.
- AllTheBacteria 2025-05 is the latest complete aggregate metadata model.

Upgrades require fixture-backed CLI/output, orchestration, and schema contract
tests. Production versions remain explicit and reproducible rather than
floating at runtime.

## 4. Input contract

Use immutable batch directories:

```text
incoming/<batch_key>/
├── samples.csv
└── samples/<sample_key>/
    ├── reads_R1.fastq.gz
    ├── reads_R2.fastq.gz
    └── READY
```

Required CSV columns:

- `sample_key`
- `r1`
- `r2`

Recognized optional columns:

- `insdc_sample_accession`
- `source_namespace`
- `source_record_id`

Preserve additional columns as source metadata. Never promote arbitrary
metadata to identity fields automatically.

Before registration:

- Validate safe batch and sample keys.
- Reject duplicate manifest keys.
- Ensure read paths remain beneath the batch directory.
- Reject escaping symlinks and path traversal.
- Require two distinct readable gzip FASTQ files.
- Observe stable file sizes across two sensor evaluations.
- Calculate SHA-256 checksums.
- Require the sample-level `READY` marker.

Inputs become immutable after registration. Changed ready files are marked
invalid and require a new submission rather than overwriting the previous
record.

## 5. Identity, persistence, and provenance

Generate UUID4 values for:

- `batch_id`
- `sample_id`
- `analysis_id`
- `artifact_id`

UUIDs remain unchanged through exports and imports. Independently registered
samples are reconciled only through exact, non-null namespaced identifiers.
Human labels and filenames are never automatic merge keys. Do not synthesize
INSDC or ATB accessions.

Implement SQLAlchemy models for:

- ingest batches
- samples
- sample identifiers
- input files
- analysis runs
- software components
- artifacts
- sequence-run results
- assembly results
- assembly statistics
- Sylph results
- CheckM2 results

Use portable types, UTC timestamps, string-backed statuses, foreign keys,
uniqueness constraints, and Alembic migrations.

Analysis states are:

```text
discovered
validated
queued
running
succeeded
failed
invalid
```

Record input and manifest fingerprints, Dagster run IDs, attempts, pipeline
configuration fingerprints, software/container/reference versions,
timestamps, resolved non-secret arguments, artifact checksums, and failure
summaries.

The default database is DuckDB through `UBIO_DATABASE_URL`. Add an optional
`pyodbc` dependency for SQL Server. Domain and repository code must not use
DuckDB-specific SQL.

## 6. Module interfaces

Keep Dagster orchestration shallow and place scientific and persistence
behavior behind deep module interfaces:

- `InputRegistry`: discover, validate, fingerprint, and register ready samples.
- `BactopiaRunner`: execute a resolved request and return an execution result.
- `ArtifactStore`: allocate workspaces and publish immutable artifacts.
- `ResultRepository`: manage sample identity, analysis lifecycle, provenance,
  and normalized results.
- `AtbProjector`: generate versioned strict and extended ATB datasets.
- `QualityPolicy`: distinguish structural failures from biological warnings.

Commands must be constructed as argument arrays. Never use `shell=True`.

Store artifacts under:

```text
artifacts/samples/<sample_id>/analyses/<analysis_id>/
```

Use attempt-specific staging directories. Publish canonical outputs only after
successful execution and structural parsing. Failed logs remain available but
are not successful scientific artifacts.

Store artifact URIs in the database. Implement local/shared filesystems first
while preserving a seam for future object storage and Slurm scratch staging.

## 7. Dagster and execution design

A sensor runs every 30 seconds by default:

1. Discover batch manifests.
2. Identify stable ready samples.
3. Register samples transactionally.
4. Add each `sample_id` as a dynamic partition.
5. Emit one idempotent run request per sample.

The run key is derived from:

```text
sample_id + input_fingerprint + pipeline_configuration_fingerprint
```

Logical per-sample assets are validated input, Bactopia output, normalized
results, sample quality, and ATB sample export. Represent them through one
graph-backed multi-asset or equivalent single compute boundary so Slurm mode
creates exactly one allocation per sample.

Within that allocation:

1. Generate a one-sample Bactopia samplesheet.
2. Run Bactopia core.
3. Run Bactopia CheckM2.
4. Run Bactopia Sylph.
5. Validate and parse outputs.
6. Persist normalized results.
7. Publish per-sample exports.

Pin Bactopia to 4.0.0 and record the container digest. Keep MLST, AMR,
annotations, reports, and logs as indexed artifacts in v1 without promising
normalized schemas.

### Local deployment

Support host development through `pixi run dagster-dev` and a complete Docker
Compose deployment. Compose includes the Dagster webserver, daemon, user-code
module, and PostgreSQL for Dagster operational state. The canonical scientific
result database remains DuckDB by default.

### Slurm deployment

Use [`dagster-slurm`](https://github.com/ascii-supply-networks/dagster-slurm).
Submit exactly one Slurm allocation per sample, run Nextflow's local executor
inside it, and prohibit nested Slurm submissions in v1. Default to Apptainer on
Slurm while allowing Docker or native execution where supported. Initial
storage is a shared filesystem.

## 8. AllTheBacteria projection

Pin compatibility to the
[AllTheBacteria 2025-05 metadata model](https://allthebacteria.org/docs/metadata_sqlite/).

Version-control the authoritative schema for:

- `run`
- `assembly`
- `assembly_stats`
- `sylph`
- `checkm2`

Document every field in `docs/atb-field-mapping.md` with its type, source,
transformation, nullability, and fixture coverage. Unavailable archive-specific
fields are explicitly null rather than estimated.

Extended exports contain ATB-compatible fields plus `ubio_sample_id`,
`ubio_analysis_id`, and `atb_schema_version`; they retain samples without
public accessions.

Strict exports contain only original ATB fields, include only records with
genuine accessions that satisfy the strict schema, and never substitute UUIDs
for accessions.

Export:

```text
exports/<export_id>/
├── manifest.json
├── run.parquet
├── assembly.parquet
├── assembly_stats.parquet
├── sylph.parquet
├── checkm2.parquet
└── sample_view.parquet
```

Parquet is canonical; TSV is optional. `sample_view.parquet` has one row per
successful analysis and uses `<table>__<column>` names for joined fields.
Preserve all Sylph hits in `sylph.parquet`; use the highest
estimated-abundance hit for the wide view and report the hit count.

## 9. Implementation sequence

1. Complete Git safety and workspace normalization.
2. Introduce the source layout, packaging, configuration, linting, typing,
   tests, CI, architecture documentation, and Dagster definitions.
3. Implement domain types, SQLAlchemy models/repositories, Alembic migrations,
   and DuckDB lifecycle tests.
4. Implement ingestion, dynamic partitions, sensor behavior, and a fake-runner
   tracer bullet.
5. Capture the authoritative ATB schema, add Bactopia fixtures, implement
   parsers, and create strict/extended/wide exports.
6. Implement real Docker execution and local Compose deployment.
7. Integrate Slurm/Apptainer and verify one allocation per sample.
8. Complete retry, recovery, concurrency, operational, and handoff
   documentation.

## 10. Acceptance criteria

The rebuild is complete when:

- Archive branch `ubio_autobox` and the dated tag preserve pre-rebuild `main`.
- `/Users/b246297/Documents/PublicHealthBox` is the only project Git root.
- A valid ready sample is registered exactly once.
- Samples without `READY` are ignored.
- Changed ready inputs cannot overwrite previous records.
- Each sample has UUID identity, immutable checksums, analysis provenance,
  artifacts, and normalized results.
- DuckDB works through SQLAlchemy and SQL Server portability is preserved.
- The five ATB-compatible tables and wide DataFrame export are generated.
- No synthetic accessions are produced.
- Local Docker execution works.
- Slurm submits one allocation per sample.
- Local and Slurm normalized fixture results agree.
- The prototype monolith and duplicate packaging files are removed.
- Unit, contract, migration, orchestration, and lightweight integration tests
  pass.

## 11. Fixed assumptions

- Archive branch: `ubio_autobox`
- Archive tag: `archive/pre-rebuild-2026-07-29`
- Implementation branch: `codex/rebuild-ubio-autobox`
- Git transport: SSH
- V1 input: one Illumina paired-end read pair per sample
- Landing contract: batch CSV plus per-sample `READY`
- Bactopia: 4.0.0
- ATB schema: 2025-05
- Default result database: DuckDB
- Initial Slurm storage: shared filesystem
- Default Slurm runtime: Apptainer
- ATB import and comparison reports: future work

## 12. Local deployment observability — implemented

- Every analysis attempt receives the Dagster run ID supplied by Dagster, or a
  `manual-...` correlation ID for direct CLI execution.
- The database, Dagster Pipes log, and `attempt-manifest.json` expose the
  current execution phase from input validation through Bactopia core,
  CheckM2, Sylph, parsing, export, publication, and terminal completion.
- The database also retains per-attempt phase start/completion timestamps and
  derived durations through the `phase_history` status field.
- Status responses link the active or failed workspace and logs, while retry
  history preserves the previous attempt's run ID, error, and workspace.
- Integration coverage verifies retry registration, run correlation, phase
  transitions, retained workspaces, and the structured attempt manifest.
