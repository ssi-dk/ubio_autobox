# Deployment Interface

`ubio_autobox` owns its application image, configuration model, database
migrations, immutable input contract, analysis status query, and scientific
artifact contract. Target topology, Compose, secrets, services, reference
locations, rollback, and host policy belong to a separate deploy repository.

## Workspace expectations

A conventional linked workspace is:

```text
<workspace>/
├── app/
├── deploy/
├── automation/
├── private/
└── runtimes/
```

`private/` and `runtimes/` must not be committed. Application source can be a
symlink or checkout, provided image builds receive the repository root as their
Docker build context.

## Image

Build the app-owned image using:

```bash
docker build \
  --file packaging/docker/Dockerfile \
  --tag ubio-autobox:<exact-git-sha> \
  .
```

The image includes the application package and packaged Alembic environment.
The deploy repository supplies runtime Compose and Dagster configuration.

## Operational CLI

Validate public application configuration:

```bash
ubio-autobox validate-config --config <config.yml>
```

Upgrade the scientific database idempotently:

```bash
ubio-autobox migrate --config <config.yml>
```

`init-db` is a compatibility alias for `migrate`; it does not bypass Alembic.

Query one sample under the current pipeline fingerprint:

```bash
ubio-autobox analysis-status <sample-uuid> \
  --config <config.yml> \
  --json
```

The JSON object has stable `sample_id`, `sample_key`, `sample_status`,
`pipeline_config_fingerprint`, `analysis_id`, `status`, `attempt`,
`dagster_run_id`, `execution_phase`, `phase_updated_at`,
`attempt_workspace_uri`, `failed_workspace_uri`, `logs_uri`,
`attempt_history`, `phase_history`, `error_summary`, `started_at`, and
`completed_at` keys. `phase_history` contains ordered phase records with
`attempt`, `phase`, `started_at`, `completed_at`, and `duration_seconds`.
The active phase has a null `completed_at` and a duration measured through the
status query time.
Exit codes are:

- `0`: analysis succeeded;
- `10`: terminal failed or invalid state;
- `20`: absent, validated, queued, or running and safe to retry polling.

## Mounts and security

The immutable incoming batch, artifact root, state, caches, logs, and external
scientific reference paths must persist outside replaceable containers.
Bactopia's Docker profile launches sibling task containers through the host
daemon, so every referenced host path must appear at the same absolute path in
the control-plane containers.

Mounting `/var/run/docker.sock` gives a container effective control over the
Docker host. Use a dedicated deployment host or a socket proxy with a reviewed
allowlist. Never place database passwords, reads, scientific databases, or
private target topology in this repository or image build context.

Public-safe starting configurations are in `examples/`.
