from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ubio_autobox.domain.models import (
    AnalysisRequest,
    BactopiaRequest,
    RegisteredSample,
)
from ubio_autobox.execution import (
    BactopiaCommandBuilder,
    write_bactopia_samplesheet,
)
from ubio_autobox.execution.payload import _sample_tsv_metadata
from ubio_autobox.execution.processor import _redact_commands


def test_bactopia_commands_are_argument_arrays(tmp_path: Path) -> None:
    sample = RegisteredSample(
        batch_id=uuid4(),
        sample_id=uuid4(),
        batch_key="batch",
        sample_key="sample; touch NO",
        input_fingerprint="a" * 64,
        r1=tmp_path / "reads R1.fastq.gz",
        r2=tmp_path / "reads R2.fastq.gz",
    )
    analysis = AnalysisRequest(
        analysis_id=uuid4(),
        sample=sample,
        attempt=1,
        pipeline_config_fingerprint="b" * 64,
    )
    request = BactopiaRequest(
        analysis=analysis,
        samplesheet_path=tmp_path / "samples sheet.tsv",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        executable="bactopia",
        profile="docker",
        max_cpus=8,
        max_memory="32.GB",
    )
    commands = BactopiaCommandBuilder.build(request)
    assert len(commands) == 3
    assert commands[0][0] == "bactopia"
    assert str(request.samplesheet_path) in commands[0]
    assert all(isinstance(command, tuple) for command in commands)


def test_bactopia_4_samplesheet_contract(tmp_path: Path) -> None:
    sample = RegisteredSample(
        batch_id=uuid4(),
        sample_id=uuid4(),
        batch_key="batch",
        sample_key="sample",
        input_fingerprint="a" * 64,
        r1=tmp_path / "r1.fastq.gz",
        r2=tmp_path / "r2.fastq.gz",
        source_metadata={"species": "Staphylococcus aureus"},
    )
    samplesheet = tmp_path / "samples.tsv"
    write_bactopia_samplesheet(sample, samplesheet)
    lines = samplesheet.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == [
        "sample",
        "runtype",
        "genome_size",
        "species",
        "r1",
        "r2",
        "se",
        "ont",
        "assembly",
    ]
    assert len(lines[1].split("\t")) == 9
    assert lines[1].split("\t")[3] == "Staphylococcus aureus"


def test_controlled_bactopia_arguments_cannot_be_overridden(tmp_path: Path) -> None:
    sample = RegisteredSample(
        batch_id=uuid4(),
        sample_id=uuid4(),
        batch_key="batch",
        sample_key="sample",
        input_fingerprint="a" * 64,
        r1=tmp_path / "r1.fastq.gz",
        r2=tmp_path / "r2.fastq.gz",
    )
    request = BactopiaRequest(
        analysis=AnalysisRequest(
            analysis_id=uuid4(),
            sample=sample,
            attempt=1,
            pipeline_config_fingerprint="b" * 64,
        ),
        samplesheet_path=tmp_path / "samples.tsv",
        output_dir=tmp_path / "output",
        logs_dir=tmp_path / "logs",
        executable="bactopia",
        profile="docker",
        max_cpus=8,
        max_memory="32.GB",
        extra_args=("--outdir=/tmp/escape",),
    )
    with pytest.raises(ValueError, match="cannot be overridden"):
        BactopiaCommandBuilder.build(request)


def test_persisted_command_arguments_redact_secret_values() -> None:
    commands = (("tool", "--api-token", "secret-value", "--flag=value"),)
    assert _redact_commands(commands) == [
        ["tool", "--api-token", "<redacted>", "--flag=value"]
    ]


def test_sample_tsv_metadata_uses_dagster_table_and_markdown_types(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample_view.tsv"
    path.write_text(
        "ubio_sample_id\trun__pass\tassembly__scientific_name\n"
        "sample-1\t1\tEscherichia coli\n",
        encoding="utf-8",
    )

    table, markdown = _sample_tsv_metadata(path)

    assert table["type"] == "table"
    assert table["raw_value"]["records"] == [
        {
            "ubio_sample_id": "sample-1",
            "run__pass": "1",
            "assembly__scientific_name": "Escherichia coli",
        }
    ]
    assert markdown["type"] == "md"
    assert "| Scientific name | Escherichia coli |" in markdown["raw_value"]
