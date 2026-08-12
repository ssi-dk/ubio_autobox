# Bactopia v4 Apple Silicon support audit

**Scope:** official `bactopia/bactopia` v4.0.0 tag, its first-party v4.0.0 documentation, release notes, package recipe, CI, and workflow profiles. **Audit date:** 2026-08-11.

## Finding

Bactopia v4 is **not expected to run natively on Apple Silicon (`osx-arm64`)**. The official v4.0.0 installation guide says macOS support is limited and explicitly says Apple Silicon/ARM is unsupported because many workflow tools lack ARM builds. Its prescribed workaround is Docker emulating `linux/amd64`, using `-profile arm` ([v4.0.0 installation guide](https://bactopia.io/v4.0.0/installation#Windows-and-OSX-Support)).

Therefore, the supported Apple Silicon model is:

```text
Apple Silicon macOS host
  -> host-side Bactopia + Nextflow + Docker
  -> Bactopia `arm` profile
  -> Linux/amd64 workflow containers under emulation
```

This is **Docker-based Linux/amd64 emulation**, not a native macOS/ARM execution mode. A Linux x86_64 host can run the same Linux/amd64 containers natively; a Linux ARM host would need an equivalent emulation strategy. The official docs describe Bactopia as primarily developed for Linux and do not promise native ARM execution.

## Evidence from the v4.0.0 repository

| Area | Primary-source evidence | Interpretation |
| --- | --- | --- |
| Apple Silicon policy | The v4.0.0 docs say “Apple silicon (ARM) is not supported” and recommend Docker emulation of `linux/amd64`. | Native `osx-arm64` is unsupported; Docker emulation is the official workaround. |
| ARM profile | [`conf/profiles.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/conf/profiles.config#L74-L100) defines `arm` with `docker.enabled = true`, adds `--platform=linux/amd64`, and disables Conda, Singularity, Apptainer, Podman, and other alternatives. | `-profile arm` is specifically a Docker/Linux-amd64 emulation profile. |
| Ordinary Docker profile | The same profile defines `docker` as a container executor without an architecture override. | On Apple Silicon, use `arm`, not plain `docker`, when the image/toolchain must be forced to amd64. |
| Workflow containers | [`conf/base.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/conf/base.config#L1-L18) selects per-process Docker images (or Singularity images); representative module metadata uses Linux-oriented Biocontainers/Singularity images, e.g. [`modules/bactopia/qc/module.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/bactopia/qc/module.config#L35-L50). | The many bioinformatics tools are workflow-task dependencies, separate from the host launcher. |
| CI coverage | [`all-bactopia-tests.yml`](https://github.com/bactopia/bactopia/blob/v4.0.0/.github/workflows/all-bactopia-tests.yml#L8-L64) uses one `self-hosted` runner and tests Singularity, Docker, and Conda; [`conda-build-manual.yml`](https://github.com/bactopia/bactopia/blob/v4.0.0/.github/workflows/conda-build-manual.yml#L3-L30) uses only `ubuntu-latest`. Neither declares macOS, `osx-arm64`, Apple Silicon, or an ARM matrix. | v4 CI provides no evidence of native Apple Silicon support. |
| Release | The [v4.0.0 release](https://github.com/bactopia/bactopia/releases/tag/v4.0.0) is tagged at commit `55dc640` and requires Nextflow `>=26.04.0`. | This audit is tied to the released v4.0.0 source, not an inferred future configuration. |

## Host dependencies versus workflow dependencies

### Host-side launcher dependencies

The v4 package recipe is [`data/conda/meta.yaml`](https://github.com/bactopia/bactopia/blob/v4.0.0/data/conda/meta.yaml#L1-L38). It declares Bactopia as `noarch: generic` and installs host-side runtime dependencies including:

- `bactopia-py`
- Conda and Mamba
- Nextflow `>=26`
- Python `>3.9,<3.14`
- `coreutils`, `sed`, `wget`, `nf-test`, `importlib-metadata`, and `openpyxl`

The top-level [`environment.yml`](https://github.com/bactopia/bactopia/blob/v4.0.0/environment.yml#L1-L26) likewise lists Conda, Mamba, Nextflow, Python, and shell utilities, but is a broader development environment (it also includes testing/build/documentation tools). [`nextflow.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/nextflow.config#L1-L10) sets the v4 minimum to `>=26.04.0`.

`noarch: generic` means the Bactopia wrapper package itself is not published as a CPU-specific Conda build. It does **not** establish that all of Bactopia’s hundreds of workflow tools have native `osx-arm64` builds; the first-party installation guide expressly says the opposite.

### Workflow-task dependencies

`csvtk` is **not a required host launcher dependency** in the Bactopia package recipe. It is a workflow module dependency. For example, [`modules/csvtk/concat/main.nf`](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/csvtk/concat/main.nf#L29-L35) declares both a per-task Conda environment and a container, while [`modules/csvtk/concat/module.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/csvtk/concat/module.config#L17-L22) pins `bioconda::csvtk=0.31.0` and records the Docker/Singularity images. The join module has the same arrangement ([`modules/csvtk/join/module.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/csvtk/join/module.config#L17-L22)).

Thus:

- with a Conda/standard profile, `csvtk` is resolved for the workflow task through Nextflow’s per-process Conda environment;
- with Docker, including the Apple Silicon `arm` profile, `csvtk` runs inside the selected Linux container image;
- installing `csvtk` natively on macOS does not make the complete Bactopia workflow Apple-Silicon-compatible.

## Practical conclusion

For an Apple Silicon Mac, treat Bactopia v4 as a **Linux/amd64 workflow launched from macOS**:

1. Install the host-side Bactopia/Nextflow prerequisites in a supported host environment.
2. Install and run Docker Desktop (or an equivalent Docker engine that can emulate amd64).
3. Run Bactopia with `-profile arm` so Nextflow passes `--platform=linux/amd64` to Docker.

Do not describe this as native `osx-arm64` support. Plain native Conda execution on Apple Silicon is outside the official support statement, and the v4.0.0 CI does not test it.

## Sources checked

- [Bactopia v4.0.0 installation guide](https://bactopia.io/v4.0.0/installation)
- [Bactopia v4.0.0 release](https://github.com/bactopia/bactopia/releases/tag/v4.0.0)
- [v4.0.0 repository tree](https://github.com/bactopia/bactopia/tree/v4.0.0)
- [v4.0.0 `conf/profiles.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/conf/profiles.config)
- [v4.0.0 `conf/base.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/conf/base.config)
- [v4.0.0 `environment.yml`](https://github.com/bactopia/bactopia/blob/v4.0.0/environment.yml)
- [v4.0.0 `data/conda/meta.yaml`](https://github.com/bactopia/bactopia/blob/v4.0.0/data/conda/meta.yaml)
- [v4.0.0 `nextflow.config`](https://github.com/bactopia/bactopia/blob/v4.0.0/nextflow.config)
- [v4.0.0 Docker/Singularity/Conda CI workflow](https://github.com/bactopia/bactopia/blob/v4.0.0/.github/workflows/all-bactopia-tests.yml)
- [v4.0.0 Conda build workflow](https://github.com/bactopia/bactopia/blob/v4.0.0/.github/workflows/conda-build-manual.yml)
- [v4.0.0 `csvtk` module](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/csvtk/concat/main.nf)
- [v4.0.0 `csvtk` module metadata](https://github.com/bactopia/bactopia/blob/v4.0.0/modules/csvtk/concat/module.config)
