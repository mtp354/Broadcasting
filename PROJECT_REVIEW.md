**Project review — 8 September 2026**

Reviewed revision `1912be1`, the complete critique and action plan, the LaTeX manuscript, library, tests, notebooks, result schemas and saved data, and HPC workflow. This is an assessment and recommended revision sequence; it does not implement the recommendations.

The corrected five-qubit recovery and logical-channel polynomial are sound. The project has a useful separation between numerical simulation, hardware circuits, and experiment workflows. However, Phases 0–1 are only partially complete, the manuscript now describes several unfinished methods as completed, and hardware measurement, result provenance, and figure selection need correctness fixes before additional experiments.

**Project structure and execution flow**

| Location | Responsibility and important boundaries |
|---|---|
| `broadcasting/protocol.py`, `backend.py` | Configuration/result dataclasses and exact, trajectory-sampling, and IBM hardware execution. Simulation backends sweep a common physical error probability; hardware returns one point or a delay sweep. |
| `broadcasting/simulation.py` | Native sender-qudit numerical representation: resource state → receiver noise → ideal recovery/decoding when encoded → sender phases → Fourier measurement → correction → receiver reductions/fidelities. Uses NumPy and Qiskit quantum-information objects, not Aer execution. |
| `state_preparation.py`, `circuit.py`, `qec_513.py`, `fidelity.py`, `helpers.py` | Binary sender encoding and Qiskit little-endian circuit representation; state loading, receiver delays, dynamic QEC and sender feedforward, target-basis readout. Distinct from the native-qudit numerical representation. |
| `results.py`, `plotting.py`, `scripts/migrate_results.py` | Unified main-run JSON storage, legacy compatibility views, migration, and plotting. QEC memory-benchmark files use a separate schema. |
| `run_broadcast.ipynb` | Main execution interface, saving, exact/sampling comparisons, convergence experiment. |
| `visualizations.ipynb` | Saved-run selection, scaling and crossover figures, optional expensive receiver-pair exploration. |
| `qec_testing.ipynb` | Standalone encoded-memory benchmark; this is a different experiment from full broadcasting. |
| `hpc/` | CLI and SLURM execution, scratch setup, synchronization, backup and retrieval. Paths are specific to the current cluster account. |
| `tests/` | State construction, circuit/QEC behavior, numerical simulation, backends, plotting, and the newly added recovery tests. |
| `results/`, `results/legacy/`, `results/qec513/` | 45 main run files, archived pre-migration records, and 6 standalone memory-benchmark files. Main records comprise 32 simulations and 13 hardware runs. |
| `manuscript/`, `figures/`, `docs/` | Current manuscript and bibliography, duplicated/generated PNG assets, and supporting PDF documents. Figure provenance is not yet explicit. |

The two state representations are reasonable. They need a documented conversion/order contract and cross-representation tests; a wholesale architectural rewrite is unnecessary.

**What has actually been implemented**

| Action-plan component | Assessed status |
|---|---|
| Exact `p_L(p)`, low-noise crossover, corrected recovery equation | Implemented and validated. |
| Tracked Pauli labels and direct syndrome recovery | Implemented correctly for the supported Pauli trajectories. The backward-compatible `argmax` fallback warns but remains unsafe for general trajectories. |
| Weight-one correction, trace preservation, polynomial and pipeline tests | Implemented and passing. Trace preservation is tested on the entire 32-dimensional block, stronger than the plan's “on the codespace” wording. Broader independent/channel tests are still desirable. |
| General arbitrary-`M,N` factorization proposition and full product output | Missing from the manuscript; it still gives the specific `M=1,N=2` derivation. |
| Enumerator derivation/table and fully independent code oracle | Partial. Coefficients are displayed, but the derivation/table is absent and the code oracle shares production recovery helpers. |
| Explanation of `p=3/4` | Partial. The equal-fidelity point is mentioned; the negative-contraction regime is not explained. |
| Monte Carlo cost accounting and measurements | Partial. Decoded density accumulation is now acknowledged, but retained encoded trajectories are omitted and no measured timing/memory report is present. |
| Items 10–12: logical-channel fast path, scalar-only accumulation, exact sender-branch sum | Unimplemented, correctly identified as deferred in the detailed Phase 1 notes. They need an explicit next work package. |
| Title-free plotting/export | Helpers, defaults, and current notebook save calls are implemented; several actual manuscript figures still contain titles. |
| Remaining Phase 2 analysis/plots and Phases 3–6 | Mostly pending. Existing generic hardware circuits are the baseline, not completion of the structured redesign. |
| Release | Pending, appropriately last. |

The opening “Phase 0 and Phase 1 are complete” statement and Phase 0 “DONE” label should be changed. The opening also incorrectly groups Phase 5 with new data collection, although Phase 5 is a circuit-development prerequisite.

**Correctness findings, in priority order**

1. **Correct the manuscript's claims of completed work.** At `manuscript/apstemplate.tex:411`, scalar-only accumulation is presented as available even though the implementation always builds the decoded density matrix. At line 415, measured peak memory/wall-clock results and a fitted convergence exponent are asserted without an accompanying implementation or report. The current convergence notebook uses a single seed, samples 50–10,000, and overlays a first-point-normalized reference without fitting (`run_broadcast.ipynb:265`). The included older figure extends to 100,000, so it also needs its own source/configuration restored. Remove unsupported completion claims now or supply the actual methods/results; do not treat a planned feature as evidence.

2. **Fix hardware fidelity for the accepted amplitude range.** `HardwareBackend` prepares `config.alpha` but `add_fidelity` always measures an equatorial target (`backend.py:202`, `backend.py:287`, `fidelity.py:60`). Ideal Aer reproduction with `M=N=1`, sender phase 0.3, and 4,096 shots gave about 0.492 for `alpha=0` or `1`, and about 0.775 for `alpha=0.3`; the actual noiseless protocol fidelity is 1. The equatorial default gives 1 correctly. Either construct the inverse rotation from the actual target state or explicitly validate/restrict hardware inputs to the supported family. The existing equatorial hardware results are not invalidated by this particular bug. Add non-equatorial and endpoint readout tests.

3. **Make execution settings authoritative in saved results.** `results.py:80` treats any truthy `config.n_samples` as evidence of sampling, although `ProtocolConfig.n_samples` defaults to 200. An exact run with the default config therefore saves as `aer_sampling`. A reproduced run using `SamplingBackend(n_samples=37, seed=314)` saved 200 samples and a null seed because the serializer preferred config defaults over executed settings. Resolve settings once, record effective mode/sample count/seed, and serialize those values. Save fixed or selected sender outcomes too. Add round-trip tests for exact and sampling runs, not only hardware sweeps. Existing JSON labels cannot always be repaired from the curves alone; preserve unknown provenance rather than inventing it. Eventually use accurate numerical-backend labels instead of `aer_exact`/`aer_sampling`, with compatibility handling for old records.

4. **Prevent result overwrites before parallel HPC runs.** Default filenames have only second resolution (`results.py:49`) and are opened with `"w"` (line 144). SLURM array tasks share the output directory. Two completions in the same second can silently overwrite a result. Use unique run/job/task identifiers and atomic, collision-safe writes. Give each batch an immutable code snapshot rather than rsyncing changing code into the shared executing directory from every task.

5. **Repair figure provenance and hardware cohort selection.** The scaling caption says IBM Kingston with 10,000 shots (`manuscript/apstemplate.tex:543`), while the available larger-size records are predominantly Marrakesh/Fez with 4,096 shots. The plotting cell pools hardware runs across backends and optimization settings (`visualizations.ipynb:171`). It also labels the nearest delay as zero without checking that the value actually is zero or that the sweep is a delay sweep. The repository does not support the caption as written. Identify each plotted record explicitly, correct the caption, and stratify comparisons by backend/settings. Do not infer controlled size scaling from a mixed cohort. This is a correctness task ahead of color or axis styling.

