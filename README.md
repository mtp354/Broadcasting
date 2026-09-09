# Broadcasting — project reference

Simulation, dynamic circuits, and IBM Quantum experiments for the M-sender,
N-receiver broadcasting protocol with optional `[[5,1,3]]` error correction.
This is the single working reference. Superseded reviews and plans remain in Git
history; the [manuscript](manuscript/apstemplate.tex),
[derived hardware report](analysis/hardware/report.md),
[historical figure source manifest](figures/sources.json), and
[manuscript figure source manifest](figures/manuscript_sources.json) retain the
scientific evidence.

Start with [run_broadcast.ipynb](run_broadcast.ipynb). It controls hardware campaigns,
displays existing results, and runs the restored Monte Carlo convergence study.
**No HPC scripts are required for this notebook workflow. All figure exports are PNG.**

[Setup](#setup) · [Notebook campaigns](#notebook-campaigns) ·
[Convergence](#monte-carlo-to-exact-convergence) · [Recovery](#recovery-and-optional-cli) ·
[Analysis and manuscript](#analysis-and-manuscript) · [Protocol](#protocol-contracts) ·
[HPC](#hpc-simulations) · [Remaining work](#current-status-and-remaining-work)

## Setup

Use Bash and Python 3.12. The tested environment is Linux / CPython 3.12.3.
From the project root:

```bash
bash scripts/setup.sh
source .venv/bin/activate
```

Setup creates or reuses `.venv`, installs `requirements-tested.txt`, checks dependency
compatibility, and runs tests excluding `slow`. Installation needs package-index
access. It does not contact IBM or submit experiments. Use
`BROADCAST_PYTHON=/path/to/python3.12` or `BROADCAST_VENV=/absolute/path` to override
Python or the environment directory. `requirements.txt` lists direct dependencies;
keep the tested environment unchanged between preparation and collection.

Open `run_broadcast.ipynb` in your notebook editor and select `.venv/bin/python` as
its kernel. Setup includes the Jupyter kernel and notebook execution dependencies;
the editor supplies the notebook interface. Run from this project root.
**Run All with the checked-in settings reads saved data, prints plans, and writes
three derived PNGs; it makes no IBM requests and collects no new simulation data.**

```bash
bash scripts/setup.sh --check   # Check an installed environment, without installing.
python -m pytest -q            # Full validation, including larger QEC simulations.
```

## Notebook campaigns

### What will run

| Notebook section | Default experiment | Per-circuit shots | Total budget |
|---|---|---:|---|
| Zero-delay scaling | M=1,2,3 × N=1,2,3,4; 12 cases; 3 repeats | 8,192 | 3 jobs, 36 evaluations, 294,912 shots |
| Receiver fidelity versus time | M=1,N=2; 121 delays; 3 different random-angle sweeps | 10,000 | 3 jobs, 363 evaluations, 3,630,000 shots |

Together these are **6 jobs and 3,924,912 shots**. Both use optimization level 3,
real equatorial amplitude, linear feedforward, and unencoded receivers. Each repeat
is one job containing every case/delay for that campaign in a reproducibly shuffled
order. Submitted order need not equal device execution order. Shot counts are a
measurement budget, not a device-time or monetary quote.

Scaling defaults to `SCALING_SENDERS=[1,2,3]` and `SCALING_RECEIVERS=[1,2,3,4]`.
Within a repeat, equal-M cases share angles across N; smaller M uses the prefix of
the same random phase vector. Repeats have different seeded phases. The largest
case needs 13 logical qubits. Generic state preparation can produce deep circuits
and expensive compilation; inspect the actual depths and mappings before submitting.

Delay uses one random angle held constant across each complete sweep, with a new
angle for each repeat. `TAU_VALUES_DT=0,50,…,6000` matches the historical 121-point
grid. Delays are in backend-specific **dt** units, applied to both receivers.
Preparation reports physical times and rejects unsupported timing alignment.
If a target rejects a 50-dt step, explicitly edit the grid and prepare a new folder;
no delays are rounded or silently rescaled. Different phases and acquisition times
mean repeat variation includes both phase dependence and device drift.

### Select the account and settings

The notebook preserves `IBM_PROFILE="mprest1"`. Set `IBM_BACKEND` to an explicit
backend available to that saved profile, then review the phase seed, repeat count,
size lists, delay grid, and campaign directories. No automatic backend is chosen.
If a saved account is needed, run this once in the activated environment:

```bash
python -c '
from getpass import getpass
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(
    channel="ibm_quantum_platform",
    name=input("Account profile name: ").strip(),
    token=getpass("IBM Cloud API key: "),
    instance=input("Instance CRN or name: ").strip(),
)
'
```

Credentials stay in the SDK account store, outside notebooks and the repository.
Preparation checks account access, qubit capacity, target instructions, and timing.

### Prepare, review, submit, collect

Run the notebook sections in order; each action switch initially equals `False`.

1. **Preview:** inspect both plans, total shots, each case, and every repeat's actual
   phase samples. This is offline and works before setting a backend.
2. **Prepare:** enable `PREPARE_SCALING` and/or `PREPARE_DELAY`, then run that cell.
   It fetches the target and compiles locally; it submits no job. It freezes each
   distinct phase's circuits, shares initial layouts across matching sizes, and
   archives source hashes, environment versions, calibration, and circuit mappings.
3. **Review:** inspect dt conversion, compiled depths, layouts, and warnings in the
   following cell. Full per-circuit receiver mappings remain in `bundle["review"]`.
4. **Submit:** enable `SUBMIT_SCALING` and/or `SUBMIT_DELAY` in their separate cells.
   These cells submit the complete configured campaigns at the shot counts above.
   Each attempt is recorded before its request; each job ID is saved immediately.
5. **Collect:** enable `COLLECT_SCALING` and/or `COLLECT_DELAY`. Collection retrieves
   existing jobs and can wait for them to finish. It never submits another job.
6. **Plot:** rerun the saved-data cells. Set `WRITE_ANALYSIS=True` for the detailed
   per-campaign report. Reset action switches to `False` before a later general Run All.

Default bundles are `campaigns/scaling_01/` and `campaigns/delay_01/`. Use the same
folder to resume; completed submissions/results are skipped. Changed settings fail
against a frozen bundle: restore the old settings or choose a new folder and campaign
ID. Failed preparation retains its diagnostic plan; correct the error and use a new
folder. Preserve the whole bundle, including compiled circuits, attempts, receipts,
and `results/repeat_###_case.json`. Local campaign directories are Git-ignored.
Collected campaign dates identify submission time (the original attempt time for a
recovered job); `timestamp_source` states that meaning. Preparation time is retained
separately. These dates do not claim the exact device execution time.

## Monte Carlo-to-exact convergence

The notebook displays the restored **log–log** curve immediately, then has a separate
`RUN_CONVERGENCE=False` cell to add **two independent seed repetitions, 1 and 2**.
It repeats the original physical scenario and full grid:

- M=1, N=2, alpha=1/√2, theta=[0], QEC enabled, sender outcome [0].
- 21 equally spaced depolarizing probabilities from 0 to 1.
- Trajectory counts 50, 100, 200, 500, 1,000, 2,000, 5,000, 10,000, 50,000, 100,000.
- Error is the sum over receivers of the trapezoidal integral over p of absolute
  sampled-minus-exact fidelity error. Both axes use logarithmic scales.

The original seed-0 errors were recovered from the May 14 notebook at commit
`0b3735a51f779a77ac706de52255477fd7f5536f` and are preserved with source/hash evidence
in [historical_summary.json](analysis/convergence/historical_summary.json).
Those are printed summaries rounded to eight decimal places, not reconstructed raw
fidelity grids. A bounded current-code regression reproduces the original 50-trajectory
point within that precision. The later withdrawn plot reused one effective seed and
remains excluded; it is separate from this valid historical size sweep.

Enable `RUN_CONVERGENCE` and run that cell when ready for new local CPU computation.
The 100,000-trajectory point retains about **4.9 GB of encoded vectors alone**, plus
working buffers, and can take substantial time. Keep sufficient free memory.
HPC is optional if more resources are needed; no cluster scripts are invoked here.

`results/convergence/repeats_01/` stores the exact reference, study settings, and each
completed trajectory-count sweep immediately. Rerun the same batch directory and
seeds to resume; completed files are validated and preserved. An interrupted
individual sweep restarts from that sweep. For additional independent curves, use
new seeds and a new batch directory. The plot overlays each seed separately alongside
the historical curve. Its n⁻¹ᐟ² line is an anchored reference, not a fitted claim or
an uncertainty estimate; sample counts within one seed curve are correlated.

## Recovery and optional CLI

The notebook and CLI use the same campaign implementation. Offline status is:

```bash
python scripts/hardware_campaign.py status campaigns/delay_01
```

If submission stopped after requesting a job but before saving its receipt, it is
**ambiguous** and automatic resubmission stops. Find the existing job using the tags
in the attempted bundle and attach it to the **zero-based** repeat index:

```bash
python scripts/hardware_campaign.py attach-job campaigns/delay_01 --repeat 0 --job-id YOUR_JOB_ID
python scripts/hardware_campaign.py collect campaigns/delay_01
```

The notebook equivalent is `attach_job(DELAY_RUN_DIR, repeat=0, job_id="...")`.
Attachment verifies the job against the archived submission. Do not remove attempt
files or create a duplicate campaign to retry an ambiguous request. If a job failed,
was cancelled, or does not exist, reconcile its remote status before preparing a
clearly identified replacement cohort. Local status reports receipts, not the live queue.

For operation without a notebook, copy either checked-in configuration, edit its
account/backend, and use a fresh folder:

```bash
cp configs/hardware_repeats.json configs/hardware_repeats.local.json
python scripts/hardware_campaign.py plan configs/hardware_repeats.local.json
python scripts/hardware_campaign.py prepare configs/hardware_repeats.local.json --run-dir campaigns/delay_01
python scripts/hardware_campaign.py submit campaigns/delay_01
python scripts/hardware_campaign.py collect campaigns/delay_01
```

`configs/hardware_scaling.json` provides the other campaign. These schema-v2
configurations archive a seeded random phase schedule by repeat and case. Fixed
phase designs and old schema-v1 configurations/prepared bundles remain supported.

## Analysis and manuscript

`run_broadcast.ipynb` and `visualizations.ipynb` load historical records and collected
campaign records together. Receipts and analysis JSON are excluded. Separate jobs,
cases, and angles remain separate; duplicate saves of the same observation are removed.

For the manuscript, open [visualizations.ipynb](visualizations.ipynb) and run the
self-contained **Manuscript figures** cell near the top. It imports its own
dependencies and reads saved inputs, so earlier cells need not be executed. Edit
`QISKIT_PALETTE`, `PLOT_RC`, `EXPORT`, and the `FIGURE_1`, `FIGURE_2`, `FIGURE_4`,
`FIGURE_5`, and `FIGURE_6` dictionaries in that cell to adjust shared styling,
source selection, and each figure's plotting controls, including sizes, colours,
markers, lines, axes, labels, and legends. The palette uses the circuit diagram's
burgundy (`#9F1853`), cyan (`#33B1FF`), coral (`#FA4D56`), and slate (`#778899`).
Rerun the cell to preview changes.

`SAVE_MANUSCRIPT_FIGURES=True` writes the following PNGs into both `manuscript/`
and `figures/`, matching the manuscript's figure references:

| Figure | PNG | Default saved evidence |
|---|---|---|
| 1 | `figure_01_sampling_convergence.png` | Five separate Monte Carlo seed curves, 0–4, with receiver errors, total error, and reference |
| 2 | `figure_02_qec_memory.png` | Four pinned encoded/bare QEC memory curves, retaining each saved fidelity and delay grid |
| 4 | `figure_04_qec_crossover.png` | Pinned QEC crossover simulation sources |
| 5 | `figure_05_delay_repeats.png` | Two panels: the three Marrakesh sweeps from `delay_01` overlaid on the left, the three Kingston sweeps from `delay_02` on the right. Each uses saved repeats 000–002; all are 121-point, opt3, M=1/N=2 delay sweeps. |
| 6 | `figure_06_hardware_scaling.png` | All 55 qualifying opt3, zero-delay observations |

Figure 3 is the existing Qiskit circuit diagram, `manuscript/m1n2qec0_circ.png`.
The cell renders all five data plots; it does not redraw the circuit.

The cell writes `figures/manuscript_sources.json` with input paths, SHA-256 hashes,
and plotting settings for these exports. Set `SAVE_MANUSCRIPT_FIGURES=False` to
preview without replacing the exported assets. These dedicated filenames keep
the historical `scripts/generate_figures.py` exports from overwriting the selected
manuscript figures. No hardware jobs or new simulations are launched by this cell.

The campaign notebook also exports exploratory plots to `figures/campaigns/`:

| PNG | Meaning | Manuscript use |
|---|---|---|
| `hardware_scaling_opt3.png` | Fidelity y, receiver count N x, sender count M colour; opt3/tau0 only. Points are receiver means; vertical bars span receiver min–max. | Figure 6 supporting analysis |
| `receiver_fidelity_vs_time_repeats.png` | Separate receiver curves for each repeat/angle, recorded time units, and Wilson shot intervals; latest two historical sweeps plus the selected campaign. | Figure 5 supporting analysis |
| `mc_sampling_convergence.png` | Restored historical curve plus compatible new seed curves, on log–log axes. | Figure 1 supporting analysis |

Receiver-range bars describe receiver variation, not confidence intervals. Historical
backend/date/shot differences remain visible or archived in plotted-point metadata.
Changing N also changes the resource/circuit and may change physical layout, so the
plot alone does not establish a size-only causal effect. Phase changes across delay
jobs are deliberate and must be retained in comparisons.

For full statistics without notebook execution:

```bash
python scripts/analyze_saved_hardware.py --results-dir campaigns/delay_01/results
# Combined historical and collected comparison, written to a separate derived folder:
python scripts/analyze_saved_hardware.py --include-results-dir campaigns --output-dir analysis/combined
```

The report includes per-histogram local, joint and worst-receiver fidelity, receiver
pairs/covariance, exploratory spectra, plotted scaling-point provenance, and separate
delay PNGs. Marginal/joint intervals use Wilson scores; worst-receiver bounds use
Bonferroni adjustment; mean/paired uncertainties retain within-histogram covariance.
These assume independent shots with fixed probabilities within each histogram.
They do not estimate between-job drift or establish a periodic physical mechanism.

Regenerate the historical publication assets from saved data only:

```bash
python scripts/analyze_saved_hardware.py
python scripts/generate_figures.py
```

The historical generator's hardware/memory sources remain explicitly pinned by its
25-record SHA-256 manifest. Use the **Manuscript figures** cell for all five selected
data plots and their separate manifest. Figure 2's QEC memory benchmark and Figure
4's crossover simulation retain their separately pinned sources. Figure 3's circuit
diagram remains a separate asset.

The manuscript embeds PNGs. All 15 existing generated PDF figures were removed;
external reference papers and the complete compiled manuscript PDF are retained.
PNG is the sole supported shared figure-save format, including notebook exports.

## Protocol contracts

`ProtocolConfig` is shared by `ExactBackend`, `SamplingBackend`, `HardwareBackend`,
and `HPCBackend`. The first two use native-qudit numerical evolution; hardware
uses binary sender encoding and dynamic circuits. `HPCBackend` returns a submission
receipt, not completed fidelities. Direct `HardwareBackend.run` / `run_tau_sweep`
submit immediately; use the campaign notebook or CLI for the prepared repeat workflow.

- M,N are positive integers; the high-level API accepts real alpha in [-1,1] and
  M finite real sender phases. Low-level state constructors have broader amplitude
  support; that is not a claim of arbitrary complex high-level inputs.
- At backend level, `p_list` is a sweep grid, applied uniformly to every receiver.
  In low-level numerical functions it contains one probability per receiver.
- Explicit config `n_samples`/`seed` override sampling-backend defaults. Unset
  trajectory count uses 200; the simulation CLI explicitly defaults to 1,000.
  Set the config seed separately for independent repetitions.
- Numerical `outcomes_list=None` samples a sender branch; a list selects that
  branch. Hardware uses all measured branches without postselection. Linear
  feedforward applies the additive phase formula even to invalid binary values
  greater than N and reports their observed frequency.
- Fidelities describe a single point or the whole sweep; `reduced_states` describes
  only the final simulation sweep point. Receiver index 0 is the least-significant
  readout bit. Shot-aligned register columns preserve pairing across readouts.
- Under the ideal independent phase-covariant receiver-channel assumptions, every
  sender branch yields the same product output. For depolarizing noise,
  `F_i = 1 - 2p_i/3` and joint fidelity is the product. Ideal QEC replaces p by
  `p_L = 10p² - (200/9)p³ + (160/9)p⁴ - (128/27)p⁵`.
  The low-noise break-even point is `(3-sqrt(6))/4`; p=3/4 is full depolarization,
  and p>3/4 is the negative-contraction regime, not a second fault-tolerance threshold.

Production stabilizer/syndrome logic is shared, while the binary-symplectic test
oracle independently enumerates all 1,024 Pauli patterns. Numerical and Qiskit
representations have independent ordering/factorization tests. The retained
implementation uses generic resource synthesis and the Gram–Schmidt decoder.
Sampling retains trajectories and decoded density accumulation; it is not a
streaming or scalar-only method. Coherent multi-syndrome inputs require exact
recovery, not the sampled Pauli recovery path.

## HPC simulations

HPC is for exact/trajectory simulations, separate from IBM hardware campaigns.
On the Arrow login node, with the checkout in persistent storage:

```bash
export BROADCAST_GLOBAL_DIR=/global/u/YOUR_USER/Broadcasting
export BROADCAST_SCRATCH_DIR=/scratch/YOUR_USER/Broadcasting
cd "$BROADCAST_GLOBAL_DIR"
bash hpc/setup_scratch.sh
```

Setup reuses the same tested dependency installer and creates the scratch venv.
`BROADCAST_PYTHON_MODULE` overrides the default `Compilers/Python/3.12.13`.
The remaining SLURM script takes a fresh immutable source snapshot per submission;
there are no separate demo scripts or shared source copies for executing tasks.
Validate cluster paths with this small **new simulation submission** first:

```bash
sbatch --cpus-per-task=1 --mem=2G --time=00:10:00 --export=ALL,M=1,N=1,P_STEPS=3,SEED=42 hpc/slurm_broadcast.sh
```

For an explicit nonuniform array, use a correctly sized task range:

```bash
sbatch --array=0-2%2 --export='ALL,M=1,N=2,P_LIST=0 0.1 1,SEED=42' hpc/slurm_broadcast.sh
```

The equivalent local CLI is `python -m hpc.run_experiment --mode exact --M 1 --N 2
--p-values 0 0.1 1` (on one line). It also collects new simulation results.
The older `--p-min`, `--p-max`, `--p-steps` options remain available.
`HPCBackend(submit=False)` builds a shell-safe command without submitting.

Completed records and their source snapshot are archived under
`results/submissions/JOB_ID/`. `bash hpc/backup_results.sh` copies outstanding
scratch records. Locally, `bash hpc/fetch_results.sh` fetches the archive; its
`BROADCAST_SSH_USER`, `BROADCAST_JUMP_HOST`, `BROADCAST_CLUSTER_HOST`,
`BROADCAST_REMOTE_RESULTS`, and `BROADCAST_LOCAL_RESULTS` variables override the
original Arrow account defaults. Copies preserve existing result files.

```bash
python scripts/merge_hpc_runs.py results/submissions/JOB_ID/run_*.json --output-dir derived/merged
```

Merge only per-task records from one experiment. The merger requires matching
configuration, phases, seed, code/submission identity, and the complete intended
grid. Historical task files without that grid require `--expected-p-values`.
Incomplete or mixed groups fail before any output is written.

## Files and data preservation

| Path | Responsibility |
|---|---|
| `broadcasting/` | Protocol, numerical/circuit backends, campaign orchestration, convergence, storage and plots |
| `configs/`, `scripts/` | Campaign definitions, setup, CLI, saved-data analysis and figure generation |
| `tests/` | Offline numerical, circuit, notebook, provenance and execution regressions |
| `hpc/` | Optional simulation CLI and cluster/archive tools |
| `run_broadcast.ipynb` | Main hardware campaign and convergence workflow |
| `visualizations.ipynb` | Configurable manuscript Figures 1, 2, 4, 5, and 6 and additional saved-result exploration |
| `qec_testing.ipynb` | Separate encoded/bare memory benchmark; hardware defaults off |
| `results/`, `campaigns/*/results/` | Historical raw evidence and new immutable records |
| `analysis/`, `figures/` | Derived outputs and explicit source provenance |
| `manuscript/`, `docs/*.pdf` | Current paper/PNG assets and external reference literature |

Never overwrite, delete, rename, or hand-repair raw experiment files. JSON publication
is atomic and refuses existing paths. All 97 historical JSON files retain their paths
and hashes. Historical metadata corrections are evidence-backed loader overrides;
no derived plot repairs a raw record. The two withdrawn convergence PNGs remain
historical evidence only, excluded from publication. Their redundant PDF was removed.

## Current status and remaining work

The numerical corrections, factorization proof, independent QEC oracle, execution
provenance, historical reanalysis, notebook campaign setup, and PNG/manuscript
corrections are implemented. Historical analysis covers **16 broadcasting jobs,
819 per-theta/per-delay histograms, and 5 unique standalone memory jobs**. Hardware
QEC evidence is a separate memory benchmark; full QEC-enhanced broadcasting has not
been demonstrated. Phase-independent classical transcripts are not a general
security proof.

Saved scaling and delay campaigns now contain all three requested repeats, and
four complete new Monte Carlo seed curves are available alongside the historical
seed-0 summary. The manuscript figure workflow integrates those saved results with
historical observations. This integration reads existing data and does not submit
IBM/SLURM jobs or collect new experiments.

Earlier validation on 2026-09-08: **327 tests passed**. Both main notebooks executed in a
real Jupyter kernel with acquisition disabled (30 and 18 cells, zero errors).
The manuscript builds to 12 pages without warnings; all rendered pages were
inspected. The 819 historical histogram summaries retain their earlier statistics
to floating-point precision, and all 97 raw files retain their paths and SHA-256
hashes. Dependency and diff checks pass.

Remaining work:

1. Assess size/layout effects, receiver asymmetry, phase dependence, and run variation.
   Preserve negative or inconclusive results. Additional controls or delay ablations
   should follow the evidence.
2. Review Figures 1–6, convergence overlays, captions, and statistical
   claims for release. Tune their exposed notebook settings and regenerate the PNGs
   as needed. Conditional shot intervals do not replace repetition-based uncertainty.
3. Finalize author/affiliation details, archive deposit/DOI, and release checks.

Generic resource preparation and Gram–Schmidt decoding remain the selected methods.
Structured synthesis/decoding, streaming simulation tiers, and dynamical-decoupling
ablations are closed scope decisions, not outstanding implementation commitments.

Build the manuscript after regenerating its selected PNGs:

```bash
cd manuscript
pdflatex -interaction=nonstopmode apstemplate.tex
bibtex apstemplate
pdflatex -interaction=nonstopmode apstemplate.tex
pdflatex -interaction=nonstopmode apstemplate.tex
```

The compiled PDF is a local whole-paper preview. Source and PNG figure assets are
versioned. Before release, run the complete tests and inspect the final paper layout.
