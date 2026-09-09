# Broadcasting

Simulation and IBM Quantum experiments for the M-sender, N-receiver broadcasting
protocol with optional `[[5,1,3]]` error correction.

## Setup

Use Python 3.12 and Bash from the project root:

```bash
bash scripts/setup.sh
source .venv/bin/activate
```

Setup installs `requirements-tested.txt` and runs the offline tests excluding
`slow`. Select `.venv/bin/python` as the notebook kernel. To check an existing
environment or run the complete test suite:

```bash
bash scripts/setup.sh --check
python -m pytest -q
```

`BROADCAST_PYTHON` and `BROADCAST_VENV` override the interpreter and environment
paths. IBM credentials belong in the Qiskit Runtime saved-account store. The
execution notebook selects the saved profile and backend explicitly.

## Two notebooks

[run_broadcast.ipynb](run_broadcast.ipynb) generates and collects data. Its controls
cover exact simulation, Pauli-trajectory sampling, convergence repetitions,
broadcasting size/delay experiments, and encoded/bare single-qubit memory tests.
All acquisition and execution switches default to `False`; Run All previews
settings and reads saved state without contacting IBM or collecting new data.

For hardware, edit the experiment settings, then use the separate **prepare**,
**submit**, and **collect** cells. Preparation freezes compiled circuits and their
configuration for review. Collection retrieves an existing job without submitting
another. `experiments/` holds plans, circuits, submission attempts, and receipts;
completed measurements go to `results/records/`. Resume with the same experiment
folder. If a submission has no saved receipt, attach its existing job ID before
continuing; ambiguous attempts are never automatically resubmitted.

[visualizations.ipynb](visualizations.ipynb) contains all plotting code and produces
manuscript Figures 1–6 from saved records. Each figure has editable source and style
settings: dimensions, colours, lines, markers, axes, legends, and export controls.
The notebook writes PNGs directly to `manuscript/` and records source hashes and
plot settings in `manuscript/figure_sources.json`. Its optional final cell builds
the manuscript PDF locally. Plotting launches no experiments.

| Figure | Content |
|---|---|
| 1 | Monte Carlo convergence: separate seed/receiver errors, total, and reference |
| 2 | Encoded and bare single-qubit memory measurements |
| 3 | Broadcasting circuit diagram |
| 4 | Exact and sampled QEC crossover; optional analytical curves |
| 5 | Three Marrakesh and three Kingston receiver-fidelity delay sweeps |
| 6 | Hardware fidelity versus sender/receiver count |

The optional command-line hardware workflow uses the same implementation:

```bash
python scripts/experiments.py plan configs/hardware_scaling.json
python scripts/experiments.py status experiments/scaling_02
```

Run `python scripts/experiments.py --help` for prepare, submit, collect, and
job-attachment commands. New experiments require a fresh folder when their frozen
settings change. `configs/hardware_repeats.json` and `configs/memory.json` provide
delay-sweep and standalone-memory templates for the same workflow.

## Saved records and numeric analysis

`broadcasting.results.load_run` and `list_runs` read the same schema from
`results/records/`, regardless of collection date or execution route.

| Field | Meaning |
|---|---|
| `record_id` | Stable identity of the saved record |
| `experiment_type` | Simulation, hardware, or an HPC submission receipt |
| `experiment_kind` | `broadcasting` or `memory` |
| `protocol` | M, N, target state, QEC, and phase samples |
| `sweep` | Axis and ordered values: depolarizing probability p or delay tau |
| `fidelities` | Sweep × receiver, averaged over phase samples if present |
| `per_theta_fidelities` | Optional phase sample × sweep × receiver values |
| `counts` | Hardware phase sample × sweep joint receiver histograms |
| `metadata.execution` | Experiment/run/repeat/case identity and execution settings |
| `metadata.provenance` | Source hashes and evidence for attributed metadata |

Memory records use M=0, N=1 and the same fidelity/count dimensions. Receiver 0 is
the least-significant readout bit. Backend `dt` converts saved delays to time;
missing calibration values remain unknown. Distinct jobs, cases, phase samples,
and seeds remain separate observations. A shared Runtime job does not make its
cases independent repetitions.

Generate numeric hardware statistics and a Markdown report:

```bash
python scripts/analyze_saved_hardware.py
```

Outputs in `analysis/hardware/` are `points.json`, `summary.json`,
`scaling_points.json`, and `report.md`. Use `--results-dir`, repeatable
`--include-results-dir`, and `--output-dir` to select other saved records. The
report includes local, mean, worst-receiver and joint fidelity, paired covariance
and asymmetry, recorded invalid sender-outcome rates, and exploratory delay
spectra. It writes no figures. Shot intervals are conditional on each histogram;
they do not quantify between-job drift or identify a physical noise mechanism.

## Reproducibility

Record writes are atomic and refuse existing paths. Preserve source attribution,
execution bundles, and complete saved records; edit plotting settings instead of
measurement values. `results/migration_v2.json` maps imported source paths to
canonical records and records their hashes. The local
`.local-archive/before-results-v2.tar.gz` preserves the original source files and
execution bundles; it is excluded from Git.

The Monte Carlo convergence study stores each completed
sample-size sweep and its exact reference so interrupted work can resume. Seeds
are retained separately; the inverse-square-root line is an anchored reference,
not a fitted convergence exponent or confidence interval.

The encoded trajectory simulator retains all sampled state vectors and a decoded
density accumulator. Its largest default convergence point needs several GB of
memory. `ProtocolConfig` drives exact, sampled, hardware, and HPC backends; an
`HPCBackend` submission receipt contains no completed measurement values.

Build the paper after regenerating figures:

```bash
cd manuscript
pdflatex -interaction=nonstopmode apstemplate.tex
bibtex apstemplate
pdflatex -interaction=nonstopmode apstemplate.tex
pdflatex -interaction=nonstopmode apstemplate.tex
```

Open [docs/remaining_work.md](docs/remaining_work.md) for outstanding manuscript
and release tasks.

## Optional HPC

The notebook workflow needs no cluster. For larger simulations, `hpc/` provides
a local CLI, SLURM submission, immutable source snapshots, and archive transfer.
Set the persistent and scratch paths before running `hpc/setup_scratch.sh`:

```bash
export BROADCAST_GLOBAL_DIR=/global/u/YOUR_USER/Broadcasting
export BROADCAST_SCRATCH_DIR=/scratch/YOUR_USER/Broadcasting
bash hpc/setup_scratch.sh
```

`hpc/slurm_broadcast.sh` submits exact or sampled simulations. Completed records
go to `results/records/`; immutable source snapshots go to
`experiments/submissions/JOB_ID/source/`. `hpc/backup_results.sh` and
`hpc/fetch_results.sh` transfer measurements and snapshots into these folders.
`scripts/merge_hpc_runs.py` combines only matching tasks with a complete intended
probability grid. Use its `--help` for explicit inputs and destinations.
