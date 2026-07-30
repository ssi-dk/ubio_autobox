# Contributing

Use Python 3.11 and Pixi:

```bash
pixi install
pixi run format-check
pixi run lint
pixi run type-check
pixi run test
```

Keep orchestration shallow and place scientific behavior behind the module
boundaries documented in `docs/architecture.md`. Commands must be argument
arrays; never introduce shell interpolation. Database changes require an
Alembic migration and must avoid dialect-specific domain SQL.

Changes to Bactopia, Dagster, `dagster-slurm`, or the ATB schema follow
`docs/adr/0004-version-policy.md`: update captured fixtures, contracts,
documentation, and `pixi.lock` together.

Tests must contain only synthetic or public non-sensitive fixtures. Never
commit laboratory samples, credentials, private container references, SSH
keys, or production configuration.
