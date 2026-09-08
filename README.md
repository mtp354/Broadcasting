# Broadcasting

Numerical simulation, dynamic-circuit implementation, and IBM-hardware experiments for the
M-sender, N-receiver quantum broadcasting protocol with optional `[[5,1,3]]` error correction. See
[manuscript/apstemplate.tex](manuscript/apstemplate.tex) for the write-up and
[ACTION_PLAN.md](ACTION_PLAN.md) for the current status of open issues.

## Repository structure

```
broadcasting/       Library: protocol config, backends, circuits, QEC, results I/O, plotting
hpc/                 SLURM/CLI entry point for cluster runs (hpc/run_experiment.py, hpc/slurm_broadcast.sh)
scripts/             Standalone utilities (migrate_results.py, merge_hpc_runs.py)
tests/               pytest suite
run_broadcast.ipynb  Main notebook: exact/sampling/hardware/hpc runs of the broadcasting protocol
qec_testing.ipynb    Standalone [[5,1,3]] encoded-memory benchmark (not the broadcasting protocol --
                     a single logical qubit stored in one code block, no senders/receivers/broadcast)
visualizations.ipynb Loads saved runs from results/ and produces the manuscript figures
results/             Saved run JSON (unified schema) -- hardware runs here cannot be regenerated
manuscript/          LaTeX source and the exact image files embedded in the paper
```

**`run_broadcast.ipynb` vs. `qec_testing.ipynb`:** the former runs the actual M-sender/N-receiver
broadcasting protocol (with or without QEC); the latter is a separate, simpler experiment that just
stores one logical qubit in a single `[[5,1,3]]` block across a delay and checks recovery fidelity --
it does not broadcast anything. Both save into `results/` (`qec_testing.ipynb` uses the dedicated
`results/qec513/` subdirectory).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the test suite:

```bash
pytest
```

### IBM Quantum account (only needed for `MODE="hardware"` / `"hardware_tau_sweep"`)

Save your account once (interactive Python shell or a one-off script):

```python
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(channel="ibm_quantum_platform", token="<your token>", name="<profile name>")
```

Then set `IBM_PROFILE = "<profile name>"` in the notebook's Configuration cell. (The old
`channel="ibm_quantum"` API has been removed by IBM -- use `"ibm_quantum_platform"` for new accounts.)

## Core architecture

Every execution path shares the same two pieces:

- **`ProtocolConfig`** (`broadcasting/protocol.py`) -- one dataclass holding everything that defines a
  run: `M`, `N`, `alpha`, `thetas`, `p_list` (noise sweep), `use_qec`, `outcomes_list`, `tau`,
  `n_samples`, `seed`, `linear_feedforward`.
- **`Backend`** (`broadcasting/backend.py`) -- an abstract base class with four interchangeable
  implementations, all consuming the same `ProtocolConfig`:
  - `ExactBackend` -- full density-matrix simulation (local).
  - `SamplingBackend` -- Monte Carlo Pauli-trajectory simulation (local, QEC only).
  - `HardwareBackend` -- transpiles and submits to real IBM Quantum hardware.
  - `HPCBackend` -- builds (and optionally submits) the `sbatch` command for a SLURM cluster run.

Every run ends with `broadcasting.results.save_run(result, config)`, which writes one JSON file under
`results/` using a schema `load_run`/`list_runs` and the plotting helpers all understand.

## Using `run_broadcast.ipynb`

Everything is controlled from the **Configuration** cell:

| Variable | Meaning |
|---|---|
| `MODE` | `"exact"`, `"sampling"`, `"hardware"`, `"hardware_tau_sweep"`, or `"hpc"` |
| `M`, `N` | Number of senders / receivers |
| `alpha` | Real amplitude parameter (`1/sqrt(2)` = equatorial target state, used throughout the manuscript) |
| `use_qec` | Encode each receiver in a `[[5,1,3]]` block |
| `thetas` / `theta_samples` | Sender phase angle(s); `nt` controls how many random samples are drawn |
| `p_list` | Depolarizing-probability sweep (`exact`/`sampling`/`hpc` modes) |
| `n_samples` | Monte Carlo trajectory count (`sampling`/`hpc` modes) |
| `tau` / `tau_values` | Delay time(s) in backend `dt` units (`hardware`/`hardware_tau_sweep`) |
| `IBM_PROFILE`, `IBM_BACKEND`, `SHOTS`, `OPTIMIZATION_LEVEL` | Hardware execution settings |
| `HPC_MODE`, `HPC_SUBMIT`, `HPC_ARRAY`, `HPC_CONCURRENCY` | Only used when `MODE="hpc"` |

