# AllTheBacteria 2025-05 field mapping

The authoritative contract is versioned in
`src/ubio_autobox/projection/schemas/atb-2025-05.json`. Column names and order
match the latest complete AllTheBacteria 2025-05 metadata model documented at
[allthebacteria.org](https://allthebacteria.org/docs/metadata_sqlite/).

`null` means the archive-specific fact is unavailable locally. It is never
estimated. All listed fields have schema contract coverage; source/parser and
export tests use the committed fake Bactopia fixture.

## `run`

| Field | Type | Local source/transformation | Nullability |
|---|---|---|---|
| `run_accession` | string | `source_record_id` only when namespace is `ena_run`/`insdc_run` and syntax is genuine | nullable |
| `sample_accession` | string | validated `insdc_sample_accession` | nullable |
| `in_661k` | int | archive membership not inferred | nullable |
| `in_ena_20240625` | int | archive membership not inferred | nullable |
| `in_ena_20240801` | int | archive membership not inferred | nullable |
| `in_ena_20250506` | int | archive membership not inferred | nullable |
| `ena_202505_batch` | string | archive batch unavailable | nullable |
| `fastq_md5` | string | not inferred from SHA-256 input provenance | nullable |
| `meta_pass_atb` | int | ATB ENA metadata rule not evaluated locally | nullable |
| `meta_pass_661k` | int | 661k metadata rule not evaluated locally | nullable |
| `pass` | int | ATB aggregate metadata pass is not conflated with local validation | nullable |
| `comments` | string | explicitly identifies locally generated rows | nullable |

## `assembly`

| Field | Type | Local source/transformation | Nullability |
|---|---|---|---|
| `sample_accession` | string | validated INSDC sample accession | nullable |
| `run_accession` | string | validated namespaced INSDC run accession | nullable |
| `assembly_accession` | string | never synthesized | nullable |
| `assembly_seqkit_sum` | string | no archive `seqkit sum` text generated in v1 | nullable |
| `asm_pipe_filter` | string | assembly length/count/N50 quality policy | non-null |
| `asm_fasta_on_osf` | int | local artifact is not on OSF; `0` | non-null |
| `dataset` | string | literal `ubio_autobox` | non-null |
| `scientific_name` | string | ENA scientific name unavailable locally | nullable |
| `sylph_species_pre_202505` | string | one species with `Sequence_abundance >= 99`, matching the documented historical rule | nullable |
| `in_hq_pre_202505` | string | local evaluation of the historical species and assembly/CheckM2 thresholds | non-null |
| `sylph_species` | string | null until the 2025-05 coverage/genome-size condition can be evaluated | nullable |
| `sylph_filter` | string | explicit reason; `SYLPH_COVERAGE_NOT_EVALUATED` prevents a false 2025-05 `PASS` | non-null |
| `hq_filter` | string | combined Sylph, CheckM2, and assembly policy | non-null |
| `osf_tarball_filename` | string | archive location unavailable | nullable |
| `osf_tarball_url` | string | archive location unavailable | nullable |
| `aws_url` | string | archive location unavailable | nullable |
| `comments` | string | parser/policy note when needed | nullable |

The normalized database additionally retains `assembly_uri` and
`assembly_sha256`; these are deliberately excluded from strict ATB output.

## `assembly_stats`

| Field | Type | Local source/transformation | Nullability |
|---|---|---|---|
| `sample_accession` | string | validated INSDC sample accession | nullable |
| `total_length` | int | sum of parsed assembly contig lengths | non-null |
| `number` | int | number of assembly contigs | non-null |
| `mean_length` | float | total length divided by contig count | non-null |
| `longest` | int | maximum contig length | non-null |
| `shortest` | int | minimum contig length | non-null |
| `N_count` | int | count of `N` bases, case-insensitive | non-null |
| `Gaps` | int | count of contiguous `N` runs | non-null |
| `N50` | int | contig length crossing 50% cumulative length | non-null |
| `N50n` | int | contig ordinal crossing 50% | non-null |
| `N70` | int | contig length crossing 70% cumulative length | non-null |
| `N70n` | int | contig ordinal crossing 70% | non-null |
| `N90` | int | contig length crossing 90% cumulative length | non-null |
| `N90n` | int | contig ordinal crossing 90% | non-null |

## `sylph`

All hits are preserved. The wide view chooses the row with the highest
`Taxonomic_abundance` and adds `sylph_hit_count`.

| Field | Type | Local source/transformation | Nullability |
|---|---|---|---|
| `sample_accession` | string | validated INSDC sample accession | nullable |
| `run_accession` | string | validated namespaced run accession | nullable |
| `Genome_file` | string | Bactopia merged Sylph output | nullable |
| `Taxonomic_abundance` | float | Bactopia merged Sylph output | nullable |
| `Sequence_abundance` | float | Bactopia merged Sylph output | nullable |
| `Adjusted_ANI` | float | Bactopia merged Sylph output | nullable |
| `Eff_cov` | float | Bactopia merged Sylph output | nullable |
| `ANI_5_95_percentile` | string | Bactopia merged Sylph output | nullable |
| `Eff_lambda` | float | Bactopia merged Sylph output | nullable |
| `Lambda_5_95_percentile` | string | Bactopia merged Sylph output | nullable |
| `Median_cov` | float | Bactopia merged Sylph output | nullable |
| `Mean_cov_geq1` | float | Bactopia merged Sylph output | nullable |
| `Containment_ind` | string | Bactopia merged Sylph output | nullable |
| `Naive_ANI` | float | Bactopia merged Sylph output | nullable |
| `Contig_name` | string | Bactopia merged Sylph output | nullable |
| `Species` | string | Upstream taxonomy enrichment when supplied; raw Sylph does not provide a species-name column | nullable |

## `checkm2`

| Field | Type | Local source/transformation | Nullability |
|---|---|---|---|
| `sample_accession` | string | validated INSDC sample accession | nullable |
| `Completeness_General` | float | Bactopia merged CheckM2 output | nullable |
| `Contamination` | float | Bactopia merged CheckM2 output | nullable |
| `Completeness_Specific` | float | Bactopia merged CheckM2 output | nullable |
| `Completeness_Model_Used` | string | Bactopia merged CheckM2 output | nullable |
| `Translation_Table_Used` | int | Bactopia merged CheckM2 output | nullable |
| `Coding_Density` | float | Bactopia merged CheckM2 output | nullable |
| `Contig_N50` | int | Bactopia merged CheckM2 output | nullable |
| `Average_Gene_Length` | float | Bactopia merged CheckM2 output | nullable |
| `Genome_Size` | int | Bactopia merged CheckM2 output | nullable |
| `GC_Content` | float | Bactopia merged CheckM2 output | nullable |
| `Total_Coding_Sequences` | int | Bactopia merged CheckM2 output | nullable |
| `Additional_Notes` | string | Bactopia merged CheckM2 output | nullable |

## Strict and extended rules

Extended output is the default and appends:

- `ubio_sample_id`
- `ubio_analysis_id`
- `atb_schema_version`

Strict output includes only original ATB fields. Rows without syntactically
genuine sample accessions are removed; `run`, `assembly`, and `sylph` also
require a genuine run accession. UUIDs, sample labels, and filenames are never
inserted into accession fields.
