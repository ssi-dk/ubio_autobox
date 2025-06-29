from dagster import Definitions, load_assets_from_modules
from dagster_duckdb import DuckDBResource
from dagster_duckdb_pandas import DuckDBPandasIOManager

from ubio_autobox.assets import illumina_workflow  # noqa: TID252

all_assets = load_assets_from_modules([illumina_workflow])

defs = Definitions(
    assets=all_assets,
    resources={
        "duckdb": DuckDBResource(
            database="./data/database/seqsample.duckdb",  # required
        ),
        "io_manager": DuckDBPandasIOManager(
            database="./data/database/iomanager.duckdb", schema="illumina_workflow"
        ),
    },
    # sensors=[illumina_workflow.unprocessed_illumina_samples_sensor],
    # jobs=[illumina_workflow.unprocessed_illumina_samples_job],
)
