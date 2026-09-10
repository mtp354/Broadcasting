# Broadcasting

Qiskit simulations and IBM Quantum measurements of an M-sender, N-receiver
broadcasting protocol, with optional `[[5,1,3]]` quantum error correction.
Use the two notebooks to configure experiments and produce the manuscript figures;
the `broadcasting/` package contains the reusable implementation, command-line
tools, setup script, and saved hardware analysis.

## Setup

From the project root, using Python 3.12 and Bash:

```bash
bash broadcasting/setup.sh
source .venv/bin/activate
```

Setup installs `requirements.txt`, checks dependencies, and runs the offline tests
excluding those marked `slow`. Select `.venv/bin/python` as the notebook kernel.
The dependency list is unpinned. `BROADCAST_PYTHON` and `BROADCAST_VENV` can override
the interpreter and environment paths.

```bash
bash broadcasting/setup.sh --check  # Check an existing environment
python -m pytest -q                # Run the complete test suite
```

For hardware runs, save credentials in Qiskit Runtime's account store and set the
account name and backend in `run_broadcast.ipynb`. Figure generation and saved-data
analysis work offline. Building the manuscript PDF additionally requires
`pdflatex` and `bibtex` on your path.

## Code structure

```text
Broadcasting/
├── run_broadcast.ipynb          Experiment settings, execution, and recovery
├── visualizations.ipynb        Plotting code, figure export, and LaTeX build
├── broadcasting/
│   ├── __init__.py             Public Python API
│   ├── protocol.py             Protocol configuration and result types
│   ├── backend.py              Exact, sampling, hardware, and HPC backends
│   ├── simulation.py           Numerical evolution and QEC recovery
│   ├── circuit.py              Broadcasting circuits and feedforward
│   ├── state_preparation.py    Bare and encoded initial states
│   ├── qec_513.py              Five-qubit code and memory benchmark circuits
│   ├── fidelity.py             Receiver fidelity measurements
│   ├── helpers.py              Sender encoding and bit conventions
│   ├── experiments.py          Hardware job lifecycle and its CLI
│   ├── convergence.py          Sampled-to-exact convergence studies
│   ├── results.py              Result validation, loading, and storage
│   ├── provenance.py           Software, circuit, and calibration evidence
│   ├── validation.py           Duplicate detection and cohort selection
│   ├── analysis.py             Fidelity statistics and delay spectra
│   ├── analyze_saved_hardware.py  Saved-data analysis CLI
│   ├── merge_hpc_runs.py       Complete simulation sweep merge CLI
│   ├── setup.sh                Environment setup and checks
│   └── hardware_analysis/     Derived JSON statistics and report.md
├── hpc/
│   ├── run_experiment.py       Cluster/local simulation CLI
│   ├── archive.py              Frozen job sources and verified result transfer
│   ├── slurm_broadcast.sh      SLURM submission settings
│   ├── setup_scratch.sh        Cluster environment setup
│   ├── fetch_results.sh        Fetch measured results to this checkout
│   └── backup_results.sh       Cluster result backup
├── results/                    Self-contained measurement and job JSON files
├── manuscript/                 LaTeX, bibliography, six PNGs, and source manifest
├── tests/                      Protocol, workflow, and figure checks
├── requirements.txt            Python dependencies
└── pytest.ini                  Test configuration
```

The execution notebook calls `broadcasting/` and saves measurements in `results/`.
The visualization notebook reads those measurements and exports to `manuscript/`.
The analysis CLI reads the same records and writes to
`broadcasting/hardware_analysis/`.

## Run and resume experiments

[run_broadcast.ipynb](run_broadcast.ipynb) contains settings for exact simulation,
Pauli-trajectory sampling, convergence repetitions, hardware size/delay sweeps,
and encoded/bare single-qubit memory benchmarks. Every execution switch defaults
to `False`; running all cells previews settings and saved status. Enable
preparation, submission, and collection separately to acquire hardware data.

Each hardware job has one JSON file containing its configuration, compiled
circuits, submission attempt, receipt, and measured cases. Resume with that file.
After an interrupted submission without a receipt, attach the accepted job ID
before continuing. Completed measurements are immutable.

The same job workflow is available from the package CLI:

