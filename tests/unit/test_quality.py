from ubio_autobox.projection import QualityPolicy


def test_biological_failures_are_filters_not_structural_errors() -> None:
    assessment = QualityPolicy().assess(
        {
            "total_length": 50_000,
            "number": 2_001,
            "n50": 1_999,
        },
        {
            "completeness_general": 89.9,
            "contamination": 5.1,
        },
        (),
    )
    assert assessment.assembly_filter != "PASS"
    assert "NO_SYLPH_RESULTS" in assessment.hq_filter
    assert not assessment.passed