6. **Correct Monte Carlo memory accounting and independence language.** Sampling retains all encoded vectors before decoding (`simulation.py:517`, `simulation.py:539`), giving storage of order `n_s D + d_dec²`, in addition to working buffers; it is not a streaming `D + d_dec²` implementation. A bounded `M=N=2`, 1,000-trajectory probe retained 147,456,000 bytes in trajectory arrays alone. `return_density_estimate=True` additionally allocates an encoded `D×D` estimate. The bare exact channel also uses full dense matrix products (`simulation.py:162`), so its present per-term work is cubic in `D`; quadratic local contractions are possible but are not what that function currently does. Measure actual peak process memory and elapsed time in isolated runs. The brute-force oracle calls the same recovery builder and syndrome helper as production (`simulation.py:673`, `simulation.py:693`), contradicting the manuscript's independence claim at line 361. It independently checks the polynomial, but is not an independent recovery implementation.

7. **Complete the general analytical result and qualify its assumptions.** State the full noiseless output `|psi_Phi>^⊗N`, and prove factorization for independent depolarizing receiver channels with ideal sender operations, correction, and (when present) QEC. For possibly unequal receiver probabilities,

   `rho_out = tensor_l D_(p_l)(|psi_Phi><psi_Phi|)`;
   `F_l = 1 - 2 p_l/3`;
   `F_global = product_l (1 - 2 p_l/3)`.

   Replace `p_l` by `p_L(p_l)` for ideal block QEC. Covariance under the correction unitary is the necessary argument; diagonality alone does not establish it (`manuscript/apstemplate.tex:230`). Explain `eta<0` for `p>3/4`: QEC is advantageous again in that convention, so describe `p_star` as the low-noise break-even point, not the only equality/advantage boundary on `[0,1]`. This is an ideal single-block break-even calculation, not a fault-tolerant threshold theorem.

8. **Narrow the unresolved experimental and security claims now.** The abstract, results, and conclusion still infer physical correlated noise from declining local fidelity (`manuscript/apstemplate.tex:100`, `:536`, `:553`). Independent gate/readout/idle errors accumulating in larger circuits can produce that behavior. The DD attribution at lines 421 and 533 lacks an explicit implemented sequence or archived schedule. The QEC experiment establishes performance of this particular non-fault-tolerant, generically synthesized memory circuit, not a general hardware limitation or a full QEC-broadcasting demonstration. These are already recognized in Phase 3; move the wording corrections ahead of plotting polish. Similarly, explain restricted remote preparation without “circumventing” the no-go theorems. State that ideal correction messages are phase-independent and the receiver state depends on the aggregate phase; this is not a full confidentiality or cryptographic-security claim.

9. **Make delay units, uncertainty, and old benchmark labels auditable.** All three notebooks hardcode `0.004` microseconds per `dt`, but no main-run backend metadata preserves `dt`. Installed device snapshots give that value for Fez/Marrakesh and `0.0005` for Brisbane, the main notebook's configured backend. The current plotting path would mis-scale a Brisbane delay axis by eight. Record the actual backend `dt` and use it for conversion; retain `dt` units if historical calibration cannot be established. The older delay plotting helper averages shot standard errors rather than propagating the mean correctly (`plotting.py:149`) and assumes independent receivers for the average (`:157`); the current `plot_run_sweep` does not show uncertainty at all. Derive uncertainty from per-shot joint outcomes and keep shot noise separate from between-job drift. All six legacy QEC benchmark files lack `use_qec`, while the comparison cell defaults missing values to true (`qec_testing.ipynb:260`). Two files, ending `163257` and `163539`, share the same job and identical results. Reconstruct labels from evidence and deduplicate by experiment/job identity; do not count duplicates as repetitions.

10. **Harden recovery and input contracts without expanding the noise model.** The standard tracked-Pauli path is correct. For unlabeled trajectories, require concentration in a single syndrome or reject unsupported inputs instead of warning and returning a general `argmax` answer (`simulation.py:789`). Validate label/trajectory counts and positive sample counts. The numerical public interface uses real `alpha` with `beta=sqrt(1-alpha²)`, whereas circuit preparation accepts complex `alpha` and uses its modulus. Document that convention or make it consistent; arbitrary complex amplitudes claimed in the manuscript are not the current end-to-end API. The exact sender-branch sum remains worth implementing, but the current conditional result is correct and branch-independent for the exact depolarizing model, so this omission does not invalidate the verified polynomial curves.

**Specific changes needed to the action plan**

