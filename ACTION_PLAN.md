# Action Plan — Revision 8, 2026-09-08

This is the current completion checklist following
[the correctness review](REVIEW_2026-09-08.md). It supersedes the retrospective
status claims in [revisions 1–7](docs/action_plan_history_2026-09-08.md).

**Authorized stopping point:** complete code corrections, analytical/manuscript
work, figure corrections, and reanalysis of existing records; stop before any new
experiment collection. Local regression tests and synthetic validation are allowed.
New convergence samples, hardware repeats, and HPC experiments are not being run.

**Current status:** sections 1–4 are completed and locally verified. Work has stopped
at section 5, before new experiment collection. Sections 5–6 remain deferred.

## Data preservation

- Never overwrite, delete, rename, or silently repair historical files in `results/`,
  including `legacy/` and `qec513/`. Preserve them as the source evidence.
- Keep any historical provenance overrides explicit and evidence-backed in analysis
  files. Write reanalysis outputs separately from the raw records.
- Serialization/HPC changes affect newly created records only. Validate changes on
  throwaway local/scratch outputs before operational use.
- Do not submit IBM/SLURM jobs or regenerate experimental datasets during this phase.

## Already verified before this revision

- [x] Correct recovery Kraus map, logical-error polynomial, and crossover.
- [x] All 15 weight-one Pauli errors corrected; recovery trace preservation.
- [x] Independent binary-symplectic oracle enumerating all 1,024 Pauli patterns
  (`tests/test_qec_recovery.py`); former item 49 is completed.
- [x] Endpoint tests `p_L(1)=22/27` and `F_QEC(1)=37/81`.
- [x] Shared logical basis and native-qudit/binary representation tests.
- [x] Linear bitwise feedforward and general real-alpha fidelity rotation.
- [x] Registered `slow` marker. Baseline full suite: 133 passed.
- [x] Existing saved data parsed and counts/fidelities checked in the review.

## 1. Execution, configuration, and provenance — completed locally

- [x] Use effective sample count/seed consistently in execution and saved records;
  make precedence across config, backend, notebook, and CLI explicit.
- [x] Publish result files atomically without replacing existing paths; retain unique
  suffixes for repeated saves within one SLURM task.
- [x] Read the actual sender register and preserve shot-aligned classical outputs.
- [x] Record code/dependency identity, circuit/configuration settings, compiled layout,
  operations/depth/timing, backend dt, and available calibration for new runs.
- [x] Validate alpha and delays before submission; retain once-per-theta compilation
  on compatible targets and handle timing-constrained targets explicitly.
- [x] Preserve arbitrary HPC probability lists and shell-safe command arguments.
- [x] Merge only matching experiments, validating array completeness and grid identity.
- [x] Isolate code per SLURM submission and test the workflow using temporary outputs.
- [x] Preserve a tested dependency snapshot (`requirements-tested.txt`).

## 2. Numerical contracts and analytical manuscript — completed

- [x] Consolidate production stabilizer labels while keeping the independent oracle
  separate; reject unlabeled coherent multi-syndrome recovery inputs.
- [x] Explain arbitrary-M,N factorization for the stated independent phase-covariant
  channels, sender-branch invariance, and product global fidelity.
- [x] Explain the p > 3/4 state-inversion regime without calling it a second
  fault-tolerance threshold.
- [x] Correct privacy: the classical transcript is phase-independent; receiver
  quantum states carry the aggregate phase.
- [x] Describe retained trajectory-list/decoded-density memory and actual dense
  operations; remove unsupported runtime/memory measurements and scalar-only claims.
- [x] Attribute independent validation to the independent test oracle.
- [x] Distinguish integrated library/simulation support from the standalone QEC memory
  experiment actually benchmarked on hardware; qualify physical-noise conclusions.
- [x] Document bitwise correction, invalid outcomes, decoder ordering, and scheduling.

## 3. Analysis and figures from existing records — completed

- [x] Fix convergence seeds and notebook integration API, but leave new convergence
  collection disabled. Remove invalid multi-seed figure/claims from the manuscript.
- [x] Fix periodicity imports, record selection, frequency/PSD units, and dt handling.
- [x] Add explicit figure source/output manifest, input grid checks, historical-unit
  provenance, and accurate backend/shots/optimization/circuit labels.
- [x] Regenerate supported existing-data figures; fix the QEC memory filename and
  crossover inset/caption mismatch. Do not guess missing encoding flags.
