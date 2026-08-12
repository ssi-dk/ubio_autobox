# Operations

## Backup

Back up the scientific database and artifact root together at a quiescent
point. For DuckDB, stop analysis launches, wait for running analyses, then copy
the `.duckdb` file and immutable artifact tree with checksums. Back up Dagster
PostgreSQL separately; it is operational state and is not the scientific
record.

For SQL Server, use the platform's supported online backup procedure. Preserve
the same artifact tree snapshot and configuration fingerprint information.

## Restore

1. Restore the database to a new path/server.
2. Restore artifacts at paths compatible with recorded file URIs, or perform a
   reviewed URI migration.
3. Set `UBIO_DATABASE_URL` and storage roots.
4. Run `ubio-autobox migrate --config <config.yml>`.
5. Run `ubio-autobox status` and verify a sample of artifact SHA-256 values.
6. Start Dagster only after scientific state is consistent.

## Recovery

Failed attempt workspaces and logs are retained under `failed/` and linked from
the status response. A retry increments the analysis attempt number, receives a
fresh staging directory, and retains the previous run ID and failure in
`attempt_history`. Dagster re-execution gives the new attempt a new Dagster run
ID; direct CLI processing creates a `manual-...` correlation ID.
Never edit a published attempt. Submit changed input as a new batch/sample.

## Secrets and sample data

Keep database credentials, Slurm passwords/keys, and container registry tokens
in environment-backed secret stores. Do not commit them to YAML. No real
sample data belongs in this repository; tests use tiny synthetic reads and
fake outputs.
