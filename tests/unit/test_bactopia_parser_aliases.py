from pathlib import Path

from ubio_autobox.projection.parser import BactopiaResultParser


def test_checkm2_accepts_current_completeness_header(tmp_path: Path) -> None:
    report = tmp_path / "checkm2.tsv"
    report.write_text(
        "Name\tCompleteness\tContamination\nsample-a\t99.5\t0.2\n",
        encoding="utf-8",
    )

    parsed = BactopiaResultParser._parse_checkm2(report, "sample-a")

    assert parsed["completeness_general"] == 99.5
    assert parsed["contamination"] == 0.2


def test_sylph_accepts_current_headers_and_sample_file(tmp_path: Path) -> None:
    report = tmp_path / "sylph.tsv"
    report.write_text(
        "Sample_file\tGenome_file\tSequence_abundance\t"
        "ANI_5-95_percentile\tLambda_5-95_percentile\n"
        "/reads/sample-a_R1.fastq.gz\tGCF_000005845.2\t99.8\t"
        "98.9-99.3\t8.0-9.0\n"
        "/reads/another_R1.fastq.gz\tGCF_000005845.2\t99.9\t"
        "99.0-99.4\t8.1-9.1\n",
        encoding="utf-8",
    )

    parsed = BactopiaResultParser._parse_sylph(report, "sample-a")

    assert len(parsed) == 1
    assert parsed[0]["ani_5_95_percentile"] == "98.9-99.3"
    assert parsed[0]["lambda_5_95_percentile"] == "8.0-9.0"
