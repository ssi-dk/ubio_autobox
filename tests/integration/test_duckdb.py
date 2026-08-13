from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.pool import NullPool

from ubio_autobox.persistence import SqlAlchemyResultRepository


@pytest.mark.integration
def test_duckdb_creates_normalized_schema(tmp_path: Path) -> None:
    repository = SqlAlchemyResultRepository(f"duckdb:///{tmp_path / 'results.duckdb'}")
    assert isinstance(repository.engine.pool, NullPool)
    repository.initialize()
    tables = set(inspect(repository.engine).get_table_names())
    assert {
        "ingest_batches",
        "samples",
        "analysis_runs",
        "analysis_phase_events",
        "assembly_results",
        "assembly_stats_results",
        "sylph_results",
        "checkm2_results",
    } <= tables
