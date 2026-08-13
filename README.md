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

Additional manifest columns are retained as source metadata. When a manifest
contains `species`, the value is passed into Bactopia's `species` samplesheet
column.

## Local development

```bash
pixi install
pixi run ubio-autobox migrate
pixi run dagster-dev
```

`init-db` remains a compatibility alias for the same idempotent packaged
Alembic migration path.

Dagster scans every 30 seconds by default (`sensor.interval_seconds`). Each
registered `sample_id` becomes a dynamic partition and receives an idempotent
run key derived from the sample UUID, input fingerprint, and pipeline
configuration fingerprint. A sample is not re-queued on every poll once it is
running, failed, or complete; use Dagster re-execution for a visible retry.

For a dependency-free scientific tracer test:

```bash
UBIO_BACTOPIA_RUNNER=fake pixi run pytest
```

For a fast end-to-end smoke run that generates tiny valid paired FASTQs,
metadata, `READY` markers, registrations, artifacts, and normalized results:

```bash
pixi run ubio-autobox synthetic-run \
  --config examples/config.synthetic.yaml \
  --samples 3
```

Use `--no-process` when you only want to generate the landing batch for the
periodic Dagster sensor. To run Dagster against that isolated synthetic
configuration, use:

```bash
UBIO_CONFIG_FILE="$PWD/examples/config.synthetic.yaml" pixi run dagster-dev
```

Synthetic runs always use the fake Bactopia adapter; keep their
`.ubio-synthetic` data root separate from real inputs.

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

## Deployment interface

Deployment topology is owned outside this public application repository. A
deployment workspace is expected to provide sibling `app`, `deploy`,
`automation`, `private`, and `runtimes` paths. The application-owned image is
built from the repository root with:

```bash
docker build -f packaging/docker/Dockerfile -t ubio-autobox:<git-sha> .
```

Deploy tooling should use these stable operational commands:

```bash
ubio-autobox validate-config --config /path/to/config.yml
ubio-autobox migrate --config /path/to/config.yml
ubio-autobox analysis-status <sample-id> --config /path/to/config.yml --json
```

`analysis-status` returns `0` for a succeeded current-pipeline analysis, `10`
for terminal `failed` or `invalid` state, and `20` while the sample or analysis
is absent, validated, queued, or running.

When Bactopia uses the Docker profile, control-plane containers need the host
Docker socket and host datasets/reference paths mounted at identical absolute
paths. Docker-socket access is effectively host-level control. Restrict the
deployment host and operators accordingly, or use a narrowly configured socket
proxy.

See [`docs/deployment-interface.md`](docs/deployment-interface.md) for the
complete public contract. Compose, Dagster instance/workspace configuration,
secrets, and target policy belong to the private deploy repository.

## Slurm

Start from `examples/config.slurm.yaml` and set `UBIO_CONFIG_FILE`.
Slurm mode uses `dagster-slurm` per-asset execution. The five logical assets
are represented by one graph-backed compute boundary, so a sample submits one
allocation. Bactopia/Nextflow run locally inside that allocation; nested Slurm
submission is not enabled. Shared storage and Apptainer are the v1 defaults;
Bactopia's profile is named `singularity`, which Nextflow uses with the
Apptainer runtime. `dagster-slurm` packages the locked Linux Pixi environment
for the allocation; Apptainer itself is expected to be installed by the
cluster.

The single allocation contains explicit sequential checkpoints for Bactopia
core, CheckM2, and Sylph. Each phase can have its own `max_cpus` and
`max_memory` settings. A failed attempt records the completed phase and its
output checksum; a retry validates that checkpoint and resumes with the next
phase instead of rerunning completed scientific work.

## Outputs

Successful attempts are published immutably beneath:

```text
artifacts/samples/<sample_id>/analyses/<analysis_id>/published/attempt-0001/
```

Each attempt also contains an `attempt-manifest.json` at its root. It records
input metadata and checksums, the Dagster/manual run correlation ID, attempt
number, redacted commands, phase, return codes, and checksummed files. The
database and Dagster Pipes logs expose the same phase updates:
`validating_input`, `preparing`, `bactopia_core`, `checkm2`, `sylph`,
`parsing_outputs`, `exporting_results`, `publishing_artifacts`, and terminal
`succeeded`/`failed`. Failed attempts remain linked through
`failed_workspace_uri` and `logs_uri`; retries retain prior attempt history.

Each per-sample export contains:

```text
exports/<export_id>/
├── manifest.json
├── run.parquet
├── assembly.parquet
├── assembly_stats.parquet
├── sylph.parquet
├── checkm2.parquet
├── sample_view.parquet
└── sample_view.tsv
```

Extended tables retain local records and add `ubio_sample_id`,
`ubio_analysis_id`, and `atb_schema_version`. Strict tables contain only ATB
columns and exclude records without genuine public accessions. The per-sample
`sample_view.tsv` is a human-readable extended view with accession columns
removed for locally generated samples. Its `file://` URI is attached as
`atb_sample_tsv_uri` to the completed Dagster materializations. The
`atb_sample_export` materialization also includes a typed Dagster table preview
(`atb_sample_preview`) and a compact Markdown summary (`atb_sample_summary`)
for overview display. UUIDs are never substituted for accessions.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/atb-field-mapping.md`](docs/atb-field-mapping.md), and
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
