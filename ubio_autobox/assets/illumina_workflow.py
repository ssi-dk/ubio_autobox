"""
Illumina Workflow Asset
This asset is designed to find Illumina samples in a specified input folder.
"""

import os
import subprocess
import pandas as pd
from dagster import (
    Config,
    asset,
    AssetExecutionContext
)
from pydantic import field_validator
from dagster_duckdb import DuckDBResource

class illumina_workflow_config(Config):
    input_folder: str = (
        # fastq R1, R2 files, can be in subfolders
        "./data/illumina_workflow/input"
    )
    output_file: str = "./data/illumina_workflow/output/illumina_workflow_output.txt"
    bactopia_prepare_cmd: str = "bactopia-prepare --path {input_folder} > {output_file}"

    @field_validator("input_folder", mode="before")
    @classmethod
    def validate_input_folder(cls, v: str) -> str:
        """
        Validate the input folder path.
        Checks if the folder exists and is a directory."""
        if not os.path.exists(v):
            raise FileNotFoundError(
                f"Input folder '{v}' does not exist. Please provide a valid path."
            )
        if not os.path.isdir(v):
            raise NotADirectoryError(
                f"Input folder '{v}' is not a directory. Please provide a valid path."
            )
        return v

    @field_validator("bactopia_prepare_cmd", mode="before")
    @classmethod
    def validate_bactopia_prepare_cmd(cls, v: str) -> str:
        """
        Validate the bactopia prepare command.
        Checks if the command exists in the system PATH."""
        if not os.path.exists(v):
            raise FileNotFoundError(
                f"Command '{v}' does not exist. Please provide a valid command."
            )
        return v

    @field_validator("output_file", mode="before")
    @classmethod
    def validate_output_file(cls, v: str) -> str:
        """
        Validate the output file path.
        Checks if the output directory exists and if the file has a valid extension."""
        output_dir = os.path.dirname(v)
        if not os.path.exists(output_dir):
            raise FileNotFoundError(
                f"Output directory '{output_dir}' does not exist. Please provide a valid path."
            )
        if not v.endswith(('.tsv', '.csv', '.txt')):
            raise ValueError(
                f"Output file '{v}' must have a valid extension (.tsv, .csv, .txt)."
            )
        return v


@asset(
    group_name="illumina_workflow",
    kinds={"source", "ingest"},
)
def illumina_samples_in_folder(
    context: AssetExecutionContext,
    config: illumina_workflow_config
) -> pd.DataFrame:
    """
    Find Illumina samples in the input folder using bactopia prepare.
    """
    input_folder = config.input_folder
    output_file = config.output_file
    bactopia_prepare_cmd = config.bactopia_prepare_cmd.format(
        input_folder=input_folder, output_file=output_file
    )

    context.log.info(f"Running command: {bactopia_prepare_cmd}")

    try:
        subprocess.run(bactopia_prepare_cmd, shell=True, check=True)
        context.log.info(f"Illumina samples found and saved to {output_file}")
    except subprocess.CalledProcessError as e:
        context.log.error(f"Error running command: {e}")
        raise e

    return pd.read_csv(output_file, sep="\t")


@asset(
    deps=[illumina_samples_in_folder],
    group_name="illumina_workflow",
    kinds={"DuckDB"},
)
def new_illumina_samples(
    context: AssetExecutionContext,
    duckdb: DuckDBResource,
    illumina_samples_in_folder: pd.DataFrame,
) -> pd.DataFrame:
    """
    Determine new Illumina samples by comparing the current output with the previous one.
    """
    current_samples = illumina_samples_in_folder
    # check we have current_samples
    if not current_samples.empty:
        with duckdb.get_connection() as conn:
            # This DB either needs to be created or already exists
            conn.execute(
                "CREATE TABLE IF NOT EXISTS seqsample.illumina_samples ("
                "sample TEXT PRIMARY KEY, "
                "runtype TEXT, "
                "genome_size INTEGER, "
                "species TEXT, "
                "r1 TEXT, "
                "r2 TEXT, "
                "processed BOOLEAN DEFAULT FALSE, "
                "extra TEXT)"
            )
            existing_samples = conn.execute(
                "SELECT sample FROM seqsample.illumina_samples"
            ).fetchall()
            # Check that existing_samples is not empty
            if not existing_samples:
                new_samples = current_samples
            else:
                existing_samples = {row[0] for row in existing_samples}
                new_samples = current_samples[~current_samples['sample'].isin(existing_samples)]
                # change from Series to DataFrame
                new_samples = new_samples.reset_index(drop=True)

            # Insert new samples into the DuckDB table
            if not new_samples.empty:
                new_samples.to_sql(
                    "illumina_samples",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi"
                )
                context.log.info(f"Inserted {len(new_samples)} new samples into DuckDB.")
            else:
                context.log.info("No new samples to insert into DuckDB.")
    # return new_samples
    return new_samples


@asset(
    deps=[new_illumina_samples],
    group_name="illumina_workflow",
    kinds={"DuckDB"},
)
def unprocessed_illumina_samples(
    context: AssetExecutionContext,
    duckdb: DuckDBResource,
) -> pd.DataFrame:
    """
    Get unprocessed Illumina samples from the DuckDB table.
    """
    with duckdb.get_connection() as conn:
        unprocessed_samples = conn.execute(
            "SELECT * FROM seqsample.illumina_samples WHERE processed = FALSE"
        ).fetchdf()

        if not unprocessed_samples.empty:
            context.log.info(f"Found {len(unprocessed_samples)} unprocessed samples.")
            for index, row in unprocessed_samples.iterrows():
                context.log.info(f"Unprocessed sample: {row['sample']}")
        else:
            context.log.info("No unprocessed samples found.")

    return unprocessed_samples


def run_bactopia(r1, r2, sample, species, genome_size, runtype, extra):
    """
    Run Bactopia on the given Illumina sample.
    """
    cmd = f"bactopia run -profile docker --r1 {r1} --r2 {r2} --sample {sample} --species {species} --genome_size {genome_size} --runtype {runtype} --outdir ./data/illumina_workflow/output"
    try:
        subprocess.run(cmd, shell=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running Bactopia: {e}")
        return False


@asset(
    deps=[unprocessed_illumina_samples],
    group_name="illumina_workflow",
    kinds={"bactopia"},
)
def run_unprocessed_illumina_samples(
    context: AssetExecutionContext,
    duckdb: DuckDBResource,
    unprocessed_illumina_samples: pd.DataFrame
) -> None:
    """
    Run Bactopia on unprocessed Illumina samples.
    """
    with duckdb.get_connection() as conn:
        for index, row in unprocessed_illumina_samples.iterrows():
            success = run_bactopia(
                r1=row['r1'],
                r2=row['r2'],
                sample=row['sample'],
                species=row['species'],
                genome_size=row['genome_size'],
                runtype=row['runtype'],
                extra=row['extra']
            )
            if success:
                conn.execute(
                    "UPDATE seqsample.illumina_samples SET processed = TRUE WHERE sample = ?",
                    (row['sample'],)
                )
                context.log.info(f"Processed sample {row['sample']}.")
            else:
                context.log.error(f"Failed to process sample {row['sample']}.")
                return False