```bash
python -m broadcasting.experiments --help
python -m broadcasting.experiments status results/job_*.json
```

Its `submit`, `collect`, and `attach-job` commands operate on existing job files;
use the notebook to prepare experiments and edit their physical settings.

## Make the figures

[visualizations.ipynb](visualizations.ipynb) reads saved results and exports all six
figures directly to `manuscript/`. Each figure cell contains its source selection,
plotting code, dimensions, colours, axes, legend, and layout.

| Figure | Content |
|---|---|
| 1 | Monte Carlo convergence by seed and receiver, with total errors |
| 2 | Encoded and bare single-qubit memory measurements |
| 3 | Broadcasting circuit in one continuous row |
| 4 | Exact and sampled QEC crossover, with an enlarged inset |
| 5 | Three Marrakesh and three Kingston delay sweeps |
| 6 | Hardware fidelity versus sender and receiver count |

Shared controls are `FONT_SIZE` (ticks and general text),
`AXIS_LABEL_FONT_SIZE` (axis labels), `LEGEND_FONT_SIZE`, and `INSET_FONT_SIZE`.
Figure-specific settings can override these defaults. Figure 4's legend sits
inside the lower-left corner of its axes.

Run the notebook top to bottom to export the PNGs and rebuild
`manuscript/apstemplate.pdf`. Set `SAVE_MANUSCRIPT_FIGURES=False` for a preview
without exports, or `BUILD_MANUSCRIPT=False` to save figures without compiling
LaTeX. The build uses a temporary directory. Export settings and input hashes are
recorded in `manuscript/figure_sources.json`.

## Saved results and numeric analysis

Every file in `results/` is a self-contained JSON record or job document.
Simulations retain protocol settings, sweeps, seeds, measurements, and source
evidence. Hardware jobs retain their preparation and recovery state. Memory tests
use M=0, N=1 and the same sweep/receiver/count dimensions as broadcasting.

`broadcasting.results.list_runs` exposes individual measured cases. Use
`record_id` to select a case when several cases share a JSON path or Runtime job
ID. Receiver 0 is the least-significant readout bit. Recorded backend `dt` converts
delay values to physical time; absent calibration remains unknown.

```bash
python -m broadcasting.analyze_saved_hardware
```

This refreshes `summary.json`, `points.json`, `scaling_points.json`, and
[report.md](broadcasting/hardware_analysis/report.md) in
`broadcasting/hardware_analysis/`. Use `--results-dir`, `--include-results-dir`,
and `--output-dir` to select other saved inputs or an output location.
The report covers local, mean, worst-receiver, and joint fidelity, covariance,
receiver asymmetry, recorded invalid sender outcomes, and exploratory delay
spectra. Shot intervals describe uncertainty conditional on each histogram;
they do not estimate variation between jobs or identify a physical noise mechanism.

Convergence results embed their exact reference and error settings. Seed 0
contains rounded error summaries and records that its raw fidelity grids are
unavailable; convergence summaries are excluded from the default measured-record
view. The inverse-square-root curve is an anchored reference. Source hashes and
embedded execution evidence support reproducibility of the measurements and
derived figures. The ignored `.local-archive/` retains original result archives
referenced by saved provenance.

## Optional HPC workflow

`hpc/` handles simulation execution, SLURM jobs, and result transfer. Set
`BROADCAST_GLOBAL_DIR` and `BROADCAST_SCRATCH_DIR` for the cluster, then run
`bash hpc/setup_scratch.sh` on its login node. Configure the simulation through
the environment settings in `hpc/slurm_broadcast.sh` and submit with `sbatch`.

```bash
python -m hpc.run_experiment --help
python -m broadcasting.merge_hpc_runs --help
```

A cluster job JSON contains its frozen source, requirements, arguments, and
completed task measurements. `hpc/fetch_results.sh` imports verified new results
and task progress. Merge a completed probability sweep with:

```bash
python -m broadcasting.merge_hpc_runs results/hpc_SUBMISSION_ID.json
```

Merging requires matching task settings and a complete intended probability grid,
and retains the input evidence. Set the SSH and remote-directory options in
`hpc/fetch_results.sh` for your cluster. The encoded trajectory simulator can
require several GB of memory for the largest default convergence points;
plotting saved results does not rerun those simulations.