- [x] Analyze every suitable existing hardware run for local/global/worst fidelity,
  covariance and asymmetry with shot uncertainty, preserving theta/job distinctions.
- [x] Quantify delay traces with documented limitations; do not infer a physical
  correlated-noise mechanism or confirmed periodic process from these summaries.
- [x] Update manuscript captions and measured statements to the derived artifacts.

## 4. Integration and stopping check — completed

- [x] Update README with effective configuration, safe HPC/reanalysis commands, tested
  environment, and the boundary between regeneration and new collection.
- [x] Run focused regressions, then the full test suite; verify notebooks without
  enabling experiment cells; run figure/reanalysis tools using saved records.
- [x] Build and visually inspect the manuscript; resolve actionable layout warnings.
- [x] Verify every historical result file retains its original checksum and no new
  experiment records or remote jobs were created.
- [x] Reconcile this checklist with final test evidence and state exactly what remains.

## Completion evidence

- Final complete suite: **230 passed** (266.47 s with BLAS/OpenMP threads limited
  to one). An earlier full run passed 226 tests before the final four spectral
  edge cases were added; the final run includes them.
- Independent factorization tests cover all sender branches in several small systems,
  unequal depolarizing noise and amplitude damping. The independent QEC oracle
  remains separate from consolidated production constants.
- Analysis/plot/notebook checks cover effective seeds/counts with mocked collection,
  saved-source integrity, unit conversion, optional analysis execution, and rejection
  of constant/linear-only spectral peaks. No new convergence samples were collected.
- Existing-data analysis covers **16 broadcasting jobs / 819 per-theta, per-delay
  histograms and 5 unique memory jobs**. See [the report](analysis/hardware/report.md),
  [machine-readable summaries](analysis/hardware/summary.json), and
  [all point estimates](analysis/hardware/points.json).
- [Figure sources](figures/sources.json) pin 25 source records with SHA-256 hashes
  and historical attribution. Supported figures were regenerated; the three
  invalid convergence images are preserved in [the withdrawn archive](figures/withdrawn/README.md).
- Manuscript: complete LaTeX/BibTeX build, **12 pages, zero warnings and no
  overfull/underfull boxes**, with every page visually inspected. Workspace preview:
  [manuscript/apstemplate.pdf](manuscript/apstemplate.pdf). Generated vector figure
  PDFs are included as source artifacts; the compiled preview remains gitignored.
- `pip check` and `git diff --check` pass. The tested environment is recorded in
  [requirements-tested.txt](requirements-tested.txt).
- All **97 original result JSON files retain identical paths and SHA-256 hashes**;
  no new raw experimental records were added and no IBM/SLURM jobs were submitted.
- HPC validation used actual local CLI tasks, rsync/flock, immutable source snapshots,
  and complete-grid merging in throwaway directories. Live cluster/IBM execution
  remains untested. Cached calibration timestamps or dynamic-circuit duration
  estimates that are unavailable are recorded as unavailable rather than invented.

## 5. New data — deferred at the user's stopping point

1. Collect independent convergence repetitions with saved seeds, sample counts, raw
   errors; estimate exponent uncertainty across independent repetitions before
   restoring an empirical convergence figure. The prepared collector currently
   labels its fit as descriptive rather than reporting an OLS confidence interval.
2. Collect bounded repeated delay sweeps to assess receiver asymmetry/run variation,
   with settings interleaved or randomized where supported and order archived.
3. Collect a controlled scaling cohort on one backend with fixed documented settings.
4. If needed, ablate components of the retained generic circuit to localize loss;
   do not revive rejected structured designs by default.
5. Save full execution/circuit/calibration provenance and aligned classical outputs
   for every new hardware run. Validate on cluster scratch before operational reuse.

Reanalyze new data and finalize the associated manuscript evidence after collection.

## 6. Release — after data and author decisions

- Resolve coauthor/affiliation details with the authors; do not invent identities.
- Finalize the archive deposit/DOI once the final data and code are ready.
- Complete final manuscript/artifact checks and release packaging.

## Closed scope decisions

Keep generic resource preparation and the Gram–Schmidt decoder. Structured resource
preparation, a structured Clifford decoder, extra logical-frame/streaming simulation
tiers, and DD ablations are not remaining implementation commitments. The manuscript
must describe the retained implementation and its limitations accurately.
