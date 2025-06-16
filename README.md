# ubio_autobox

An automated bioinformatics pipeline for processing Illumina sequencing data using Bactopia. This project automatically detects new samples in an input directory, tracks their processing status, and runs Bactopia analysis on unprocessed samples using Dagster orchestration.

## Overview

The pipeline works by:
1. **Sample Discovery**: Scanning the input directory for new FASTQ files
2. **Sample Tracking**: Storing sample metadata in a DuckDB database
3. **Dynamic Processing**: Creating dynamic partitions for each unprocessed sample
4. **Automated Analysis**: Running Bactopia on each sample via a sensor-triggered job
5. **Progress Monitoring**: Providing visual reports of processing status

## Tech Stack

- **[Bactopia](https://bactopia.github.io/)**: Bacterial genome analysis pipeline
- **[Dagster](https://dagster.io/)**: Data orchestration platform
- **[DuckDB](https://duckdb.org/)**: Embedded analytical database
- **[Pixi](https://pixi.sh/)**: Package and environment management

## Project Structure

```
ubio_autobox/
├── data/
│   ├── database/           # DuckDB databases
│   └── illumina_workflow/
│       ├── input/          # Place FASTQ files here
│       └── output/         # Bactopia results
├── ubio_autobox/
│   ├── assets/
│   │   └── illumina_workflow.py  # Main pipeline assets
│   └── definitions.py      # Dagster definitions
├── pixi.toml              # Environment and dependencies
└── pyproject.toml         # Python project configuration
```

## Getting Started

### Prerequisites

- [Pixi](https://pixi.sh/) for environment management
- Docker (for Bactopia execution)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/ssi-dk/ubio_autobox/
   cd ubio_autobox
   ```

2. **Set up the environment with Pixi**:
   ```bash
   pixi install
   ```

3. **Activate the Pixi environment**:
   ```bash
   pixi shell
   ```

4. **Install the package in development mode**:
   ```bash
   pip install -e ".[dev]"
   ```

### Running the Pipeline

1. **Start the Dagster UI**:
   ```bash
   dagster dev
   ```

2. **Access the web interface**:
   Open http://localhost:3000 in your browser

3. **Add FASTQ files**:
   Place your Illumina FASTQ files (R1/R2 pairs) in `data/illumina_workflow/input/`

4. **Monitor processing**:
   The sensor will automatically detect new samples and create processing jobs

## Pipeline Assets

### Core Assets

- **`illumina_samples_in_folder`**: Discovers FASTQ files using `bactopia-prepare`
- **`new_illumina_samples`**: Identifies new samples by comparing with database
- **`unprocessed_illumina_samples`**: Retrieves samples that haven't been processed
- **`run_unprocessed_illumina_sample`**: Processes individual samples (partitioned)
- **`illumina_samples_plot`**: Generates processing status reports

### Dynamic Partitioning

The pipeline uses dynamic partitions to process each sample independently:
- Each unprocessed sample gets its own partition
- Samples can be processed in parallel
- Failed samples don't block others

### Sensor

The `unprocessed_illumina_samples_sensor` automatically:
- Detects new unprocessed samples
- Creates dynamic partitions
- Triggers processing jobs

## Configuration

### Input Directory

By default, the pipeline looks for FASTQ files in `./data/illumina_workflow/input`. You can configure this in the asset configuration.

### Bactopia Settings

The pipeline runs Bactopia with Docker profile. The command can be customized in the `run_bactopia` function in `illumina_workflow.py`.

### Database

Sample metadata is stored in DuckDB at `./data/database/seqsample.duckdb`. The database tracks:
- Sample names and file paths
- Species and genome size information
- Processing status
- Metadata

## Development

### Adding Dependencies

Add new dependencies to `pixi.toml`:

```toml
[dependencies]
new-package = ">=1.0.0"
```

Then run:
```bash
pixi install
```

### Running Tests

```bash
pytest ubio_autobox_tests
```

### Code Quality

The project uses standard Python linting. Run checks with:
```bash
pixi run lint  # if configured
```

## Usage Examples

### Processing New Samples

1. Copy FASTQ files to the input directory:
   ```bash
   cp /path/to/sample_R1.fastq.gz /path/to/sample_R2.fastq.gz data/illumina_workflow/input/
   ```

2. The sensor will automatically detect and process them within the sensor interval

3. Monitor progress in the Dagster UI at http://localhost:3000

### Manual Processing

You can also manually trigger processing:

1. In the Dagster UI, go to the "Assets" tab
2. Materialize `illumina_samples_in_folder` to discover new samples
3. Materialize `new_illumina_samples` to update the database
4. Use the "Jobs" tab to run individual sample processing jobs

## Troubleshooting

### Common Issues

- **Bactopia not found**: Ensure Bactopia is installed and accessible in the Pixi environment
- **Docker issues**: Make sure Docker is running for Bactopia execution
- **Permission errors**: Check that the pipeline has write access to output directories
- **Database errors**: Ensure DuckDB database directory exists and is writable

### Logs

Check Dagster logs in the UI or run with verbose logging:
```bash
dagster dev --log-level DEBUG
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license information here]