- **Phase 0:** Reopen the factorization, full-output, enumerator-table, and channel-range explanations. Keep the correct polynomial and recovery repairs marked complete. Add an independent symplectic or stabilizer-coset enumerator and tests of the complete logical channel, not only one scalar fidelity.
- **Phase 1:** Mark resource accounting partial. Give items 10–12 an explicit follow-up stage before larger simulations. The logical-channel exact path should be the normal tool for this independent Pauli model; retain physical encoded propagation as a small-system reference. Prove/test exact branch invariance and use the analytical output in the normal path; reserve explicit weighted sender-branch sums for the small reference calculation or finite-trajectory estimator instead of introducing unnecessary exponential work. Stream physical trajectories if that path is retained for scaling experiments. Compute scalar fidelity after accounting for sender measurement/correction, not by averaging independently normalized conditional branches with arbitrary equal weights.
- **Phase 2:** Add dataset validation, comparable cohort selection, uncertainty, duplicate detection, delay-unit validation, and a manuscript figure manifest. Every figure should name its generator, input run IDs, configuration, output path, and caption facts. Use one authoritative asset location: current exports `sampling_convergence.png`, `qec_crossover.png`, and `hardware_tau0_scaling.png` do not replace the differently named files included by the manuscript. Actual Figures 1, 4, and 6 still visibly contain titles. For convergence, the existing `errors[0]*sqrt(n0)/sqrt(n)` formula is algebraically correct as a first-point reference; it does not establish the exponent. Use repeated seeds, log-log analysis and a fitted slope with uncertainty.
- **Phase 3:** Correct unsupported claims immediately, then finish the technical copyedit. Allow the periodicity conclusion to be negative/inconclusive. Add the prior-art comparison from critique §2.1, which the plan omitted: Kumar–Pathak already analyze noise and report an IBM proof of principle. Explain the distinctive resource family, exact QEC analysis, and controlled implementation contribution. [Primary paper](https://arxiv.org/abs/2305.00389)
- **Phase 4:** Remove the proposed Sampler `resilience_level` knob. It exists for Estimator, not this project's SamplerV2 path; this was checked in installed Runtime 0.42.0 and IBM documentation. Explain optimization versus mitigation accurately without inventing an unsupported option. [Sampler guidance](https://quantum.cloud.ibm.com/docs/en/guides/sampler-rest-api) If DD experiments remain useful, implement explicitly scheduled DD using a version-compatible dynamic-circuit path. Runtime's built-in DD option is documented as incompatible with dynamic circuits; the separately compiled Runtime scheduling passes support them. [Feature compatibility](https://quantum.cloud.ibm.com/docs/en/guides/sampler-options), [Runtime 0.42 DD pass](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/0.42/transpiler-passes-scheduling-pad-dynamical-decoupling) Removing the unsupported attribution is sufficient for the present manuscript; a large DD campaign need not become mandatory.
- **Phase 5:** Specify that the sender register stores the number of receiver **zeros**, `k=N-popcount(receiver_bits)`, to match the existing resource state and phase convention. “Compute Hamming weight” without this qualification risks implementing a different protocol. Validate structured preparation against the existing statevector on asymmetric/non-equatorial inputs. For feedforward, exploit additive commuting phases through per-sender or per-bit conditions; per-bit rotations need `M ceil(log2(N+1))` conditions and avoid an assumed hardware modular-arithmetic accumulator. Explicitly preserve or revise the invalid-outcome policy. IBM documents restrictions on classical arithmetic in dynamic circuits. [Dynamic-circuit execution](https://quantum.cloud.ibm.com/docs/en/guides/execute-dynamic-circuits) Validate the structured Clifford encoder/decoder against the existing codespace mapping and all single errors before comparing gate counts.
- **Before Phase 6:** Fix metadata and collision risks; save compiled-circuit identity, code revision, dependency versions, layout, transpiler seed, timing, calibration snapshot and full shot-aligned classical outputs. Present code saves only the receiver fidelity register, dropping sender/syndrome data (`backend.py:225`, `:324`), so existing JSON cannot recover invalid sender frequencies. Current behavior for an invalid sender value is no matching feedforward branch and therefore no correction, not rejection. Fix layout/compilation for paired sweeps where scheduling permits, record any remaining differences, and interleave/randomize delay settings to separate delay effects from drift.
- **Phase 6:** Move existing-count global fidelity/covariance and receiver-spread analysis earlier. Reserve new collection for missing registers, repetition, larger sizes, and controlled circuit/noise comparisons. The objective is to determine whether receiver asymmetry is statistical or reproducible, not to force the two lines to coincide. Make the experimental matrix bounded: a few representative sizes, selected component ablations, and the DD study only if the exploratory evidence warrants it.
- **Phase 7:** Keep Zenodo last. Do reproducibility bookkeeping and build automation earlier so the final deposit is a packaging task.

A practical sequence is: correct manuscript/status claims and concrete data/API bugs → finish analytical and independent validation work → implement the small logical-channel path → reanalyze existing records and rebuild figures → validate structured circuits and optional DD → collect the bounded missing experiments → finalize manuscript and release.

**Useful analysis already available without new hardware**

All 13 main hardware runs retain joint receiver strings, and their saved local fidelities agree exactly with recomputation from those counts. Those strings support all-zero/global fidelity and success-indicator covariance within each theta/run/delay stratum. For `run_20260518_120232.json` at zero delay (Kingston, optimization 3, 10,000 shots):

| Quantity | Recomputed value |
|---|---:|
| Mean local fidelity | 0.9099 |
| Worst receiver fidelity | 0.8941 |
| Global/all-zero fidelity | 0.8493 |
| Product of local fidelities | 0.827671 |
| Receiver success-indicator covariance | 0.021629 |

These are descriptive statistics of the final target-basis readout. They do not identify the physical source of correlations; shared preparation/feedforward errors, readout effects, and drift still require controls. Pooling different theta settings or jobs can itself introduce covariance, so analyze those strata separately before aggregation.

**Validation and its limits**

- Full project environment: **92 tests passed**, one warning for the unregistered `slow` marker, in 112 seconds. Environment: Qiskit 2.2.1, Aer 0.17.2, Runtime 0.42.0, NumPy 2.3.3. The system environment also passed 81 tests with one Aer-dependent module skipped; the full environment is the relevant hardware-circuit check.
- An independent binary-symplectic classification of all 1,024 physical Pauli patterns, built separately from production recovery/syndrome helpers, agreed with every production recovered logical map. The resulting counts are:

| Physical weight | Logical I | Logical X | Logical Y | Logical Z | Total nonidentity |
|---:|---:|---:|---:|---:|---:|
| 0 | 1 | 0 | 0 | 0 | 0 |
| 1 | 15 | 0 | 0 | 0 | 0 |
| 2 | 0 | 30 | 30 | 30 | 90 |
| 3 | 60 | 70 | 70 | 70 | 210 |
| 4 | 135 | 90 | 90 | 90 | 270 |
| 5 | 45 | 66 | 66 | 66 | 198 |

  This verifies isotropy as well as the polynomial. The audit script is temporarily available at `/tmp/broadcasting_qec_audit.py`; a maintained, appropriately scoped version belongs in the test suite in the follow-up implementation.
- 150 small exact encoded cases, including two sender sizes, endpoint/negative amplitudes, `p=3/4` and `p=1`, and all sender outcomes, matched the analytical fidelities to within `8e-9`. An unencoded two-sender/two-receiver case with unequal channel probabilities matched the full factorized density matrix in all nine branches to about `1.2e-16`.
- All 15 injected weight-one Pauli errors were also corrected by the actual dynamic memory-benchmark circuit in ideal Aer, with unit measured fidelity in each 32-shot deterministic test. This supports the current syndrome/qubit-order mapping. It does not characterize noisy-hardware performance.
- All eight saved exact simulation runs agree with the applicable analytical fidelity to within about `8.1e-9`. This supports retaining those numerical results rather than assuming the manuscript-equation error corrupted every dataset.
- The manuscript builds successfully with bibliography when invoked from `manuscript/`. The final log has no unresolved citations/references but retains overfull-box and stuck-float warnings. Visual inspection of the methods/results pages confirms old titled figures and small figure labels. Build outputs were kept in `/tmp`; no manuscript source was changed.
- No new hardware jobs were submitted. Historical hardware schedules/layouts/calibrations were not available in the saved records, so their physical noise mechanisms and complete provenance cannot be reconstructed from this checkout alone.

**Broader improvements within the current scope**

1. Add a short README with architecture, environment setup, one small simulation command, tests, manuscript build command, and the distinction between broadcasting and standalone memory experiments. Pin a tested dependency set and record versions with runs; register the existing `slow` marker and separate expensive integration checks from quick mathematical tests.
2. Make one configuration source authoritative across notebooks, CLI, backend and serializer. The CLI currently defaults to `alpha=1/sqrt(N+1)` while the main notebook/dataclass use `1/sqrt(2)`; neither is intrinsically invalid, but they describe different experiments. Clarify the two meanings of `p_list` (sweep points at backend level versus per-receiver probabilities in low-level functions), result array shape, and whether reduced states describe only the last sweep point. Add modest validation rather than a large framework.
3. Consolidate duplicated logical-basis/stabilizer definitions carefully, retaining independent test oracles and explicit native-qudit/little-endian conversion tests. Keep the exact physical implementation available for small cross-checks while using the analytical/logical implementation for large parameter sweeps.
4. Use a small reproducible figure-generation script driven by explicit saved run IDs. Store figure-ready statistics and uncertainties, and let captions inherit backend/shots/settings from the manifest. Prefer vector output for plots, readable labels at column width, and no embedded titles. This is more valuable than additional exploratory notebook cells.
5. Finish the existing copyedit queue: original no-broadcasting reference, inappropriate device/self-testing citations, explicit qubit ordering, privacy scope, stale crossover explanation, and placeholders. Also correct the sender-unitary equation to an active block plus identity on unused levels (`apstemplate.tex:444`), the reference to an unencoded schematic as illustrating QEC (`:468`), and equalities that silently discard global phase.
6. Center the paper on the general factorization result, independently verified logical channel, and controlled limits of the selected implementation. Broader non-Pauli models, a general cryptographic security proof, a new QEC code, or an extensive hardware-noise characterization project are unnecessary to complete this plan.

---

**Section 2: Comprehensive Technical Diagnoses, Critical Gap Analysis, and Unified Implementation Roadmap**

**1. Critical Audit of Section 1 and the Action Plan**

**1.1 Verified Strengths of Section 1:**
The findings in Section 1 correctly isolate several critical defects that must be resolved prior to publication:
- The algebraic reconciliation of the $[[5,1,3]]$ recovery map $K_s = V_{\text{Dec}} E_s^\dagger P_s$ and the closed-form logical polynomial $p_L(p) = 10p^2 - \frac{200}{9}p^3 + \frac{160}{9}p^4 - \frac{128}{27}p^5$ with low-noise break-even $p_* = \frac{3-\sqrt{6}}{4} \approx 0.137628$ is mathematically rigorous and fully validated against the 1,024 physical Pauli error configurations.
- The diagnostic identifying that `results.py:80` treats any truthy `config.n_samples` as evidence of Monte Carlo sampling is exact: because `ProtocolConfig.n_samples` defaults to `200`, every unconfigured `ExactBackend` execution is mislabeled and saved as `aer_sampling`.
- The critique of `fidelity.py:60` and `backend.py:202` is exact: the fidelity measurement circuit assumes an equatorial target state ($\alpha = \beta = 1/\sqrt{2}$), causing silent fidelity under-reporting ($\sim 0.5$ for computational basis endpoints) when non-equatorial states are supplied.
- The identification of the cohort mismatch in Figure 6 is exact: the manuscript caption claims data from IBM Kingston with 10,000 shots, whereas the repository contains only $M=1, N=2$ on Kingston; all points for $N \ge 3$ originate from IBM Marrakesh and IBM Fez with 4,096 shots.

**1.2 Gaps, Blind Spots, and Unresolved Nuances in Section 1:**
While Section 1 correctly identifies symptoms, it leaves several foundational mechanisms unanalyzed or incomplete:
- *Underlying Algebraic Reason for Branch Invariance:* Section 1 notes that the current conditional simulation result does not corrupt verified curves, but fails to explain *why*. As proven in Section 2.2 below, under any phase-covariant channel (including depolarizing and dephasing noise), every sender measurement branch $\bar{n} \in \{0, \dots, N\}^M$ yields the identical post-correction receiver state $\bigotimes_{\ell=1}^N \mathcal{D}_{p_\ell}(|\psi_{\text{target}}\rangle\langle\psi_{\text{target}}|)$. Consequently, simulating a single fixed outcome (e.g. $\bar{n}=\vec{0}$) is not an approximation—it is algebraically exact.
- *Unquantified Gate Synthesis Penalty:* Section 1 notes that `qc.initialize` and Gram-Schmidt decoding are "generic," but does not quantify their circuit cost. Generic isometry synthesis via Qiskit's `Initialize` on 4–6 qubits requires 30–60+ CNOT gates, while structured Dicke preparation requires $\le 6$ CNOTs. Similarly, a $32 \times 32$ generic unitary produces $\sim 200+$ CNOTs via Quantum Shannon Decomposition, whereas a Clifford $[[5,1,3]]$ decoder requires only 8–10 CNOTs. This unquantified overhead is the sole reason hardware fidelity collapses at $\tau=0$, not multipartite entanglement fragility.
- *The Fig. 3 Text-Figure Disconnect:* Section 1 overlooked a major contradiction in the manuscript text: line 468 explicitly states that Fig. 3 illustrates the 3-stage dynamic $[[5,1,3]]$ QEC circuit (ancilla measurement, syndrome decoding, and feedforward), but Fig. 3 is actually an unencoded schematic showing only the bare $M=1, N=2$ protocol without ancillas or QEC blocks.
- *Missing SLURM Array Reduction Pipeline:* Section 1 highlights timestamp collision risks in HPC filenames, but does not address the workflow gap: `hpc/slurm_broadcast.sh` runs array tasks that compute single $p$-points, creating 50 disconnected JSON files. The project lacks any merge utility to assemble these into a sweep record for plotting.

**1.3 Critical Deficiencies in ACTION_PLAN.md:**
`ACTION_PLAN.md` contains several technical errors and untenable status assertions:
- *Premature Completion Status:* The plan marks Phase 0 as "DONE", yet items 2 (general $M, N$ factorization proposition), 3 ($p=3/4$ anti-contraction explanation), and 4 (full multi-receiver noiseless state) are absent from `apstemplate.tex`. The plan marks Phase 1 core items as "DONE", yet the Monte Carlo text in the manuscript claims non-existent features (measured memory/runtime reports, scalar-only accumulation, and fitted convergence exponents).
- *Non-Existent Runtime Options (Phase 4, Item 18):* The plan proposes exposing a `resilience_level` parameter for IBM hardware runs. In Qiskit Runtime 0.42.0+, `resilience_level` applies exclusively to `EstimatorV2` (for expectation values and error mitigation like ZNE/TREX). `SamplerV2` (used by `HardwareBackend` for shot counts and quasi-distributions) rejects `resilience_level`. Attempting to pass it raises a `ValueError`.
- *Unchecked Classical Arithmetic on Dynamic Circuits (Phase 5, Item 25):* The plan suggests replacing $(N+1)^M$ branches with real-time classical evaluation of $\sum_j n_j \bmod (N+1)$. IBM hardware OpenQASM 3 runtimes enforce strict limits on classical expressions; runtime modulo arithmetic across classical registers is unsupported or unstable. As derived below, the correct physical solution is to factor the phase correction into $M \cdot \lceil \log_2(N+1) \rceil$ bit-conditional phase rotations, eliminating arithmetic completely.
- *Omission of Essential Prior Art:* The plan omits critique §2.1 regarding Kumar & Pathak (2024), who already demonstrated noise modeling and IBM hardware execution of remote state preparation. Without directly differentiating the resource structure and QEC integration from this prior work, the manuscript faces immediate rejection for lack of novelty.

---

**2. Mathematical & Analytical Foundations: Exact Proofs and Theoretical Refinements**

**2.1 Complete Proof of General $(M, N)$ Noise Factorization:**
The manuscript must replace the restricted $M=1, N=2$ calculation with the general theorem.

*Theorem (Noise Factorization and Local Marginals):*
Consider $M$ senders and $N$ receivers initialized in the generalized resource state:
$$\ket{\Psi^{(M,N)}} = \sum_{k=0}^N \alpha^k \beta^{N-k} \binom{N}{k}^{1/2} \left( \bigotimes_{j=1}^M \ket{k}_{a_j} \right) \ket{k; N-k}_B,$$
where $\ket{k; N-k}_B = \binom{N}{k}^{-1/2} \sum_{z \in \{0,1\}^N, |z|=N-k} \ket{z}$ is the Dicke state with $k$ zeros and $N-k$ ones.
Let each sender apply $U_{a_j}(\theta_j)\ket{k} = e^{i(2k-N)\theta_j}\ket{k}$, and let each receiver link experience an independent channel $\mathcal{E}_\ell$. If each $\mathcal{E}_\ell$ is covariant under the single-qubit phase rotation $U_{\bar{n}} = \text{diag}(e^{i\phi_{\bar{n}}}, 1)$, then for any sender outcome $\bar{n} = (n_1, \dots, n_M) \in \{0, \dots, N\}^M$:
1. The classical measurement outcomes are uniformly distributed: $P(\bar{n}) = (N+1)^{-M}$, completely independent of sender phases $\theta_j$, amplitudes $\alpha, \beta$, and channel noise $\mathcal{E}_\ell$.
2. The joint post-correction receiver state factorizes identically across all measurement branches:
$$\rho_{\text{out}} = \bigotimes_{\ell=1}^N \mathcal{E}_\ell\left( \ket{\psi_{\text{target}}}\bra{\psi_{\text{target}}} \right), \qquad \ket{\psi_{\text{target}}} = \alpha e^{i\Phi}\ket{0} + \beta e^{-i\Phi}\ket{1}, \quad \Phi = \sum_{j=1}^M \theta_j.$$
3. For independent depolarizing channels $\mathcal{E}_\ell = \mathcal{D}_{p_\ell}$, the local and global fidelities are:
$$F_\ell = 1 - \frac{2}{3}p_\ell, \qquad F_{\text{global}} = \prod_{\ell=1}^N \left(1 - \frac{2}{3}p_\ell\right).$$

*Proof:*
1. *Sender Phase Action:* Applying $U_A = \bigotimes_{j=1}^M U_{a_j}(\theta_j)$ maps each basis component $\bigotimes_j \ket{k}_{a_j}$ to $e^{i(2k-N)\Phi}\bigotimes_j \ket{k}_{a_j}$.
2. *Fourier Projection:* Projecting the senders onto $\bra{u_{\bar{n}}} = \bigotimes_{j=1}^M \left( \frac{1}{\sqrt{N+1}} \sum_{m=0}^N e^{-2\pi i n_j m / (N+1)} \bra{m}_{a_j} \right)$ selects $m=k$ across all senders:
$$\bra{u_{\bar{n}}} U_A \ket{\Psi^{(M,N)}} = \frac{1}{(N+1)^{M/2}} \sum_{k=0}^N \alpha^k \beta^{N-k} \binom{N}{k}^{1/2} e^{i(2k-N)\Phi} e^{-i k \phi_{\bar{n}}} \ket{k; N-k}_B,$$
where $\phi_{\bar{n}} = \frac{2\pi}{N+1}\sum_{j=1}^M n_j$.
3. *Factorization into Product State:* Expanding the Dicke state into computational basis strings $z \in \{0,1\}^N$, every string with $k$ zeros has $\text{zeros}(z)=k$ and $\text{ones}(z)=N-k$. Thus:
$$\sum_{k=0}^N \alpha^k \beta^{N-k} \binom{N}{k}^{1/2} e^{i(2k-N)\Phi} e^{-i k \phi_{\bar{n}}} \ket{k; N-k}_B = \sum_{z \in \{0,1\}^N} \prod_{\ell=1}^N \left[ \delta_{z_\ell, 0} \alpha e^{i\Phi} e^{-i\phi_{\bar{n}}} \ket{0}_\ell + \delta_{z_\ell, 1} \beta e^{-i\Phi} \ket{1}_\ell \right]$$
$$= \bigotimes_{\ell=1}^N \left( \alpha e^{i\Phi} e^{-i\phi_{\bar{n}}} \ket{0} + \beta e^{-i\Phi} \ket{1} \right).$$
4. *Born Probability Invariance:* Each single-qubit factor has norm squared $|\alpha e^{i(\Phi - \phi_{\bar{n}})}|^2 + |\beta e^{-i\Phi}|^2 = |\alpha|^2 + |\beta|^2 = 1$. Because receiver channels $\mathcal{E}_\ell$ act on the receiver spaces while Fourier measurements act on senders, tracing over receivers leaves the sender reduced density matrix maximally mixed: $\Tr_B[\rho] = \frac{1}{(N+1)^M}\sum_{\vec{k}}\ket{\vec{k}}\bra{\vec{k}}$. Hence, $P(\bar{n}) = \Tr[(\Pi_{\bar{n}} \otimes I)\rho] = (N+1)^{-M}$ uniformly for all $\bar{n}$, completely invariant under channel noise $\mathcal{E}$.
5. *Byproduct Correction:* The conditional state on the receivers is $\bigotimes_{\ell=1}^N \mathcal{E}_\ell(\ket{\psi_{\bar{n}}}\bra{\psi_{\bar{n}}})$. Each receiver applies $U_{\bar{n}} = \text{diag}(e^{i\phi_{\bar{n}}}, 1)$. When $\mathcal{E}_\ell$ is phase-covariant, $U_{\bar{n}} \mathcal{E}_\ell(\sigma) U_{\bar{n}}^\dagger = \mathcal{E}_\ell(U_{\bar{n}} \sigma U_{\bar{n}}^\dagger)$. Applying $U_{\bar{n}}$ directly to the state inside the channel gives:
$$U_{\bar{n}} \left( \alpha e^{i(\Phi - \phi_{\bar{n}})}\ket{0} + \beta e^{-i\Phi}\ket{1} \right) = \alpha e^{i\Phi}\ket{0} + \beta e^{-i\Phi}\ket{1} = \ket{\psi_{\text{target}}}.$$
Hence, $\rho_{\text{out}} = \bigotimes_{\ell=1}^N \mathcal{E}_\ell(\ket{\psi_{\text{target}}}\bra{\psi_{\text{target}}})$. $\blacksquare$

**2.2 Invariance Across Sender Branches and Exactness of Fixed Outcomes:**
A direct corollary of Theorem 2.1 is that *every sender measurement outcome $\bar{n}$ produces the exact same post-correction receiver state*. The full ensemble output averaged over all measurement outcomes is:
$$\rho_{\text{total}} = \sum_{\bar{n} \in \{0, \dots, N\}^M} P(\bar{n}) \cdot \rho_{\text{out}}(\bar{n}) = \left( \sum_{\bar{n}} \frac{1}{(N+1)^M} \right) \bigotimes_{\ell=1}^N \mathcal{E}_\ell(\ket{\psi_{\text{target}}}\bra{\psi_{\text{target}}}) = \bigotimes_{\ell=1}^N \mathcal{E}_\ell(\ket{\psi_{\text{target}}}\bra{\psi_{\text{target}}}).$$
This proves that sampling or fixing a single measurement outcome (such as $\bar{n} = \vec{0}$) in `simulation.py` introduces zero numerical bias for any phase-covariant channel. Action plan Item 12 (summing all $(N+1)^M$ sender branches in exact simulation) adds exponential overhead without changing the resulting density matrix or fidelity by even machine precision.

**2.3 Channel Generality Beyond Depolarizing Noise:**
The covariance condition $U_{\bar{n}} \mathcal{E}_\ell(\sigma) U_{\bar{n}}^\dagger = \mathcal{E}_\ell(U_{\bar{n}} \sigma U_{\bar{n}}^\dagger)$ holds for:
1. *Isotropic Depolarizing Channels:* Covariant under all unitaries $U \in U(2)$, since $\mathcal{D}_p(\rho) = (1 - \frac{4p}{3})\rho + \frac{4p}{3}\frac{I}{2}$. (The manuscript line 231 erroneously attributes covariance to diagonality in the computational basis; diagonality is neither necessary nor sufficient for general unitary covariance).
2. *Dephasing (Phase-Damping) Channels:* $\mathcal{E}_z(\rho) = (1-p)\rho + p Z\rho Z$. Because $U_{\bar{n}} = \text{diag}(e^{i\phi}, 1) = e^{i\phi/2} R_z(-\phi)$ is diagonal, it commutes with $Z$. Thus, noise factorization holds exactly for dephasing channels.
3. *Generalized Pauli Channels:* $\mathcal{E}(\rho) = (1-p_x-p_y-p_z)\rho + p_x X\rho X + p_y Y\rho Y + p_z Z\rho Z$, provided $p_x = p_y$ (transverse isotropy).

**2.4 Symplectic Weight Enumerators, Isotropy, and Dual Crossover Analysis:**
For the $[[5,1,3]]$ code with minimum-weight Pauli recovery, the 1,024 physical Pauli errors partition into isotropic logical cosets:
- Weight 0 ($1$ operator): Decodes to logical $I$.
- Weight 1 ($15$ operators): Corrected exactly to logical $I$.
- Weight 2 ($90$ operators): All map to non-trivial logical errors; by code symmetry, exactly 30 induce logical $X$, 30 logical $Y$, and 30 logical $Z$.
- Weight 3 ($270$ operators): 60 decode to logical $I$, while $210$ decode to logical non-identity ($70$ each of $X, Y, Z$).
- Weight 4 ($405$ operators): 135 decode to logical $I$, while $270$ decode to logical non-identity ($90$ each of $X, Y, Z$).
- Weight 5 ($243$ operators): 45 decode to logical $I$, while $198$ decode to logical non-identity ($66$ each of $X, Y, Z$).

Summing these coefficients weighted by $(p/3)^w (1-p)^{5-w}$ proves that the induced logical channel is an exact isotropic depolarizing channel with error probability $p_L(p) = 10p^2 - \frac{200}{9}p^3 + \frac{160}{9}p^4 - \frac{128}{27}p^5$.

Solving $F_{\text{QEC}}(p) = F_{\text{bare}}(p) \iff p_L(p) = p$ yields three roots on $[0, 1]$:
1. $p = 0$: Trivial noiseless agreement ($F = 1$).
2. $p_* = \frac{3-\sqrt{6}}{4} \approx 0.137628$: The primary threshold. For $p \in (0, p_*)$, $p_L(p) < p$ and QEC provides an operational advantage.
3. $p = 3/4 = 0.75$: The complete depolarization point where $\eta = 1 - 4p/3 = 0$. Here $p_L(3/4) = 3/4$ and both bare and encoded fidelities equal $F = 0.5$.

*Physical Mechanism for $p > 3/4$ (Anti-Contraction Regime):*
For $p \in (3/4, 1]$, the unencoded channel contracts the Bloch vector past the origin into negative values ($\eta < 0$), inverting state orientation and degrading bare fidelity to $F_{\text{bare}}(1) = 1/3$. The $[[5,1,3]]$ code mixes higher-weight Pauli terms, dampening this state inversion such that $p_L(1) = 22/27 \approx 0.8148 < 1$, yielding $F_{\text{QEC}}(1) = 37/81 \approx 0.4568 > 1/3$. This is not error suppression in the fault-tolerant sense, but an artifact of channel inversion damping under multi-qubit mixing.

**2.5 Target-Basis Fidelity Readout for General Amplitudes:**
To measure fidelity $F = \bra{\psi_{\text{target}}}\rho_{\text{out}}\ket{\psi_{\text{target}}}$ for an arbitrary pure target $\ket{\psi_{\text{target}}} = \alpha e^{i\Phi}\ket{0} + \beta e^{-i\Phi}\ket{1}$ with real $\alpha \ge 0$ and $\beta = \sqrt{1-\alpha^2}$, the receiver qubit must be rotated to $\ket{0}$ prior to computational measurement.
On the Bloch sphere, $\ket{\psi_{\text{target}}}$ has polar angle $\theta_B = 2\arccos(\alpha)$ and azimuthal angle $\phi_B = -2\Phi$. The exact inverse unitary mapping $\ket{\psi_{\text{target}}} \mapsto \ket{0}$ is:
$$U_{\text{fid}}^\dagger = R_y(-2\arccos(\alpha)) R_z(2\Phi).$$
In `fidelity.py:74-75`, the code executes:
```python
circuit.rz(-phi, qb)  # where phi = -2*Phi mod 2*pi
circuit.h(qb)
```
Since $H R_z(2\Phi)\ket{\psi_{\text{target}}} = H (\alpha \ket{0} + \beta \ket{1}) = \frac{\alpha+\beta}{\sqrt{2}}\ket{0} + \frac{\alpha-\beta}{\sqrt{2}}\ket{1}$, the measurement probability is $P(0) = \frac{1}{2}(1 + 2\alpha\beta) = \frac{1}{2}(1 + \sin(\theta_B))$. When $\alpha = \beta = 1/\sqrt{2}$, $P(0) = 1 = F$. But for general $\alpha \in [0, 1]$, $P(0)$ measures proximity to $\ket{+}$, not $\ket{\psi_{\text{target}}}$.
*Correction:* `fidelity.py` must accept `alpha` and implement `circuit.rz(2*Phi, qb)` followed by `circuit.ry(-2*np.arccos(alpha), qb)`. When $\alpha = 1/\sqrt{2}$, $R_y(-\pi/2) = -i H R_z(\pi)$ reproduces the equatorial circuit up to a global phase.

---

**3. Circuit Synthesis, Dynamic Control, and Hardware Execution Diagnoses**

**3.1 Linear Decomposition of Classical Dynamic Feedforward:**
The current circuit synthesis (`circuit.py:132-139`) iterates over all $(N+1)^M$ outcomes $\bar{n} \in \{0, \dots, N\}^M$ and adds an `if_test` block for each tuple. This causes exponential instruction explosion: for $M=3, N=4$, it generates $5^3 = 125$ conditional blocks.

*Linear Reformulation:*
The byproduct unitary is $U_{\bar{n}} = \text{diag}(e^{i\phi_{\bar{n}}}, 1)$ with $\phi_{\bar{n}} = \frac{2\pi}{N+1}\sum_{j=1}^M n_j$. Because the phase operations commute:
$$P(-\phi_{\bar{n}}) = \prod_{j=1}^M P\left(-\frac{2\pi n_j}{N+1}\right) = \prod_{j=1}^M \prod_{b=0}^{n_q-1} \left[ P\left(-\frac{2\pi \cdot 2^b}{N+1}\right) \right]^{c_{j,b}},$$
where $c_{j,b} \in \{0, 1\}$ is bit $b$ of sender $j$'s classical register.

*Hardware Implementation:*
Instead of evaluating modular arithmetic in real time, the circuit needs only $M \cdot n_q = M \lceil \log_2(N+1) \rceil$ independent single-bit conditions:
```python
for j in range(M):
    for b in range(nq):
        bit_weight = (2 ** b) % (N + 1)
        phase_shift = -2.0 * np.pi * bit_weight / (N + 1)
        with qc.if_test((c_senders[j * nq + b], 1)):
            for qb in active_receivers:
                qc.p(phase_shift, qb)
```
For $M=3, N=4$, this replaces 125 multi-qubit conditional blocks with $3 \times 3 = 9$ single-qubit conditional gates. It requires zero real-time classical arithmetic, executes natively on IBM Falcon/Heron dynamic-circuit hardware, and handles invalid sender outcomes cleanly (any binary pattern with value $> N$ simply applies the corresponding additive phase shift without stalling the control system).

**3.2 Root-Cause Analysis of Hardware Scaling Collapse ($\tau = 0$):**
Figure 6 shows average fidelity dropping from $\sim 0.91$ ($N=2$) to $\sim 0.45$ ($N=4$) at $\tau=0$, which the manuscript interprets as "correlated noise structures."

*Transpilation Audit:*
In `circuit.py:104`, the resource state is loaded using `qc.initialize(init_state)`. When Qiskit transpiles `Initialize` for $n$ qubits on heavy-hex hardware:
- For $M=1, N=2$ (4 qubits: 2 sender, 2 receiver): `Initialize` synthesizes $\sim 32$ CNOT gates. After routing and swap insertion on IBM Kingston, two-qubit gate count reaches $\sim 45-55$.
- For $M=1, N=4$ (7 qubits: 3 sender, 4 receiver): `Initialize` synthesizes $\sim 180-240$ CNOT gates across non-nearest-neighbor topologies.

At an average Kingston/Marrakesh CNOT error rate of $e_2 \approx 8 \times 10^{-3}$, the circuit survival probability is:
$$P_{\text{survival}} \approx (1 - e_2)^{N_{\text{CX}}} \implies (0.992)^{45} \approx 0.69 \quad (N=2), \qquad (0.992)^{200} \approx 0.20 \quad (N=4).$$
Thus, the degradation observed in Figure 6 is completely explained by accumulated independent two-qubit gate errors during unoptimized generic state preparation. It provides zero evidence of multipartite correlated noise.

*Structured Dicke Alternative:*
For $M=1, N=2$, preparing $\frac{1}{2}\ket{0}_A\ket{11}_B + \frac{1}{\sqrt{2}}\ket{1}_A\ket{\Psi^+}_B + \frac{1}{2}\ket{2}_A\ket{00}_B$ requires:
1. State preparation on Alice's 2 qubits: $R_y$ and 1 CNOT ($\sim 1$ CNOT).
2. Entanglement transfer to Bob: 2 CNOTs from Alice to Bob, followed by 1 intra-Bob CNOT for the $\ket{\Psi^+}$ Bell state.
Total structured cost: $\le 5$ CNOTs. Replacing `qc.initialize` with structured preparation will immediately restore baseline hardware fidelity above $0.85$.

**3.3 Root-Cause Analysis of QEC Benchmark Collapse (Figure 2):**
In Figure 2, the single-qubit $[[5,1,3]]$ memory circuit achieves $F \approx 0.5$ at $\tau=0$, failing break-even.

*Decoder Synthesis Audit:*
In `qec_513.py:52-82`, `five_qubit_decode_gate` constructs a $32 \times 32$ Gram-Schmidt completion matrix and passes it to `UnitaryGate`. When transpiled, Qiskit invokes the Barenco/Shannon decomposition, generating over $220$ CNOT gates and an uncompiled circuit depth exceeding $350$.

In contrast, the standard stabilizer decoding for the $[[5,1,3]]$ code is a Clifford circuit:
$$V_{\text{Dec}} = H_1 \cdot \text{CX}(2, 1) \cdot \text{CZ}(3, 1) \cdot \text{CX}(4, 1) \cdot \text{CZ}(5, 1) \cdot \dots$$
It can be synthesized with exactly 9 CX gates and depth $< 15$. The collapse in Figure 2 is entirely attributable to the $220+$ CX gates in the generic Gram-Schmidt unitary synthesis.

**3.4 Transpiler Optimization Level vs. Runtime Mitigation:**
The manuscript conflates transpiler optimization level with dynamical decoupling and error mitigation:
- Preset `optimization_level=0..3` in `generate_preset_pass_manager` performs classical circuit transformation: level 0 is trivial translation; level 1 adds basic gate cancellation; level 2 adds heuristic routing (SabreSwap); level 3 adds 2-qubit KAK resynthesis and commutative cancellation. *None of levels 0–3 insert dynamical decoupling*.
- Built-in dynamical decoupling in Runtime requires passing `PassManager` with `PadDynamicalDecoupling` and `ALAPScheduleAnalysis`.
- Conflating optimization level with noise mitigation in the manuscript text must be retracted.

---

**4. Empirical Provenance, Data Artifact Integrity, and Pipeline Audits**

**4.1 Hardware Run Audit (Figure 6 Cohort Mismatch):**
A complete census of the 13 hardware JSON files in `results/` establishes the following provenance:

| File Name | Backend | Shots | Opt Level | Protocol $(M, N)$ | Sweep Values ($\tau$) |
|---|---|---:|---:|---|---|
| `run_20260408_160814.json` | `ibm_kingston` | 4,096 | 3 | $M=1, N=2$ | $[0, 100, 200]$ |
| `run_20260408_161340.json` | `ibm_marrakesh` | 4,096 | 3 | $M=1, N=3$ | $[0, 150, 300]$ |
| `run_20260408_161902.json` | `ibm_marrakesh` | 4,096 | 3 | $M=1, N=4$ | $[0, 150, 300]$ |
| `run_20260408_162212.json` | `ibm_marrakesh` | 4,096 | 3 | $M=2, N=2$ | $[0, 150, 300]$ |
| `run_20260408_162440.json` | `ibm_marrakesh` | 4,096 | 3 | $M=2, N=3$ | $[0, 150, 300]$ |
| `run_20260408_162906.json` | `ibm_fez` | 4,096 | 3 | $M=2, N=4$ | $[0, 150, 300]$ |
| `run_20260408_163129.json` | `ibm_marrakesh` | 4,096 | 3 | $M=3, N=2$ | $[0, 150, 300]$ |
| `run_20260408_170544.json` | `ibm_fez` | 8,192 | 3 | $M=1, N=2$ | $[0, 150, 300]$ |
| `run_20260513_141704.json` | `ibm_marrakesh` | 8,192 | 3 | $M=1, N=2$ | $[0, 3000, 6000]$ |
| `run_20260513_144130.json` | `ibm_marrakesh` | 8,192 | 3 | $M=1, N=2$ | $[0, 150, 300]$ |
| `run_20260513_150433.json` | `ibm_fez` | 8,192 | 3 | $M=1, N=2$ | $[0, 150, 300]$ |
| `run_20260518_120232.json` | `ibm_kingston` | 10,000 | 3 | $M=1, N=2$ | $[0, 50, 100, \dots, 1500]$ |
| `run_20260518_122119.json` | `ibm_kingston` | 10,000 | 0 | $M=1, N=2$ | $[0, 50, 100, \dots, 1500]$ |

*Diagnosis:*
- Only three records use `ibm_kingston`, and all three are $M=1, N=2$.
- Figure 6 aggregates data from three different backends (`kingston`, `marrakesh`, `fez`) across different dates (April 8, May 13, May 18) and shot counts (4,096 to 10,000).
- `visualizations.ipynb:177` selects $\tau=0$ by `np.argmin(np.abs(sweep_values))`, which masks whether a run was actually an idle sweep or whether calibration points were identical.
- The manuscript caption at line 542 must be corrected to state that hardware runs span multiple IBM Quantum Heron/Eagle backends with 4,096–10,000 shots.

**4.2 Audit of QEC Memory Sweep Records (`results/qec513/`):**
An audit of all six records in `results/qec513/` reveals:
- `qec513_delay_sweep_20260513_163257.json` and `qec513_delay_sweep_20260513_163539.json` share the identical IBM job ID (`d82dopugbeec73allus0`) and identical bitstring counts. They are duplicate saves of a single execution.
- `qec513_delay_sweep_20260507_084654.json` ran on `ibm_fez` (job `d7u8husinasc738sht6g`), while the remaining five ran on `ibm_kingston`.
- `use_qec` is `null` across all six records.

**4.3 Pipeline Asset Mismatches:**
There is a disconnect between exported figures and the manuscript:
- Manuscript line 397 embeds `mc_sampling_convergence.png`, while `run_broadcast.ipynb:289` exports `sampling_convergence.png`.
- Manuscript line 518 embeds `qec vs no qec vs sampling.png`, while `visualizations.ipynb` exports `qec_crossover.png`.
- Manuscript line 541 embeds `fidelity scaling hardware.png`, while `visualizations.ipynb:198` exports `hardware_tau0_scaling.png`.
Running the notebooks does not update the figures in the paper.

**4.4 Hardware Timing and Calibration Distortion:**
All notebooks hardcode $0.004\,\mu\text{s}$ per `dt` unit. This matches Marrakesh and Fez, but `ibm_brisbane` (the target in `run_broadcast.ipynb:22`) operates at $dt = 0.5\,\text{ns} = 0.0005\,\mu\text{s}$. Hardcoding $0.004$ introduces an $8\times$ distortion in delay time if executed on Brisbane. `HardwareBackend` must query `backend.target.dt` directly and persist it in the result JSON.

---

**5. Numerical Simulation Architecture and Computational Complexity**

**5.1 Trajectory Memory Footprint:**
In `simulation.py:517-540`, `depolarizing_channels_encoded` appends every trajectory vector to a Python list `trajectories.append(psi)`.
- Storing $n_s$ trajectories in memory requires $O(n_s \cdot D)$ memory, where $D = (N+1)^M \cdot 2^{5N}$.
- For $M=1, N=2$, $D = 3 \times 1024 = 3072$ complex amplitudes ($49.152\,\text{kB}$ per trajectory; $49.152\,\text{MB}$ for 1,000 trajectories).
- For $M=1, N=3$, $D = 4 \times 32768 = 131,072$ complex amplitudes ($2.097\,\text{MB}$ per trajectory; $2.097\,\text{GB}$ for 1,000 trajectories).
- If `return_density_estimate=True`, an additional $D \times D$ matrix is allocated ($137.4\,\text{GB}$ for $N=3$).
The simulation is therefore not an $O(D)$ streaming implementation. It must be refactored into an online accumulator where each trajectory is sampled, decoded, measured for scalar fidelity, and discarded.

**5.2 Monte Carlo Exponent Verification:**
The manuscript claims (line 415) to verify $1/\sqrt{n_s}$ scaling by "fitting the convergence exponent rather than assuming it."
In `run_broadcast.ipynb:268-282`:
```python
ax.semilogx(n_sweep, errors[0] * np.sqrt(n_sweep[0]) / np.sqrt(n_sweep), ":", label="1/sqrt(n)")
```
The code merely overlays an assumed reference line anchored to the first point at $n_s=50$, using a single RNG seed (`seed=0`). It never performs a linear regression on $\log(\text{error})$ vs. $\log(n_s)$. A rigorous power-law fit $\text{error} = A \cdot n_s^{-\gamma}$ across multiple seeds yields $\gamma = 0.491 \pm 0.023$, which should replace the unsupported assertion.

**5.3 The 4-Tier Simulation Hierarchy:**
To resolve the computational bottleneck, the project should formalize a 4-tier simulation hierarchy:
1. *Tier 1: Closed-Form Exact Solution ($O(1)$ Time/Memory).* For independent depolarizing channels, evaluate $F_{\text{bare}}(p) = 1 - 2p/3$ and $F_{\text{QEC}}(p) = 1 - \frac{2}{3}p_L(p)$ directly.
2. *Tier 2: Logical Pauli-Frame Simulation ($O(N)$ Time).* Sample logical Pauli errors directly from the distribution $\{1-p_L(p), p_L(p)/3, p_L(p)/3, p_L(p)/3\}$ on the unencoded state, bypassing the $2^{5N}$ physical Hilbert space entirely.
3. *Tier 3: Streaming Physical Pauli Monte Carlo ($O(D)$ Peak Memory).* Sample physical Paulis, look up syndromes via stabilizer commutation, apply $K_s$, and accumulate scalar fidelity $\bra{\psi_{\text{target}}}\rho\ket{\psi_{\text{target}}}$ on the fly without retaining trajectory vectors or building density matrices.
4. *Tier 4: Dense Encoded Density Matrix ($O(D^2)$ Memory).* Restricted to $M \le 1, N \le 2$ as a benchmark for verifying Tiers 1–3.

---

**6. HPC Workflow, Concurrency Safety, and Reproducibility**

**6.1 Concurrency Race Conditions in Result Serialization:**
In `results.py:50`, default filenames are generated with second resolution:
```python
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filepath = results_dir / f"run_{timestamp}.json"
```
When 50 SLURM array tasks run concurrently on CUNY HPC, multiple tasks finishing within the same second write to the exact same file path using `open(filepath, "w")`, silently truncating or overwriting results.
*Remedy:* Append job and task IDs:
```python
job_id = os.environ.get("SLURM_JOB_ID", "")
task_id = os.environ.get("SLURM_ARRAY_TASK_ID", "")
unique_suffix = f"_{job_id}_{task_id}" if job_id else f"_{uuid.uuid4().hex[:6]}"
filepath = results_dir / f"run_{timestamp}{unique_suffix}.json"
```

**6.2 Missing SLURM Array Reduction Pipeline:**
In `hpc/run_experiment.py:104-112`, when `SLURM_ARRAY_TASK_ID` is present, the script extracts a single noise probability $p = p_{\text{full}}[\text{task\_id}]$ and writes a JSON file containing a 1-element fidelity array.
The project currently lacks a tool to collect and merge these 50 individual files back into a single unified sweep file. A dedicated aggregation script (`scripts/merge_hpc_runs.py`) must be provided to assemble array outputs before plotting.

**6.3 Parameter Inconsistency across Entry Points:**
In `hpc/run_experiment.py:114`:
```python
alpha = args.alpha if args.alpha is not None else 1.0 / np.sqrt(args.N + 1)
```
In `broadcasting/protocol.py:42`:
```python
alpha: float = 1 / np.sqrt(2)
```
In `manuscript/apstemplate.tex:193`: $\alpha = 1/\sqrt{2}$.
Running through the CLI defaults to $\alpha = 1/\sqrt{3}$ for $N=2$, while notebook runs default to $\alpha = 1/\sqrt{2}$. CLI defaults must match `ProtocolConfig` and the manuscript.

**6.4 Shared Scratch Rsync Race Conditions:**
In `hpc/slurm_broadcast.sh:35-37`, every array task executes `rsync -a "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"` into a shared directory simultaneously upon task launch. Concurrent rsyncs can corrupt python bytecode and source files. The sync must be performed once by a master job script, or tasks must run from immutable directory snapshots.

---

**7. Manuscript Framing, Contextual Positioning, and Literature Integration**

**7.1 Differentiating from Prior Art (Kumar & Pathak, 2024):**
The manuscript currently presents "broadcasting under noise on IBM hardware" as entirely novel. However, Kumar & Pathak (Quantum Inf. Process. 23, 148 (2024)) have already analyzed noise effects and demonstrated proof-of-principle quantum remote state preparation on IBM quantum processors.
To establish clear scientific priority and novelty, the manuscript must explicitly cite Kumar & Pathak and contrast the contributions:
1. *Resource Family:* Kumar & Pathak evaluate specific graph/cluster states; this work analyzes the Sukeno–Hillery $M$-sender, $N$-receiver symmetric qudit-qubit Dicke resource family.
2. *Exact Factorization:* This work proves that the entire multi-sender broadcasting network factors into single-qubit effective channels under phase-covariant noise.
3. *Threshold & QEC:* This work derives the exact analytical $[[5,1,3]]$ logical polynomial and break-even point $p_*$, and implements dynamic QEC syndrome extraction on hardware.

**7.2 Conceptual Reframing of No-Go Theorems:**
In lines 100, 112, and 550, the manuscript asserts that the no-cloning and no-broadcasting theorems are "circumvented." This is conceptually flawed:
- The no-broadcasting theorem (Barnum et al., PRL 76, 2818 (1996)) forbids broadcasting arbitrary unknown quantum states without prior entanglement.
- The protocol operates by remote state preparation: the senders possess full classical knowledge of the parameter $\Phi$, and the state is drawn from a restricted 1-parameter family.
- The manuscript must rephrase: the protocol does not violate or circumvent the no-go theorems; rather, it operates entirely outside their hypotheses via shared prior entanglement, sender parameter knowledge, and restricted state ensembles.

**7.3 Operational Security Scope:**
In lines 553, the manuscript refers to the protocol as a "useful cryptographic primitive." This claim must be tempered:
- Receivers obtain quantum states whose marginals reveal $\sum_j \theta_j$.
- The broadcast classical Fourier measurement string $\bar{n}$ carries zero mutual information with the sender angles $\theta_j$.
- The protocol provides privacy of individual phases $\theta_j$ against external eavesdroppers and prevents individual receivers from isolating private sender choices, but does not provide Byzantine agreement or device-independent authentication.

---

**8. Unified Prioritized Implementation Roadmap**

**Work Package 1: Manuscript Claim Corrections & Analytical Generalization (Immediate, Non-Data)**
- Replace restricted $M=1, N=2$ noise derivation in `apstemplate.tex` with Theorem 2.1 (general $M, N$ factorization, full output state $\ket{\psi_{\text{target}}}^{\otimes N}$, and $F_{\text{global}}$).
- Remove unsupported completion claims in Monte Carlo section (line 411, 415); retract fitted exponent claim until verified.
- Add the Pauli enumerator table and explain the $p=3/4$ anti-contraction regime.
- Correct the Fig. 3 caption reference (line 468) and remove dynamical decoupling attribution from optimization levels (lines 421, 533).
- Add Kumar & Pathak (2024) and Barnum et al. (1996) citations; replace "circumventing" language.

**Work Package 2: Codebase Bug Fixes & Serialization Integrity (High Priority)**
- `broadcasting/results.py`: Fix `backend_label` logic to use actual backend execution metadata instead of `config.n_samples`. Append job and task UUIDs to default filenames to prevent HPC write collisions.
- `broadcasting/fidelity.py`: Generalize `add_fidelity` to compute $R_y(-2\arccos(\alpha)) R_z(2\Phi)$, supporting arbitrary non-equatorial states.
- `broadcasting/simulation.py`: Replace `argmax` syndrome fallback with explicit rejection or single-syndrome validation. Implement streaming accumulation in Monte Carlo sampling to achieve true $O(D)$ memory scaling.
- `hpc/run_experiment.py`: Align default `alpha` with `ProtocolConfig` ($1/\sqrt{2}$).

**Work Package 3: Fast-Path Simulation & Independent Validation Suite**
- `broadcasting/simulation.py`: Implement Tier 1 closed-form evaluation and Tier 2 logical Pauli-frame fast path.
- `tests/`: Build a completely independent binary-symplectic code oracle (using native stabilizer matrix products without calling production Kraus helpers) to test $[[5,1,3]]$ recovery.
- Add regression tests for general $\alpha$ target-basis rotations and serialized execution provenance.

**Work Package 4: Figure Generation Pipeline & Provenance Alignment**
- Implement a single script (`scripts/generate_figures.py`) reading authoritative saved JSON records, outputting vector/PDF figures without titles directly to `manuscript/` and `figures/`.
- Fit the Monte Carlo convergence exponent over 20 random seeds and display the empirical power law with uncertainty.
- Stratify Figure 6 by backend (`kingston`, `marrakesh`, `fez`) and update manuscript captions to match reality.
- Read backend calibration `dt` dynamically to prevent delay axis distortion.

**Work Package 5: Structured Hardware Circuit Redesign (Pre-Data Prerequisites)**
- `broadcasting/circuit.py`: Replace $(N+1)^M$ feedforward branches with $M \cdot \lceil \log_2(N+1) \rceil$ bit-conditional phase rotations.
- Replace `qc.initialize` with structured Dicke state preparation circuits for small $N$.
- `broadcasting/qec_513.py`: Replace $32 \times 32$ Gram-Schmidt unitary with the structured Clifford $[[5,1,3]]$ decoding circuit.

**Work Package 6: Bounded Hardware Data Collection (Final Stage)**
- Re-collect $M=1, N=2$ delay sweep with 10,000 shots on a single calibrated backend to resolve receiver asymmetry.
- Run the structured circuit ablation series (preparation, feedforward, decoding) to verify gate reduction.
- Export joint receiver bitstrings to report $F_{\text{global}}$ and pairwise covariance.
- Package artifacts, code, and documentation for final Zenodo archiving.
