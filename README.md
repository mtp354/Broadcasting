# Broadcasting

Numerical simulation, dynamic circuits, and IBM-hardware experiments for the
M-sender, N-receiver quantum broadcasting protocol with optional `[[5,1,3]]`
error correction. See [the manuscript](manuscript/apstemplate.tex),
[the current action plan](ACTION_PLAN.md), and [the correctness review](REVIEW_2026-09-08.md).

## Setup and validation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-tested.txt
pytest
```

`requirements-tested.txt` records the dependency snapshot tested with CPython
3.12.3 on Linux. `requirements.txt` is the unconstrained list of direct development
dependencies. The snapshot does not establish compatibility with every hardware
target. Use `pytest -m "not slow"` for quick mathematical/API checks and the full
suite before changing the experiment pipeline.

## Repository structure

| Path | Purpose |
|---|---|
| `broadcasting/` | Configuration, numerical simulation, circuits/QEC, execution, results, analysis and plotting |
| `tests/` | Local mathematical, execution and data-pipeline validation |
| `hpc/` | CLI and SLURM execution; per-submission source snapshots |
| `scripts/` | Figure generation, existing-data analysis and array merging |
| `run_broadcast.ipynb` | Broadcasting simulation and hardware workflows |
| `qec_testing.ipynb` | Standalone encoded/bare memory benchmark; no broadcasting or senders |
| `visualizations.ipynb` | Saved-result exploration |
| `results/` | Historical raw experiments, including `legacy/` and `qec513/` |
| `analysis/hardware/` | Derived analysis of saved hardware records |
| `figures/sources.json` | Explicit publication figure sources and historical provenance |
| `manuscript/` | LaTeX and the images it actually embeds |

## Reanalyze existing data without collecting experiments

```bash
python scripts/analyze_saved_hardware.py
python scripts/generate_figures.py --formats png,pdf
```

The first command writes `analysis/hardware/report.md`, machine-readable summaries
and derived figures. It preserves job/theta distinctions when estimating joint,
worst-receiver, covariance and asymmetry statistics. The second reads the explicit
figure manifest, checks sources and grids, and updates the selected PNG/PDF images
in `figures/` and `manuscript/`. Neither command launches an experiment by default.

Historic timing/encoding/circuit overrides are documented separately from raw
records. Missing provenance is not silently filled from current backend settings.
Heterogeneous hardware records do not form a controlled scaling experiment simply
because they share M,N. Nonzero receiver-success covariance alone does not establish
correlated physical noise.

The former convergence figure repeated one effective seed while claiming independent
repetitions. It is excluded from the current manuscript. The repaired future
collection path is explicit:

```bash
# Collects NEW simulation data; outside the current pre-collection work phase.
python scripts/generate_figures.py --collect-convergence
```

That path saves the measurements under `results/convergence/` before rendering a
new convergence figure. `--quick` selects a smaller development collection; neither
option is required to regenerate figures supported by existing records.

## Configuration and execution

`ProtocolConfig` defines M, N, real alpha, sender phases, noise sweep, QEC choice,
fixed sender outcomes, delay, trajectory count/seed, and feedforward convention.
Four backends consume it: `ExactBackend`, `SamplingBackend`, `HardwareBackend`, and
`HPCBackend` (which returns a submission receipt rather than completed fidelities).

An explicit `ProtocolConfig.n_samples` or `seed` overrides the corresponding
`SamplingBackend` setting. If a field is `None`, its backend value is used
(200 trajectories by default). The CLI supplies its own explicit 1,000-trajectory
default. Results record effective settings. Set the config seed for each independent
repetition rather than changing a backend seed shadowed by the config.

At backend level, `p_list` lists sweep points, each applied uniformly to every
receiver. In low-level numerical functions it means one probability per receiver.
Backend fidelities describe the whole sweep; `reduced_states` describes only its
last point. `load_run` exposes protocol fields such as `M` and `N` at the top level
of its returned mapping.

In `run_broadcast.ipynb`, choose `MODE` (`exact`, `sampling`, `hardware`,
`hardware_tau_sweep`, or `hpc`) and set the Configuration cell before running the
execution cell. `alpha` is real in [-1,1]; `1/sqrt(2)` is equatorial. Hardware delays
are finite, nonnegative integer dt values respecting the selected backend's timing
constraints; choose unique values in a sweep. Sender `outcomes_list=None` means
random outcomes; provide a list to condition numerical runs on a specific branch.
The default linear feedforward applies the additive phase formula even for invalid
binary sender values greater than N; those events are diagnosed rather than discarded.

Optional analysis/collection flags are disabled by default. Use `qec_testing.ipynb`
for the separate memory benchmark; its hardware flag also defaults to false.
The resource preparation and decoder use the retained generic synthesis.

For future hardware execution, save an IBM Quantum account once:

```python
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(
    channel="ibm_quantum_platform", token="<your token>", name="<profile name>"
)
```

Set the notebook's `IBM_PROFILE`, explicit `IBM_BACKEND`, `SHOTS`, and
`OPTIMIZATION_LEVEL`. New records preserve effective configuration and available
execution/circuit/calibration provenance. Plotting uses recorded backend dt;
historical conversions come from explicit provenance overrides.

## HPC

`HPCBackend(submit=False)` builds an argv list and a shell-quoted command without
submitting. `array=True` assigns one task per probability point; `concurrency`
limits simultaneous tasks. Actual submission requires `submit=True` on the cluster.
Arbitrary ordered grids are preserved, including nonuniform ones. The CLI accepts:

```bash
# Example NEW simulation execution, not needed for existing-data reanalysis.
python -m hpc.run_experiment --mode exact --M 1 --N 2 --p-values 0 0.1 1
```

The older `--p-min`, `--p-max`, and `--p-steps` flags still construct an evenly spaced
grid. Each SLURM submission uses its own source snapshot and archives outputs under
`results/submissions/JOB_ID/`. A later source sync cannot replace a running
submission's source. Validate configured paths on scratch before operational use.
Merge only the matching per-task files for one submission:

```bash
python scripts/merge_hpc_runs.py results/submissions/JOB_ID/run_*.json --output-dir derived/merged
```

New array records preserve the complete intended grid and submission identity.
Merging validates matching configurations and grid completeness before writing.
Historical per-task inputs require `--expected-p-values` followed by the actual
intended grid. Do not pass complete sweeps or unrelated result files. Source records
are never modified.

## Manuscript

```bash
cd manuscript
pdflatex -interaction=nonstopmode apstemplate.tex
bibtex apstemplate
pdflatex -interaction=nonstopmode apstemplate.tex
pdflatex -interaction=nonstopmode apstemplate.tex
```

Regenerate supported figures from the manifest first. New convergence evidence,
controlled hardware repeats/scaling, final authorship details and archive DOI remain
separate data/release steps in `ACTION_PLAN.md`.

## Data preservation

Files in `results/`, including `legacy/` and `qec513/`, are source evidence and must
not be deleted or hand-edited. `save_run` publishes complete JSON atomically and
refuses to replace any existing path, including an explicit `filepath`. Default
names use a fresh UUID even within the same SLURM task. Reanalysis outputs belong
in `analysis/` or `derived/`, separate from raw experiments. See the current
[action plan](ACTION_PLAN.md) for the collection stopping point and preservation rules.
