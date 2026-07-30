"""ATB-aligned biological quality policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    assembly_filter: str
    sylph_filter: str
    hq_filter: str
    scientific_name: str | None
    sylph_species_pre_202505: str | None
    in_hq_pre_202505: str

    @property
    def passed(self) -> bool:
        return self.hq_filter == "PASS"


class QualityPolicy:
    """Separate parse-invalid output from valid output with quality warnings."""

    def assess(
        self,
        assembly_stats: dict[str, Any],
        checkm2: dict[str, Any],
        sylph: tuple[dict[str, Any], ...],
    ) -> QualityAssessment:
        assembly_failures: list[str] = []
        total = int(assembly_stats["total_length"])
        contigs = int(assembly_stats["number"])
        n50 = int(assembly_stats["n50"])
        if total < 100_000:
            assembly_failures.append("LENGTH_LT_100KB")
        if total > 15_000_000:
            assembly_failures.append("LENGTH_GT_15MB")
        if contigs > 2_000:
            assembly_failures.append("CONTIGS_GT_2000")
        if n50 < 2_000:
            assembly_failures.append("N50_LT_2000")

        candidates = [
            row
            for row in sylph
            if row.get("species")
            and (_number(row.get("sequence_abundance"), default=0.0) or 0.0) >= 99.0
        ]
        species = sorted({str(row["species"]) for row in candidates})
        if not sylph:
            sylph_filter = "NO_SYLPH_RESULTS"
            pre_species = None
        elif not species:
            sylph_filter = "SYLPH_RESULTS_FAIL"
            pre_species = None
        elif len(species) > 1:
            sylph_filter = "MULTIPLE"
            pre_species = None
        else:
            # The ATB 2025-05 call also needs reference genome size and read
            # coverage metadata not present in the merged Sylph output.
            sylph_filter = "SYLPH_COVERAGE_NOT_EVALUATED"
            pre_species = species[0]

        hq_failures = list(assembly_failures)
        completeness = _number(checkm2.get("completeness_general"))
        contamination = _number(checkm2.get("contamination"))
        if completeness is None or completeness < 90:
            hq_failures.append("CHECKM2_COMPLETENESS_LT_90")
        if contamination is None or contamination > 5:
            hq_failures.append("CHECKM2_CONTAMINATION_GT_5")
        if sylph_filter != "PASS":
            hq_failures.append(sylph_filter)
        pre_hq_passed = not assembly_failures and (
            completeness is not None
            and completeness >= 90
            and contamination is not None
            and contamination <= 5
            and pre_species is not None
        )

        return QualityAssessment(
            assembly_filter=";".join(assembly_failures) or "PASS",
            sylph_filter=sylph_filter,
            hq_filter=";".join(hq_failures) or "PASS",
            scientific_name=None,
            sylph_species_pre_202505=pre_species,
            in_hq_pre_202505="1" if pre_hq_passed else "0",
        )


def _number(value: object, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(str(value))
