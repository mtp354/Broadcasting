# Broadcasting

Simulation and IBM Quantum measurements of the M-sender, N-receiver broadcasting
protocol with optional `[[5,1,3]]` error correction.

## Setup

Use Python 3.12 and Bash from the project root:

```bash
bash scripts/setup.sh
source .venv/bin/activate
```

Select `.venv/bin/python` as the notebook kernel. Setup installs the tested
requirements and runs the offline tests excluding `slow`. To check an existing
environment or run every test:

```bash
bash scripts/setup.sh --check
python -m pytest -q
```

`BROADCAST_PYTHON` and `BROADCAST_VENV` override the interpreter and environment
paths. Save IBM credentials in Qiskit Runtime's account store; select the account
and backend explicitly in the execution notebook.

## Two notebooks

[run_broadcast.ipynb](run_broadcast.ipynb) contains the editable settings for exact
simulation, Pauli-trajectory sampling, convergence repetitions, broadcasting
size/delay measurements, and encoded/bare single-qubit memory tests. Execution
switches default to `False`. Run All reads saved state and previews settings.
Enable preparation, submission, and collection separately when collecting data.

Each hardware job uses one JSON file in `results/`. It holds its configuration,
compiled circuits, submission attempt and receipt, and measured cases. Resume
using the same file. If submission was interrupted without a receipt, attach the
existing job ID before continuing; an ambiguous submission is never automatically
repeated. Completed measurements remain immutable.

[visualizations.ipynb](visualizations.ipynb) contains all plotting code and exports
all six figures directly into `manuscript/`, then optionally rebuilds the PDF.
Each figure cell exposes its sources, dimensions, colours, lines, axes, legends,
and layout. Shared controls include `FONT_SIZE`, `LEGEND_FONT_SIZE`,
`INSET_FONT_SIZE`, and export resolution. Set `SAVE_MANUSCRIPT_FIGURES=False` for
a preview without writing files, or `BUILD_MANUSCRIPT=False` to export only PNGs.

| Figure | Content |
|---|---|
| 1 | Separate Monte Carlo seed/receiver errors, their total, and a reference |
| 2 | Encoded and bare single-qubit memory measurements |
| 3 | Broadcasting circuit in one uninterrupted row |
| 4 | Exact and sampled QEC crossover, with an enlarged inset |
| 5 | Three Marrakesh and three Kingston delay sweeps |
| 6 | Hardware fidelity versus sender/receiver count |

The optional `scripts/experiments.py` CLI uses the same hardware workflow. See its
`--help`; the notebook is the primary place to edit experiment settings.

## Self-contained results

`results/` is flat: every file is a JSON result, with no configuration files,
execution directories, study indexes, or migration manifests. Simulations contain
their protocol, sweep, seed, measured values, and source evidence. Runtime job
results additionally contain their preparation and recovery state; a job with
several cases keeps those measurements together in the same file.

`broadcasting.results.list_runs` exposes the measured cases as individual numeric
records for analysis. Each case has a stable `record_id`; several cases may share
a physical JSON path and a Runtime job ID. Use the case identity when selecting a
measurement within such a file. Distinct jobs, cases, phase samples, and seeds
remain separate observations.

Memory measurements use M=0, N=1 and the same sweep/receiver/count dimensions as
broadcasting. Receiver 0 is the least-significant readout bit. Recorded backend
`dt` converts delays to physical time; missing calibration remains unknown.

Each sampled convergence result embeds the exact reference and settings needed
to recompute its error. Seed 0 retains the available rounded error measurements
and states explicitly that its raw fidelity grids are unavailable. Convergence
summaries are excluded from the default measured-record view. The inverse-square-
root curve is an anchored reference, not a fitted exponent or confidence interval.

The figure export records its settings and source hashes in
`manuscript/figure_sources.json`. This is a reproducibility record for the derived
figures; it is not needed to load or interpret a measurement. Superseded source
files are preserved in a verified local archive excluded from Git.

## Numeric analysis and manuscript

```bash
python scripts/analyze_saved_hardware.py
```

This writes JSON statistics and a Markdown report in `analysis/hardware/`, with
no figures or new measurements. It includes local, mean, worst-receiver, and joint
fidelity, paired covariance and asymmetry, recorded invalid sender outcomes, and
exploratory delay spectra. Source paths and hashes connect summaries to the full
records. Shot intervals are conditional on each histogram and do not measure
between-job variation or identify a physical noise mechanism.

The manuscript includes the saved-repeat assessment and QEC implementation
reference. Author details and the public archive/DOI will be finalized manually.
The notebook builds LaTeX in a temporary directory and publishes the completed
PDF to `manuscript/apstemplate.pdf`.

## Optional HPC

`hpc/` provides a local simulation CLI, SLURM execution, and result transfer.
Configure `BROADCAST_GLOBAL_DIR` and `BROADCAST_SCRATCH_DIR` for the cluster, then
run `hpc/setup_scratch.sh`. Measured JSON files go directly into `results/`; source
provenance travels inside each result. A cluster job JSON embeds its frozen source,
requirements, arguments, and completed task measurements. Fetching accepts verified
new tasks while preserving existing ones and rejects conflicting job histories.
`scripts/merge_hpc_runs.py` combines only
matching tasks with a complete intended probability grid and preserves their
input evidence. Consult each script's `--help` or editable shell settings.

The encoded trajectory simulator retains all sampled state vectors and a decoded
density accumulator; the largest default convergence point requires several GB
of memory. Plotting saved results does not rerun these simulations.
