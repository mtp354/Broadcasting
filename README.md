# Broadcasting — project reference

Simulation, dynamic circuits, and IBM Quantum experiments for the M-sender,
N-receiver broadcasting protocol with optional `[[5,1,3]]` error correction.
This is the single working reference for setup, experiment operation, validated
behaviour, and remaining work. Superseded reviews and action plans remain in Git
history at commit `62e35aa`; their unresolved items are consolidated below.
The [manuscript](manuscript/apstemplate.tex), [derived hardware report](analysis/hardware/report.md),
and [figure source manifest](figures/sources.json) retain the scientific evidence.

[Setup](#setup) · [Hardware repeats and scaling](#hardware-repeats-and-scaling) ·
[Recovery](#recover-an-interrupted-campaign) · [Analysis](#analyze-saved-data) ·
[Protocol contracts](#protocol-contracts) · [HPC](#hpc-simulations) ·
[Remaining work](#current-status-and-remaining-work)

## Setup

Use Linux or macOS with Bash and Python 3.12. The tested dependency snapshot was
validated on Linux with CPython 3.12.3; other platforms are not yet verified.
From this checkout:

```bash
bash scripts/setup.sh
source .venv/bin/activate
```

The script creates or reuses `.venv`, installs `requirements-tested.txt`, checks
dependency compatibility, and runs the local tests excluding `slow`. It does not
contact IBM or submit experiments. Installation needs access to the Python package
index. Use `BROADCAST_PYTHON=/path/to/python3.12` to select Python, or
`BROADCAST_VENV=/absolute/path` to use a different environment.

```bash
# Check an existing environment without installing anything.
bash scripts/setup.sh --check

# Full validation, including the larger QEC simulations.
python -m pytest -q
```

`requirements.txt` lists direct dependencies without pins. Use the tested snapshot
for campaigns, and keep the environment unchanged between preparation and collection.

## Hardware repeats and scaling

The CLI handles broadcasting repeats without running a notebook. It deliberately
has separate planning, preparation, submission, and collection commands. **Only
`submit` submits new hardware jobs.** `prepare` reads the selected backend and
compiles locally; `collect` retrieves existing jobs. `plan` and `status` are offline.
Hardware account access and device compatibility are checked when you prepare;
no particular backend is assumed available.

### 1. Choose the experiment

| Configuration | Measurements | Default budget |
|---|---|---|
| [hardware_repeats.json](configs/hardware_repeats.json) | M=1, N=2; uniform delays, receiver-0-only delays, receiver-1-only delays; 2 sender phases; 9 delays; 3 repeats | 3 jobs, 162 circuit readouts, 663,552 shots |
| [hardware_scaling.json](configs/hardware_scaling.json) | M=1; N=1,2,3; zero added delay; 2 sender phases; 3 repeats | 3 jobs, 18 circuit readouts, 73,728 shots |

Both use real equatorial amplitude, 4,096 shots per circuit, optimization level 3,
linear feedforward, fixed transpiler and ordering seeds, and unencoded receivers.
Each repeat is one job containing all cases, with a separately shuffled circuit
order. The order is reproducible and archived. Submitted order is not a guarantee
of chronological execution on the device; execution metadata is retained when
provided. IBM describes timing spans in its [Sampler output documentation](https://quantum.cloud.ibm.com/docs/en/guides/sampler-input-output).

The delay grid is `0, 768, …, 6144` in **backend dt units**. Preparation reports its
actual time conversion. For a 4 ns dt this is a 3.072 µs step and 24.576 µs span.
This is a coarse repeat/asymmetry pilot; it cannot resolve the previously observed
near-0.5 µs spectral peaks. A dedicated periodicity study needs a finer, separately
budgeted grid and independent repetitions. Three repeats provide an initial view
of variation, not a precise drift model or guaranteed statistical power.

Receiver-specific delays diagnose sensitivity to where idle time is inserted;
other operations and scheduler-induced idle time still contribute. The small
scaling cohort holds backend, shots, phases, and compilation settings fixed, but
changing N changes the resource, circuit, and potentially physical-qubit mapping.
It does not establish a size-only causal effect.

### 2. Save an IBM account and select a backend

If you already have a named saved Runtime account, use its name. Otherwise, run
this once in your activated environment; the token is entered without echo and
stays out of the command history and repository:

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

The SDK saves credentials in its user account store. See IBM's
[credential setup](https://quantum.cloud.ibm.com/docs/en/guides/save-credentials)
for account/instance details. Select a backend accessible to that instance with
[dynamic-circuit support](https://quantum.cloud.ibm.com/docs/en/guides/execute-dynamic-circuits).
The campaign never selects the least-busy device automatically.

```bash
cp configs/hardware_repeats.json configs/hardware_repeats.local.json
```

Edit `runtime_account` and `backend` in that local JSON, replacing `EDIT_ME` with
the saved profile name and explicit backend name. Review shots, repeats, phases,
and delays. JSON accepts numbers, not Python expressions such as `pi/4`.
`seed` controls submitted order; `seed_transpiler` controls circuit compilation.
Each case's `initial_layout` can specify physical qubits in logical input-qubit
order; leave it `null` for the automatic shared-layout preparation.

### 3. Plan and prepare — no hardware jobs

```bash
python scripts/hardware_campaign.py plan configs/hardware_repeats.local.json
python scripts/hardware_campaign.py prepare configs/hardware_repeats.local.json --run-dir campaigns/repeats_01
python scripts/hardware_campaign.py status campaigns/repeats_01
```

`plan` validates the configuration and reports the budget; add `--full` to inspect
the complete submitted circuit order. `prepare` uses a new
run directory, validates delay alignment and target instructions, freezes compiled
circuits, and records configuration, source hashes, dependency versions, layout and available
calibration. It shares an initial layout across matching sizes and records output
mapping differences. Review the printed physical delay range, layouts, comparison
warnings, and counts before submission. An unavailable dynamic-circuit duration
is reported as unavailable; the shot count is not an execution-time or cost quote.

The campaign bundle contains the frozen plan/circuits, submission attempts and
receipts, and collected results. Repeats replay the archived bound circuits without
retranspilation. Editing the original config after preparation does not alter the
bundle. To change the experiment, prepare a new directory and keep the old one.
If preparation fails after creating its directory, correct the reported account,
target or timing problem and retry with a new directory. No job was submitted.

### 4. Submit and collect — these commands are for new hardware data

```bash
python scripts/hardware_campaign.py submit campaigns/repeats_01
python scripts/hardware_campaign.py status campaigns/repeats_01
python scripts/hardware_campaign.py collect campaigns/repeats_01
```

`submit` records an attempt before each request and saves its job ID immediately.
Already recorded jobs are skipped on subsequent invocations. `collect` retrieves
known jobs and writes one immutable result per repeat and case under
`campaigns/repeats_01/results/`. It can be run again after an interruption without
submitting more jobs or replacing completed results.
Collection may wait while a job is queued or running; interrupting that wait is
safe. `status` reports local receipts and files, not the live IBM queue state.

Use the same sequence with `hardware_scaling.json`, a local copy, and a separate
bundle such as `campaigns/scaling_01`. Run on the same chosen backend and record
collection dates; separate campaigns are not necessarily acquired in one calibration
window. Archive the **whole campaign directory**, including receipts and compiled
circuits, rather than copying only the final result JSONs. Local campaign bundles
and local config copies are ignored by Git.

### Recover an interrupted campaign

```bash
python scripts/hardware_campaign.py status campaigns/repeats_01
python scripts/hardware_campaign.py collect campaigns/repeats_01
```

If interruption occurred after the submission request but before its receipt was
saved, status reports an ambiguous attempt. Automatic resubmission stops because
the remote job may already exist. Find the tagged job in the IBM dashboard, then
attach that existing job to its **zero-based** repeat index:

```bash
python scripts/hardware_campaign.py attach-job campaigns/repeats_01 --repeat 0 --job-id YOUR_JOB_ID
python scripts/hardware_campaign.py collect campaigns/repeats_01
```

Attachment checks the archived identity against the existing job. Do not delete an
attempt file to force a retry. If no corresponding job exists, or a job failed or
was cancelled, preserve the attempted bundle and explicitly plan a replacement
cohort after reconciling its status. A replacement is additional acquisition and
must remain distinguishable from the originally intended repetitions.

## Analyze saved data

Analyze a collected campaign without submitting anything:

```bash
python scripts/analyze_saved_hardware.py --results-dir campaigns/repeats_01/results
```

This writes `campaigns/repeats_01/analysis/report.md`, `summary.json`, `points.json`,
and figures. `--output-dir PATH` selects another derived-output directory.
Distinct cases in the same job remain separate. The output preserves repeat/case,
job, theta and delay identities; it reports local, joint and worst-receiver
fidelity, paired receiver differences, and receiver-success covariance. Compare
matched points across repeats to assess run variation. The conditional shot
intervals do not themselves estimate between-job variation, and multiple cases in
one job are not independent job repetitions.

For the historical collection and existing publication figures:

```bash
python scripts/analyze_saved_hardware.py
python scripts/generate_figures.py --formats png,pdf
```

These commands read saved data only. Figure generation checks selected input
records against the 25-record SHA-256 manifest in `figures/sources.json`. New campaign data are not
silently added to the publication manifest. Review new results before selecting
sources and revising manuscript claims.

Marginal/joint intervals use Wilson scores; worst-receiver bounds use Bonferroni
adjustment; mean and paired uncertainties retain within-histogram covariance.
These calculations assume fixed probabilities and independent shots within a
histogram. They do not identify physical noise correlations or establish a
periodic mechanism. Missing historical timing or encoding flags are handled by
explicit evidence-backed manifest overrides, never by modifying raw records.

## Protocol contracts

`ProtocolConfig` is shared by `ExactBackend`, `SamplingBackend`, `HardwareBackend`,
and `HPCBackend`. The first two use native-qudit numerical evolution; hardware
uses binary sender encoding and dynamic circuits. `HPCBackend` returns a submission
receipt, not completed fidelities. Direct `HardwareBackend.run` / `run_tau_sweep`
submit immediately; use the campaign CLI for the prepared repeat workflow.

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
| `broadcasting/` | Protocol, numerical/circuit implementations, backends, campaign orchestration, storage and analysis |
| `configs/`, `scripts/` | Hardware campaign definitions, setup/operation, saved-data analysis, figure generation and merging |
| `tests/` | Offline numerical, circuit, data and execution regressions |
| `hpc/` | Simulation CLI, cluster setup, snapshot submission and archive transfer |
| `run_broadcast.ipynb` | Interactive simulation and exploratory single-job hardware workflows |
| `qec_testing.ipynb` | Separate encoded/bare memory benchmark; hardware flag defaults off |
| `visualizations.ipynb` | Saved-result exploration |
| `results/` | Historical raw evidence, including `legacy/` and `qec513/` |
| `analysis/`, `figures/` | Derived reports/figures and explicit publication provenance |
| `manuscript/` | Current paper, bibliography and publication figure assets |
| `docs/*.pdf` | External reference literature, retained separately from project guidance |

Never overwrite, delete, rename or hand-repair raw experiment files. `write_run_json`
and `save_run` publish complete JSON atomically and refuse existing paths; default
filenames include unique IDs. The 97 historical JSON files are preserved.
`load_run` reads the unified schema and adds convenience aliases for plotting;
original pre-migration and standalone memory schemas require their respective
analysis adapters. The obsolete in-place migration utility has been removed.

The three [withdrawn convergence assets](figures/withdrawn/) remain historical
evidence only. Their alleged independent repetitions shared one effective seed.
They are excluded from the manuscript and default generator; other unattributed
historical assets are preserved. No derived plot repairs a raw record.

## Current status and remaining work

The numerical corrections, general factorization proof, independent QEC oracle,
execution/provenance fixes, historical reanalysis and supported figure/manuscript
corrections are complete. Historical analysis covers **16 broadcasting jobs,
819 per-theta/per-delay histograms, and 5 unique standalone memory jobs**. Hardware
QEC evidence is a separate memory benchmark, not a demonstrated full QEC-enhanced
broadcasting experiment. The classical transcript is phase-independent; receiver
quantum states carry the aggregate phase. This is not a general security proof.

The hardware campaign setup and readability cleanup are locally validated;
**no new experimental data or IBM/SLURM submissions were made during this work**.
Live backend and cluster execution remain to be checked. Missing calibration
values and dynamic timing estimates stay explicitly unavailable.

Validation on 2026-09-08: **278 tests passed** in the complete suite, including
local Aer circuit replay, fake-target layout checks, interruption recovery,
receipt/shot validation, and the independent numerical oracles. All 819 historical
histogram statistics agree with the earlier analysis to floating-point precision;
all 97 raw files retain their original paths and SHA-256 hashes. Dependency and
diff checks pass. The LaTeX comment cleanup preserves the rendered manuscript
text exactly: both versions build to 12 pages without warnings.

Remaining work, in order:

1. Select the account/backend, prepare and inspect the two hardware campaigns,
   then collect the bounded repeats/scaling cohort using the commands above.
2. Assess receiver asymmetry, control/layout differences and repeat variation.
   Plan finer delay sampling or component ablations only if the evidence calls
   for them. Preserve negative or inconclusive conclusions.
3. Collect independent simulation convergence repetitions with explicit seeds and
   saved raw errors: `python scripts/generate_figures.py --collect-convergence`.
   This is **new data collection**, separate from figure regeneration. `--quick`
   reduces the development collection. The current fit is descriptive; estimate
   exponent uncertainty across independent repetitions before restoring the
   manuscript's empirical convergence claim.
4. Review and pin selected new data, regenerate supported figures, and update the
   manuscript. Conditional shot intervals do not replace repetition-based uncertainty.
5. Confirm the complete author/affiliation details, finalize the archive deposit
   and DOI, then perform final manuscript/artifact checks and release packaging.

Keep generic resource preparation and Gram–Schmidt decoding. Structured resource
preparation, a structured Clifford decoder, streaming/logical-frame simulation
tiers, and dynamical-decoupling ablations are closed scope decisions, not outstanding
implementation commitments.

Build the manuscript after regenerating its selected figures:

```bash
cd manuscript
pdflatex -interaction=nonstopmode apstemplate.tex
bibtex apstemplate
pdflatex -interaction=nonstopmode apstemplate.tex
pdflatex -interaction=nonstopmode apstemplate.tex
```

The compiled PDF is a local preview; the source and embedded figure PDFs are
versioned. Before release, run the complete tests and inspect the final PDF.