Run the **Run** cell, then the **Save And Plot** cell (saves to `results/` and shows a plot). The two
optional cells below (**Exact Vs Sampling Overlay**, **Sampling Convergence**) are for validating the
Monte Carlo sampler and are gated behind their own `RUN_*` flags (default `False`).

### Reproducing each manuscript figure

| Figure | What it needs | How to get it |
|---|---|---|
| QEC crossover (exact vs. QEC vs. sampling) | `M=1,N=2` exact no-QEC, exact QEC, and sampled QEC `p`-sweeps | `MODE="exact"` with `use_qec=False`, then `use_qec=True`; `MODE="sampling"` with `use_qec=True`. Then run `visualizations.ipynb`'s "QEC Crossover" cell. |
| Sampling convergence (`1/sqrt(n)` fit) | Nothing extra -- self-contained | Set `RUN_CONVERGENCE = True` in the **Optional Sampling Convergence** cell and run it. |
| Delay-vs-fidelity (single backend, `M=1,N=2`) | One hardware tau sweep | `MODE="hardware_tau_sweep"`, `use_qec=False`. Uses `tau_values` and (optionally) multiple `theta_samples`. |
| `[[5,1,3]]` memory benchmark (Fig. 2) | A standalone encoded-qubit delay sweep on hardware | Use **`qec_testing.ipynb`**, not `run_broadcast.ipynb` -- set `RUN_HARDWARE = True` there. This is the standalone memory test, distinct in scope from the broadcasting circuits above. |
| Hardware `(M,N)` scaling | One hardware point (`tau=0`) per `(M,N)` you want plotted, **on a single, consistent backend and shot count** (mixing backends/shots was a real bug fixed in Phase 3 -- see `ACTION_PLAN.md`) | For each `(M,N)`: `MODE="hardware"`, `tau=0`. Then run `visualizations.ipynb`'s "Hardware Fidelity At Tau Zero" cell, which now reports the backend/shots cohort explicitly and will warn you if points don't share a cohort. |
| Large sweeps too slow to run locally/interactively | -- | Use `MODE="hpc"` (see below) instead of `"exact"`/`"sampling"`. |

After collecting hardware data, `visualizations.ipynb` also has cells to compute joint (all-receiver)
fidelity, worst-receiver fidelity, and pairwise receiver covariance directly from the saved joint
readout bitstrings -- no new hardware time needed for those statistics.

### Running on HPC (`MODE="hpc"`)

`HPCBackend` builds the `sbatch` command for `hpc/slurm_broadcast.sh` from the same `ProtocolConfig`
used everywhere else:

```python
MODE = "hpc"
HPC_MODE = "exact"        # or "sampling"
HPC_SUBMIT = False        # True actually calls sbatch -- only works from the HPC login node
HPC_ARRAY = True          # one array task per p_list point instead of one task sweeping all of them
HPC_CONCURRENCY = 10      # optional cap on concurrently-running array tasks
```

Running the **Run** cell with `HPC_SUBMIT = False` just prints the `sbatch` command so you can review
it before actually submitting (`HPC_SUBMIT = True`, run from the cluster). If `HPC_ARRAY = True`, each
array task writes one single-point result file; merge them afterward with:

```bash
python scripts/merge_hpc_runs.py results/run_*.json --output-dir results
```

This only reads the source files and writes one new merged file -- it never modifies or deletes the
per-task originals.

## Building the manuscript

```bash
cd manuscript
pdflatex -interaction=nonstopmode apstemplate.tex
bibtex apstemplate
pdflatex -interaction=nonstopmode apstemplate.tex
pdflatex -interaction=nonstopmode apstemplate.tex
```

Figures embedded in the manuscript live directly in `manuscript/` under their exact caption-matching
filenames (e.g. `manuscript/mc_sampling_convergence.png`). `run_broadcast.ipynb` and
`visualizations.ipynb` write directly to those paths (in addition to `figures/`) when `SAVE_FIGURES =
True`, so re-running the relevant cell updates the actual embedded figure.

## Data safety

Files under `results/`, `results/legacy/`, and `results/qec513/` include hardware runs that **cannot
be regenerated**. Never delete or hand-edit them. `save_run` always writes a new, uniquely-named file
(never overwrites), so re-running any cell is safe -- it will not touch previous results. See
[ACTION_PLAN.md](ACTION_PLAN.md)'s "HPC data-safety ground rules" for the full policy.
