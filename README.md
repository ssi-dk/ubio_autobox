# ubio_autobox

`ubio_autobox` turns an immutable pair of Illumina FASTQ files into normalized,
provenance-rich Bactopia results and AllTheBacteria-compatible Parquet tables.
Dagster handles discovery and idempotency; the scientific and database behavior
remains usable without Dagster.

The service is intentionally comparison-compatible, not an AllTheBacteria
mirror. It does not invent public accessions, import the public dataset, or
claim that local samples belong to an ATB release.

## Compatibility baseline

The rebuild uses the newest mutually compatible versions verified on
2026-07-29:

| Component | Baseline | Why |
|---|---:|---|
| Bactopia | 4.0.0 | Current documented Bactopia release and output contract |
| Nextflow | 26.04.6 | Current Linux resolution compatible with Bactopia 4.0.0 |
| Dagster | 1.13.x | Newest series supported by `dagster-slurm` 1.15.1 |
| dagster-slurm | 1.15.1 | Current package release used for local/Slurm parity |
| AllTheBacteria metadata | 2025-05 | Current complete aggregate metadata model |
| Python | 3.11 | Stable common denominator for local and HPC deployments |

These are compatibility pins, not a promise to remain on old releases.
Upgrades are expected after contract fixtures pass; see
[`docs/adr/0004-version-policy.md`](docs/adr/0004-version-policy.md).
Bactopia task-container names are collected from Nextflow traces, with
`sha256` digests retained whenever the runtime reports them.

Authoritative upstream documentation:
[Bactopia](https://bactopia.io/),
[Dagster](https://docs.dagster.io/),
[`dagster-slurm`](https://github.com/ascii-supply-networks/dagster-slurm),
and [AllTheBacteria metadata](https://allthebacteria.org/docs/metadata_sqlite/).

## Input contract

Create a complete batch, then add each sample's empty `READY` marker last:

```text
.ubio/incoming/batch-2026-001/
├── samples.csv
└── samples/
    └── isolate-001/
        ├── reads_R1.fastq.gz
        ├── reads_R2.fastq.gz
        └── READY
```

`samples.csv`:

```csv
sample_key,r1,r2,insdc_sample_accession,source_namespace,source_record_id
isolate-001,samples/isolate-001/reads_R1.fastq.gz,samples/isolate-001/reads_R2.fastq.gz,,,
```

The registry requires safe keys, paths confined to the batch, distinct gzip
FASTQs, a `READY` marker, stable file observations, and SHA-256 checksums.
Registration makes the manifest and inputs immutable. Changed inputs are
invalidated and must be submitted as a new batch/sample.

## Local development

```bash
pixi install
pixi run ubio-autobox init-db
pixi run dagster-dev
```

Dagster scans every 30 seconds. Each registered `sample_id` becomes a dynamic
partition and receives an idempotent run key derived from the sample UUID,
input fingerprint, and pipeline configuration fingerprint.

For a dependency-free scientific tracer test:

```bash
UBIO_BACTOPIA_RUNNER=fake pixi run pytest
```

The Bactopia and Nextflow packages are locked for `linux-64`. On macOS, use
the fake runner for host-side development and Docker Compose for real
scientific processing. A Linux host can run the pinned environment directly.

For a direct registered-sample run:

```bash
pixi run ubio-autobox process <sample-uuid>
```

The default scientific database URL is
`duckdb:///<data-root>/state/ubio.duckdb`. Override it with
`UBIO_DATABASE_URL`; SQL Server support is installed with the `mssql` extra.

## Docker Compose

Copy `deploy/.env.example` to `deploy/.env`, set `UBIO_DATA_ROOT` to an
absolute host path, and run:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build
```

Compose runs the Dagster webserver, daemon, user-code service, and PostgreSQL
for Dagster operational state. Scientific results still use DuckDB by default.
The Docker socket is mounted so Nextflow can launch pinned scientific
containers. This grants the user-code service host-level Docker control; use a
dedicated host or a socket proxy with an appropriately narrow policy.

The data root is mounted at the same absolute path inside user code because
sibling containers launched through the host Docker daemon must resolve the
same paths.

## Slurm

Start from `deploy/config.slurm.example.yaml` and set `UBIO_CONFIG_FILE`.
Slurm mode uses `dagster-slurm` per-asset execution. The five logical assets
are represented by one graph-backed compute boundary, so a sample submits one
allocation. Bactopia/Nextflow run locally inside that allocation; nested Slurm
submission is not enabled. Shared storage and Apptainer are the v1 defaults;
Bactopia's profile is named `singularity`, which Nextflow uses with the
Apptainer runtime. `dagster-slurm` packages the locked Linux Pixi environment
for the allocation; Apptainer itself is expected to be installed by the
cluster.

## Outputs

Successful attempts are published immutably beneath:

```text
artifacts/samples/<sample_id>/analyses/<analysis_id>/published/attempt-0001/
```

Each per-sample export contains:

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

Extended tables retain local records and add `ubio_sample_id`,
`ubio_analysis_id`, and `atb_schema_version`. Strict tables contain only ATB
columns and exclude records without genuine public accessions. UUIDs are never
substituted for accessions.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/atb-field-mapping.md`](docs/atb-field-mapping.md), and
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
