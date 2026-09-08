# Action Plan: Addressing the Broadcasting-2 Critique

This plan translates [Broadcasting-2_Critique.md](Broadcasting-2_Critique.md), additional review
comments, and the independent [PROJECT_REVIEW.md](PROJECT_REVIEW.md) feedback (two external model
reviews of the codebase, manuscript, and HPC workflow) into concrete, ordered work.

**Revision 2 (2026-09-08):** Corrects over-claimed "DONE" status from revision 1, incorporates
verified bugs found by `PROJECT_REVIEW.md` (result serialization, fidelity readout, HPC filename
collisions, figure/data provenance mismatches), drops an unnecessary item (exact sender-branch
summation — proven unneeded, see Phase 1), and corrects two infeasible proposals from revision 1
(Sampler `resilience_level`, runtime-arithmetic feedforward). See "Review synthesis" below for what
was independently verified versus what remains a reviewer-reported claim to check before acting on.

**Revision 3 (2026-09-08):** Implements the Phase 2 correctness fixes and the Phase 6 structured-circuit
items that don't require the (deferred) Clifford `[[5,1,3]]` decoder redesign, plus a ready-to-run
preliminary hardware test script. See "What changed in revision 3" after the phase list.

## ⚠️ HPC data-safety ground rules (per user instruction)

**The hardware runs in `results/`, `results/legacy/`, and `results/qec513/` cannot be regenerated.**
Every change touching HPC code, result serialization, or these files must follow:
1. **Never delete, rename-in-place, or rewrite existing files** under `results/`. Git history is not
   a substitute for care here — treat these JSON files as irreplaceable lab notebooks.
2. **Code fixes to `results.py`/serialization only change newly created runs.** Do not "repair" old
   records' fields (e.g. `backend`, `mode`, `dt`) by mutating them in place. If a historical field is
   wrong or ambiguous, note it in analysis code / the manuscript, or add a clearly-labeled derived
   copy — never silently overwrite the source file.
3. Simulation records (`aer_exact`/`aer_sampling`) **are cheap to regenerate** since they're local
   Aer/NumPy computations — mislabeling bugs there can be fixed by fixing the code and, if desired,
   re-running. Hardware records are not in this category; treat them with more caution.
4. Any HPC pipeline change (filenames, `rsync`, SLURM scripts) must be additive and tested on a
   scratch/dry-run basis (e.g. `--array=0-1` with a throwaway output dir) before being reused for a
   real, non-reproducible job.
5. When in doubt, prefer an analysis-time correction (a small provenance-override table, a
   stratification key, a recomputation check) over any modification to the raw HPC output files.

## Legend
- **[Code]** — change in `broadcasting/` (or `hpc/`)
- **[MS]** — change in `manuscript/apstemplate.tex`
- **[Data]** — requires new simulation/hardware runs — deferred to Phase 8
- **[HPC-sensitive]** — touches non-reproducible hardware data or the HPC pipeline; extra care required

---

## Review synthesis: what I independently verified vs. what remains a reviewer claim

I spot-checked the highest-impact claims in `PROJECT_REVIEW.md` directly against the repository
before updating this plan. Findings below are marked accordingly; unverified numeric/quantitative
claims (exact CNOT counts, specific hardware error rates, `/tmp` audit scripts from the reviewer's
own session) are flagged as directional estimates to confirm before quoting in the manuscript.

**Confirmed by direct inspection this session:**
- `broadcasting/results.py` (~line 80): `if "sampl" in mode or config.n_samples:` — since
  `ProtocolConfig.n_samples` defaults to `200` (truthy), this can mislabel exact runs as
  `aer_sampling` whenever the config wasn't explicitly zeroed. **Real bug, low risk to fix** since
  affected records are simulation runs (cheaply reproducible).
- `broadcasting/backend.py` calls `add_fidelity(qc, N=config.N, thetas=config.thetas)` **without**
  passing `config.alpha`, and `broadcasting/fidelity.py::add_fidelity` hardcodes the equatorial
  `Rz(-phi)` + `H` inverse rotation. Non-equatorial `alpha` on `HardwareBackend`/`SamplingBackend`
  fidelity circuits will silently read out the wrong quantity. Existing equatorial-only results are
  not affected by this; it matters for any future non-equatorial run.
- `hpc/run_experiment.py` defaults `alpha = 1/sqrt(N+1)` while `broadcasting/protocol.py`'s
  `ProtocolConfig` defaults `alpha = 1/sqrt(2)` — **confirmed mismatch** between CLI/HPC and
  notebook/dataclass defaults. Does not invalidate existing HPC results (whatever `alpha` was
  actually recorded in each run's saved config is still correct for that run); just needs
  consistency going forward.
- `results/qec513/qec513_delay_sweep_20260513_163257.json` and `..._163539.json` share the exact
  same `job_id` (`d82dopugbeec73allus0`) — **confirmed duplicate save**, not independent repetitions.
- `run_broadcast.ipynb` and `visualizations.ipynb` hardcode `tau_scale=4e-3` (µs/dt) while defaulting
  the target backend to `ibm_brisbane` (`dt≈0.0005 µs`, not `0.004`). **Confirmed latent bug** for
  any future Brisbane run; existing saved hardware runs are on Kingston/Marrakesh/Fez, where `4e-3`
  happens to be the correct conversion, so historical figures are not necessarily mis-scaled — but
  the notebook default must record/query the backend's actual `dt` going forward.
- Manuscript-embedded figure filenames do not match what the notebooks currently export
  (`mc_sampling_convergence.png` vs. exported `sampling_convergence.png`; `qec vs no qec vs
  sampling.png` vs. exported `qec_crossover.png`; `fidelity scaling hardware.png` vs. exported
  `hardware_tau0_scaling.png`) — **confirmed**; re-running the notebooks today would not update the
  figures actually embedded in the manuscript.
- The hardware-scaling figure's source cell (`visualizations.ipynb`, "Hardware Fidelity At Tau Zero")
  pools **all** `experiment_type == "hardware"` runs with no backend/shots filter. Grepping all 13
  hardware `results/run_*.json` files confirms a mixed cohort: `ibm_kingston` (4096/10000 shots),
  `ibm_marrakesh` (4096/8192 shots), `ibm_fez` (4096/8192 shots) — **confirmed cohort mismatch**
  matching the reviewer's provenance table.
- Manuscript `\label{fig:circuit}` is defined on the *unencoded* M=1,N=2 circuit figure but a later
  paragraph cites `Fig.~\ref{fig:circuit}` while describing the three-stage **QEC** circuit —
  **confirmed label/caption mismatch** (Fig. 3 text-figure disconnect).
- `hpc/slurm_broadcast.sh` runs `rsync -a ... "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"` at the top of the
  script that **every SLURM array task executes independently** — **confirmed** every task in an
  `--array=0-49` submission re-syncs code concurrently into the same shared scratch directory.
  Result-file collisions are separately confirmed via `results.py`'s second-resolution timestamp
  filenames opened with `"w"` (no exclusivity check).

**Reviewer claims not independently verified — treat as directional, confirm before quoting:**
- Specific CNOT-count estimates for `qc.initialize`/Gram-Schmidt synthesis (e.g. "30-60+", "200-240",
  "220+ CX", "8-10 CX for structured Clifford decode") — plausible order-of-magnitude, but not
  measured here. **Measure directly** (`transpile(...).count_ops()` / two-qubit gate count) before
  using specific numbers in the manuscript or in Phase 6 justification.
- Specific hardware error-rate/survival-probability arithmetic (`e2≈8e-3`, `(0.992)^45≈0.69`, etc.)
  — illustrative, not checked against actual backend calibration snapshots for the runs in question.
- The claim that Qiskit Runtime's built-in DD option is incompatible with dynamic circuits, requiring
  a separately-compiled scheduling pass — consistent with known Qiskit dynamic-circuit/scheduling
  constraints, but **verify against the currently pinned `qiskit`/`qiskit-ibm-runtime` versions**
  before implementing Phase 5.
- The reviewer's `resilience_level` correction (Sampler vs. Estimator) **is consistent with public
  Qiskit IBM Runtime API design** (resilience options are Estimator-specific); revision 1's Phase 4
  item proposing a `resilience_level` knob for `HardwareBackend`'s Sampler-based execution is
  **withdrawn** — see Phase 5 below.
- The reviewer's 13-row hardware-run provenance table (backend/shots per file) **matches** what a
  direct grep of `results/run_*.json` shows for every file checked — treated as confirmed.
- The `/tmp/broadcasting_qec_audit.py` independent symplectic-enumerator script and "150 small exact
  cases" mentioned in the review are from the reviewer's own ephemeral session and aren't in this
  repo. The underlying mathematical claim (isotropic weight distribution: 90/210/270/198 nonidentity
  operators at weights 2-5) matches what we already derived and tested — see Phase 0. A **genuinely
  independent** oracle (not reusing `five_qubit_recovery_kraus_operators`) is still an open item
  (Phase 1).

---

## Master list of recommended changes (from the critique + additional comments + review)

### A. Mathematical/analytical correctness
1. Eqs. (32)–(33): `p_f` misused — replace with exact logical-channel polynomial `p_L(p)` and exact crossover `p* = (3-√6)/4`. (§1.2, §3.1) — ✅ done
2. State the general noise-factorization proposition (`F_local` independent of `M,N`; `F_global = (1-2p/3)^N`) instead of deriving only for `M=1,N=2`. (§1.1, §3.1) — ❌ still open (manuscript still only derives `M=1,N=2`)
3. Explain the second crossover at `p=3/4` where the Bloch contraction convention becomes negative. (§1.2) — 🟡 partial (equality mentioned; the *anti-contraction* mechanism for `p>3/4`, where QEC becomes advantageous again, is not yet explained)
4. Give the full noiseless receiver output state with `Φ = Σθⱼ`, not just the single-receiver case. (§1.1) — ❌ still open (only appears inline in the QEC protocol section, not as a general labeled result)
5. Eq. (36) recovery map is algebraically wrong as written (`V_Dec E_s P_C E_s` projects but never corrects). Replace with `V_Dec E_s† P_s`, reconcile with the density-matrix and Monte Carlo code. (§1.3, §3.2) — ✅ done
6. Add tests: all 15 weight-one Paulis corrected exactly; trace preservation over all syndrome branches; induced logical channel matches `p_L(p)`; noiseless encoded protocol gives unit fidelity for arbitrary `α,β,θ`. (§1.3, §3.2) — ✅ done, but the brute-force "independent" oracle still calls production helpers (`five_qubit_recovery_kraus_operators`, `pauli_label_syndrome`) — not a fully independent implementation yet.

### B. Monte Carlo methodology
7. Fix description: syndrome is deterministic because a Pauli error maps a stabilizer codeword into one syndrome sector — not because the state is "pure". (§1.4) — ✅ done
8. Remove/justify `argmax` syndrome selection — compute syndrome directly from the sampled Pauli pattern; note that `argmax` is unsound for coherent/non-Pauli trajectories. (§1.4, §3.2) — ✅ done (deterministic Pauli-frame lookup is now the default; `argmax` kept only as an explicitly-warned fallback for unlabeled trajectories — review recommends tightening this further, see Phase 1)
9. **Work/memory accounting is incomplete and hard to interpret** — the stated `O(D)` memory / `O(n_s N D)` time omits the cost of accumulating `ρ̂` (`O(d_dec²)` per trajectory). Replace with a clearer, more interpretable complexity measure. (§1.4, additional comment) — 🟡 partial: manuscript text now *describes* the `d_dec²` accumulation cost and recommends measuring wall-clock/memory, but no actual measurement/report exists yet, and the review found the description is still incomplete (retained encoded trajectory list itself costs `O(n_s·D)`, not just `O(D)` — see Phase 1).
10. Sample/propagate logical Pauli errors directly on the unencoded `(N+1)^M · 2^N`-dimensional state instead of the full `2^{5N}`-dimensional encoded state (the "Tier 2" fast path). (§1.4, §3.3) — ❌ not implemented
11. Average scalar fidelity per trajectory instead of building an empirical density matrix when only fidelity is needed. (§1.4, §3.3) — ❌ not implemented (manuscript describes this as an *available option*; it is not actually available in code yet — wording should be softened until implemented, see Phase 1)
12. ~~Sum sender measurement branches exactly in the "exact" reference method instead of sampling one outcome.~~ — **withdrawn**. `PROJECT_REVIEW.md` §2 proves (and we accept the proof) that under any phase-covariant receiver channel, every sender branch `n̄` yields an *identical* post-correction receiver state; fixing one outcome is exact, not an approximation. Replace this action item with: **add the branch-invariance theorem to the manuscript** (Phase 0) instead of adding exponential-cost branch summation.

### C. Hardware interpretation claims
13. Fig. 6 cannot distinguish correlated hardware errors from ordinary independent-but-accumulating circuit errors as circuit size grows — soften/narrow the claim. (§1.5, §3.6)
14. Report `F_local`, `F_global = (1-2p/3)^N`, and worst-receiver fidelity separately; local averages cannot diagnose correlation. (§1.5, §1.9, §3.5) — 🆕 much of this is *already computable* from existing saved joint-receiver bitstrings without new data (see Phase 8 "reuse existing data" note).
15. The `[[5,1,3]]` hardware result (Fig. 2) is a standalone encoded-memory test, not a full QEC-broadcasting demonstration — clarify scope mismatch with Figs. 5/6 (unencoded). (§1.6)
16. Replace generic Gram–Schmidt `32×32` decode unitary and `qc.initialize` resource-state loading with structured Clifford encoder/decoder and a Hamming-weight-based Dicke-state preparation circuit. (§1.6, §3.4) — refined in Phase 6: the sender register must store **the number of receiver zeros** `k = N - popcount(receiver_bits)` to match the existing resource-state/phase convention, not a generic Hamming weight.
17. Dynamical-decoupling claim is unsupported: Qiskit optimization levels 0–3 do not automatically apply DD; DD requires an explicit `PadDynamicalDecoupling` scheduling pass. Clarify text and, in code, either add explicit DD control or remove the DD attribution. (§1.7, additional comment)
18. ~~Add a `resilience_level` parameter for Runtime primitives, distinct from `optimization_level`.~~ — **corrected**: `HardwareBackend` executes via `SamplerV2`, which does not accept `resilience_level` (that option belongs to `EstimatorV2`). Replace this item with: clarify in text/code comments that optimization level (transpiler) and error mitigation (Estimator-only `resilience_level`, not applicable here) are distinct concepts, without adding a nonexistent Sampler option.
19. Quantify "quasi-periodic dropouts" with autocorrelation/periodogram analysis instead of visual inference. (§1.7)

### D. No-broadcasting framing & terminology
20. Reword "circumventing" no-cloning/no-broadcasting — the protocol works because it falls outside the theorems' hypotheses (restricted state family, prior entanglement, sender knowledge), not because the theorems are violated. (§1.8, §3.6, review §7.2)
21. State precisely what "privacy" means here: receivers learn only the aggregate `Σθⱼ`, not individual `θⱼ`; the broadcast classical string `n̄` carries zero mutual information with any `θⱼ`. (§1.8, review §7.3)
22. Soften the "useful cryptographic primitive" conclusion, or add an explicit application/security/threat model — no Byzantine agreement / device-independent authentication claims. (§1.9, review §7.3)
23. Cite the original 1996 no-broadcasting theorem (Barnum et al., PRL 76, 2818) in addition to the 2007 generalization; fix misattributed references (device `T1` range, self-testing citation). (§1.9)

### E. Presentation / secondary issues
24. Report invalid sender-qudit outcomes (e.g., outcome `3` when `N=2`) and state whether they are rejected/mapped/uncorrected. (§1.9) — clarified by review: the *current* behavior is that an invalid outcome simply matches no feedforward branch and therefore receives **no correction** (not rejection) — document this precisely and decide if it's the desired behavior.
25. Replace the `(N+1)^M`-branch exponential feedforward description with the actual dependency on `Σⱼnⱼ mod (N+1)` — **refined in Phase 6**: implement via `M·⌈log2(N+1)⌉` independent single-bit conditional phase rotations (exploiting that phase corrections commute and decompose bit-by-bit), *not* real-time classical modular-arithmetic evaluation, which IBM dynamic-circuit runtimes restrict/don't reliably support. (§1.9, review §3.1)
26. Clarify decoder qubit ordering / little-endian convention explicitly (Eqs. 25–26 vs Eq. 40). (§1.9)
27. Report circuit scheduling explicitly (are senders idle too, or only receivers?). (§1.9)
28. Full copyedit pass (grammar errors listed in §1.9).
29. Resolve coauthor placeholder and Zenodo placeholder — actually deposit code/data (deferred to end, per user request). (§1.9)

### F. Additional comments from user (not in critique doc)
30. Log-scale sampling-convergence plot: verify the `1/√n` reference line is scaled/anchored correctly. Review finding: the current overlay is an algebraically-correct first-point-normalized reference line, but it is **not** a fit and doesn't establish the `-1/2` exponent — needs a genuine log-log linear regression across multiple seeds.
31. Add data so the two receiver fidelity lines are not asymmetric at low shot counts (Fig. "delay time vs fidelity", Receiver 1 vs Receiver 2). **[Data]** — goal is to determine whether the asymmetry is statistical or reproducible, not to force the two lines to agree.
32. Remove titles from all published graphs. Review finding: helper defaults are correct, but the **actual embedded manuscript figures (1, 4, 6) still visibly contain titles** because of the filename mismatches in item "figure provenance" below — this is a regeneration/provenance problem, not a code-default problem.
33. Scaling-fidelity hardware figure needs: more data points, larger `M,N` **[Data]**, compressed x-axis, more distinct colors, and average/worst-case/full-spread receiver fidelity plotted as points (not just the mean). **Blocked on fixing the cohort-mismatch/provenance bug (new item 39) first** — do not add styling polish to a figure pooling incomparable backends.
34. Zenodo code release can be left to the very end.

### G. New items from PROJECT_REVIEW.md
35. **[HPC-sensitive]** Fix `results.py`'s mode-mislabeling bug (`"sampl" in mode or config.n_samples`) so execution mode is resolved once from what was *actually executed*, not from config defaults; record effective mode/sample-count/seed. Existing files are not touched by this fix.
36. **[HPC-sensitive]** Fix default result filenames to include a collision-safe suffix (job ID / array task ID / UUID) before any further parallel HPC submission; writes must not silently overwrite same-second results.
37. Generalize `broadcasting/fidelity.py::add_fidelity` to construct the inverse rotation from the actual target state (`Ry(-2·arccos(alpha))` then `Rz(2Φ)`), or explicitly validate/restrict non-equatorial inputs with a clear error, rather than silently misreporting fidelity.
38. Add a merge/reduction utility for SLURM array outputs (`hpc/run_experiment.py` currently writes one JSON per array task with a single `p` point; nothing assembles these into a sweep record).
39. Fix the Fig. 6 (hardware scaling) cohort-mismatch: stratify by backend/shots/optimization level explicitly, correct the caption to state the true multi-backend cohort, and do not infer controlled `N`-scaling from a mixed backend/shots dataset.
40. Fix figure/asset filename mismatches between what notebooks export and what the manuscript embeds; adopt one authoritative figure-manifest approach (generator script + input run IDs + config + output path + caption facts per figure).
41. Fix the Fig. 3 caption/label mismatch (`\ref{fig:circuit}` currently points at the unencoded circuit but is cited as illustrating the 3-stage QEC circuit).
42. Query and persist the actual backend `dt` per hardware run instead of a hardcoded `4e-3` µs/dt conversion; keep raw `dt`-unit values if historical calibration can't be established for older runs.
43. Deduplicate `results/qec513/` by job identity (two files share job `d82dopugbeec73allus0`) in analysis code — do not delete the duplicate file, just exclude it from repetition counts.
44. Add prior-art differentiation from critique §2.1 (Kumar & Pathak, *Quantum Inf. Process.* 23, 148 (2024)) — the manuscript currently omits this closely related IBM-hardware remote-state-preparation demonstration.
45. Align `hpc/run_experiment.py`'s default `alpha` with `ProtocolConfig`'s default (`1/√2`) for consistency going forward (does not affect already-recorded runs, which store their own `alpha`).
46. **[HPC-sensitive]** Avoid every SLURM array task independently `rsync`-ing the shared code directory concurrently (`hpc/slurm_broadcast.sh`); sync once (e.g. in the submission step or a single dependency job) rather than per-task.
47. Add regression/round-trip tests for `results.py` save/load covering exact runs, sampling runs (with explicit non-default `n_samples`/`seed`), and hardware runs — not just hardware sweeps as currently tested.
48. Document (or unify) the `alpha` type inconsistency: the numerical simulation API (`broadcasting/simulation.py`) takes real `alpha` with `beta=sqrt(1-alpha²)`, while `broadcasting/circuit.py`'s state preparation accepts complex `alpha` and uses its modulus.
49. Build a genuinely independent recovery/logical-channel oracle for tests (e.g. a binary-symplectic stabilizer-coset classification implemented without calling `five_qubit_recovery_kraus_operators`/`pauli_label_syndrome`), so the "independent validation" claim in the manuscript is accurate.
50. Add a short `README.md` (architecture, environment setup, how to run a small simulation, how to run tests, how to build the manuscript, and the distinction between the broadcasting protocol and the standalone `qec_testing.ipynb` memory benchmark); pin a tested dependency set.

---

## Phase 0 — Analytical core — 🟡 mostly done, 3 sub-items reopened

**Status:** Items 1 and 5 are done and verified (exact `p_L(p)` polynomial, corrected recovery-map
equation, algebra checked with `sympy`). Items 2, 3 (fully), and 4 are **reopened** — the previous
"DONE" label overclaimed this; the manuscript still only derives the `M=1,N=2` special case.

- [MS] **Item 1** ✅: Rewrite the QEC section around Eq. (31)–(33). Replace with the exact
  logical-channel polynomial `p_L(p) = 10p² − (200/9)p³ + (160/9)p⁴ − (128/27)p⁵`,
  `F_QEC = 1 − (2/3)p_L(p)`, and `p* = (3−√6)/4 ≈ 0.1376`. **Done.**
- [MS] **Item 5** ✅: Correct Eq. (36) to `V_Dec E_s† P_s` (`P_s = E_s P_C E_s†`); note that
  `broadcasting/simulation.py`'s exact path already implements this correct formula. **Done.**
- [MS] **Item 2, 4 (reopened)**: Add the general theorem for arbitrary `M,N` (not just `M=1,N=2`):
  full noiseless output `|ψ_target⟩^⊗N` with `Φ=Σθⱼ`; factorization
  `ρ_out = ⊗_ℓ D_pℓ(|ψ_target⟩⟨ψ_target|)` for independent (possibly unequal) per-receiver
  probabilities `p_ℓ`; `F_ℓ = 1-2p_ℓ/3`; `F_global = Π_ℓ(1-2p_ℓ/3)`, generalizing to `p_L(p_ℓ)` when
  QEC is enabled. `PROJECT_REVIEW.md` §2.1 supplies a complete, checkable proof sketch (Fourier
  projection → product-state factorization → Born-probability invariance → byproduct correction)
  that can be adapted directly; verify the covariance argument requires **phase-covariance under
  `U_n̄=diag(e^{iφ},1)`**, not mere diagonality in the computational basis (the current manuscript
  text at the `M=1,N=2` derivation conflates the two — fix that wording too).
- [MS] **Item 2 corollary**: Add the branch-invariance corollary replacing withdrawn item 12: every
  sender outcome `n̄` yields an identical post-correction receiver state under phase-covariant
  channels, so fixing/sampling one outcome in the exact simulator is exact, not approximate.
- [MS] **Item 3 (reopened, partial → complete)**: The `p=3/4` equal-fidelity point is mentioned but
  the *mechanism* for `p>3/4` isn't explained. Add: for `p∈(3/4,1]` the bare channel's Bloch
  contraction `η=1-4p/3` goes negative (state-inversion regime, `F_bare(1)=1/3`); the code's
  higher-weight-Pauli mixing damps this inversion (`p_L(1)=22/27`, `F_QEC(1)=37/81≈0.457>1/3`), so
  QEC is advantageous again past `p=3/4` — this is **not** a fault-tolerant threshold result, just
  an artifact of this channel convention past complete depolarization; say so explicitly, and verify
  `p_L(1)=22/27` algebraically (matches `logical_error_polynomial(1)` in code — confirm with a test).
- [Code] Add a test asserting `logical_error_polynomial(1) == 22/27` and `1 - 2/3*logical_error_polynomial(1) == 37/81`, to lock in the `p>3/4` regime numbers before they go in the manuscript.

## Phase 1 — Recovery-map tests & Monte Carlo accounting — 🟡 core items done, fast-path not pursued

**Status:** Items 6, 7, 8 are done and tested (92 tests passing). Item 9 is only partially reflected
in the manuscript (text now *describes* the accounting gap but doesn't measure it, and undercounts:
see below). Items 10–11 are **not being pursued** (user decision — see below); item 12 is
**withdrawn** (see Phase 0 — proven exact, not needed). Manuscript wording around 10-11 was too
generous ("... or, when only fidelity is required, accumulate the scalar per-trajectory fidelity
directly...") — **soften that sentence** to describe it as a possible future option, not an
available one, since it isn't being built.

- [Code] **Item 6** ✅: weight-one correction, trace preservation (over the **full 32-dim space**,
  stronger than originally planned "on the codespace"), closed-form-vs-brute-force polynomial match,
  break-even point, noiseless unit-fidelity, sampled-vs-exact match — all in
  [tests/test_qec_recovery.py](tests/test_qec_recovery.py). **Done.**
- [Code] **Item 49 (new)**: The brute-force oracle (`logical_error_probability_bruteforce`) currently
  calls `five_qubit_recovery_kraus_operators()` and `pauli_label_syndrome()` — i.e. it shares
  production code, so it is not a fully independent check. Add a second, genuinely independent
  oracle built from raw stabilizer matrix products / binary-symplectic classification (no shared
  helpers), and use *that* as the "independent validation" claim in the manuscript. Reproduce the
  full isotropic weight-distribution table (weight 2: 30/30/30 X/Y/Z; weight 3: 210 total incl. 60→I;
  weight 4: 270 total incl. 135→I; weight 5: 198 total incl. 45→I) as a test fixture.
- [Code] **Item 9 (accounting, corrected)**: Review finding: `depolarizing_channels_encoded`'s
  sampling branch retains **every** trajectory vector in a Python list before decoding
  (`trajectories.append(psi)`), so actual memory is `O(n_s·D + d_dec²)` for the list plus the
  post-hoc empirical density estimate, not the `O(D)`-per-trajectory streaming description in the
  manuscript. Either (a) refactor to stream — decode and discard each trajectory immediately,
  accumulating only the running `ρ̂` (or scalar fidelity) — or (b) if the list is kept for debugging,
  say so explicitly and report the real `O(n_s·D)` cost. Also note the *exact* (`"exact"` mode)
  bare-channel path uses full dense `D×D` matrix products per Pauli term (cubic-ish per-step work in
  `D`), not the quadratic local-contraction cost implied by the write-up — correct the wording or
  implement the cheaper local contraction.
- [Code] **Items 10, 11 — decided against, not being pursued (user instruction, 2026-09-08)**: the
  review's proposed 4-tier simulation hierarchy (closed form → logical Pauli-frame sampling →
  streaming physical Monte Carlo → dense encoded reference) is **not being built**. Only two tiers
  are actually needed and both already exist: the **closed-form** `logical_error_polynomial`/
  `F_QEC(p)` (Phase 0, done) for the analytical result, and the existing **dense/exact and
  Monte-Carlo-sampling** paths (`ExactBackend`/`SamplingBackend`, `depolarizing_channels_encoded`)
  for the numerics actually used to produce the manuscript's figures. The intermediate "logical
  Pauli-frame fast path" and "streaming physical Monte Carlo" tiers were speculative scalability
  improvements for larger `(M,N)` than this manuscript actually reports on, and are not worth the
  implementation/verification cost right now.
- [MS] Soften the Monte Carlo methodology section's "accumulate the scalar per-trajectory fidelity
  directly and skip the density-matrix estimate entirely" sentence to read as a possible future
  option rather than an available one, since it isn't being implemented.

## Phase 2 — Correctness & provenance bug fixes 🆕 (HPC-sensitive, do before further data reanalysis) — ✅ done

New phase inserted ahead of plotting/manuscript polish, per the review's recommended sequencing
("fix concrete data/API bugs before further investment"). All items here are code/analysis fixes;
**none require deleting or rewriting existing result files** (see HPC ground rules above).

- [Code] **Item 35** ✅: Fixed `results.py`'s mode-resolution logic — `backend_label` now depends
  only on the executing backend's reported `mode` string (`"sampl" in mode`), no longer on
  `config.n_samples` truthiness. Regression tests in
  [tests/test_results.py](tests/test_results.py) (`TestModeLabeling`) lock this in.
- [Code] **Item 36** ✅ **[HPC-sensitive]**: Added `_default_run_suffix()` to `results.py` — prefers
  `SLURM_JOB_ID`/`SLURM_ARRAY_TASK_ID` when present, else a short uuid — appended to auto-generated
  filenames. Only affects filenames generated when `filepath` isn't given explicitly; explicit
  `filepath=...` calls (used by hardware tau-sweep notebooks) are unaffected. Verified with
  `TestFilenameCollisionSafety` (two same-second calls produce distinct files).
- [Code] **Item 46** ✅ **[HPC-sensitive]**: `hpc/slurm_broadcast.sh`'s code sync is now guarded by a
  `flock` + "done" marker file, both on the shared scratch filesystem (not node-local `/tmp`, which
  isn't shared across compute nodes) so concurrently-starting array tasks perform the `rsync` exactly
  once instead of racing each other.
- [Code] **Item 38** ✅ **[HPC-sensitive]**: Added [scripts/merge_hpc_runs.py](scripts/merge_hpc_runs.py) —
  a read-only utility that groups per-task SLURM array JSON outputs by config fingerprint and merges
  each group into one multi-point sweep record; never modifies or deletes the source files. Verified
  on synthetic per-task files.
- [Code] **Item 37** ✅: `broadcasting/fidelity.py::add_fidelity` now takes a real `alpha` parameter
  (default `1/√2`) and builds `Rz(2Φ)` then `Ry(-2·arccos(alpha))`; proven or a general state
  `Rz` and `Ry` map the target to `|0>` up to global phase, so `P(0)` recovers the true fidelity
  `⟨target|ρ|target⟩` for *any* `ρ`, not just approximately — and reduces to the old
  `Rz(-φ)`+`H` circuit exactly (same measurement statistics) when `alpha=1/√2`, so all existing
  equatorial tests are unaffected. `broadcasting/backend.py`'s `HardwareBackend.run()` and
  `run_tau_sweep()` now pass `config.alpha` through. Verified in
  [tests/test_structured_circuits.py](tests/test_structured_circuits.py).
- [Code] **Item 45** ✅: `hpc/run_experiment.py`'s default `alpha` changed to `1/√2`, matching
  `ProtocolConfig`. Already-recorded runs keep their own saved `alpha`; unaffected.
- [Code] **Item 43** ✅: `qec_testing.ipynb`'s "Compare Saved QEC Sweeps" cell now deduplicates by
  `job_id` (skips `..._163539.json`, reporting it as a duplicate of `..._163257.json`, without
  deleting either file) and no longer silently defaults a missing `use_qec` field to `True` — it's
  now labeled `"QEC?"` (unknown) since none of the six legacy files actually recorded that field.
- [Code] **Item 42** ✅: `HardwareBackend.run()`/`run_tau_sweep()` now record
  `backend.target.dt` in the saved metadata (`"dt"` key) for every new hardware run. Existing
  records are untouched; the `4e-3` hardcoded conversion in the notebooks remains as-is for now
  (still correct for existing Kingston/Marrakesh/Fez records) — updating the notebooks to *read*
  the newly-recorded `dt` instead of hardcoding it is still open (Phase 3/8 follow-up once enough
  new runs carry the field).
- [Code] **Item 48**: Documented (not unified) — `add_fidelity`'s docstring now explicitly notes the
  real/complex `alpha` convention mismatch with `circuit.py`/`state_preparation.py`.
- [Code] **Item 47** ✅: Added [tests/test_results.py](tests/test_results.py) with round-trip tests
  for exact runs, sampling runs (explicit non-default `n_samples`/`seed`), filename collision safety,
  and `dt` propagation.

## Phase 3 — Plotting, figure provenance & data-cohort fixes (no data needed) — ✅ done


- [Code] **Item 40** ✅: `visualizations.ipynb`'s QEC-crossover and hardware-scaling cells, and
  `run_broadcast.ipynb`'s sampling-convergence cell, now save directly to the **exact filenames the
  manuscript embeds** (`manuscript/qec vs no qec vs sampling.png`,
  `manuscript/fidelity scaling hardware.png`, `manuscript/mc_sampling_convergence.png`) in addition to
  their existing `figures/` exports, so re-running them actually updates what's embedded. A full
  figure-manifest script (one generator per figure with explicit input run IDs) is still a
  nice-to-have follow-up; the immediate provenance breakage (re-running ≠ updating the manuscript) is
  fixed for these three figures. The remaining manually-named files in `manuscript/`
  (`delay time vs fidelity 121 opt3.png`/`opt0`, `fidelity between receivers.png`, `qec fidelity.png`)
  don't correspond to a single canonical generating cell — each is a manually-selected run — so they
  weren't remapped; use `save_figure(fig, Path("manuscript") / "exact name.png")` directly when you
  regenerate one of those.
- [Code] **Item 39** ✅: The hardware-scaling cell now groups runs by `(backend, shots)` via the new
  `broadcasting/validation.py::group_by_cohort` and prints the cohort breakdown explicitly (confirmed
  against real data: `ibm_kingston`/4096&10000, `ibm_marrakesh`/4096&8192, `ibm_fez`/4096&8192 — 6
  distinct cohorts across 13 hardware runs) instead of silently pooling them. It also now verifies the
  nearest sweep value is actually `0` before calling it "tau=0" (skips and prints a message otherwise),
  and deduplicates by `job_id` first via the new `dedupe_by_job` helper.
- [Code] **Item 32**: Once the figures are regenerated via the fixed cells above, titles are stripped
  by `save_figure`'s existing default — verified the new hardware-scaling render (see below) has none.
- [Code] **Item 30** ✅: The sampling-convergence cell now runs 5 seeds × 8 sample sizes, fits
  `log(error) = slope·log(n) + intercept` by linear regression, and reports the fitted exponent with
  its standard error (expected ≈ −0.5), plotted as a genuine log-log fit line instead of an assumed
  `1/√n` overlay anchored to one point. Smoke-tested against the real backend.
- [Code] **Item 33 (non-data parts)** ✅: hardware-scaling plot now uses `tab10` (colorblind-safe,
  keyed by `M`) instead of `magma`, integer-only compressed x-axis (`ax.set_xticks`/`set_xlim` on the
  actual `N` values present), and plots mean (with min/max spread as error bars) **and** worst-receiver
  fidelity as a separate marker per point — verified visually against the real 13-run dataset
  (see "What changed" note below for a rendered example).
- [Code] ✅: Added [broadcasting/validation.py](broadcasting/validation.py)
  (`find_duplicate_jobs`, `group_by_cohort`, `dedupe_by_job`) with
  [tests/test_validation.py](tests/test_validation.py), reused by the hardware-scaling cell above.

## Phase 4 — Manuscript framing, terminology & prior art (no data needed) — 🟡 mostly done

- [MS] **Item 20, 21** ✅: Reworded the introduction and protocol-description "circumvented" language
  to state the theorems' hypotheses simply don't apply (restricted, sender-known state family +
  prior entanglement), not that they're violated/circumvented. Added the precise privacy statement:
  the classical broadcast reveals only `Φ=Σθⱼ`, independent of any individual `θⱼ`.
- [MS] **Item 22** ✅: Conclusion no longer calls the protocol a "useful cryptographic primitive";
  states the specific privacy property instead and explicitly disclaims Byzantine-agreement /
  device-independent security claims.
- [MS] **Item 13, 14, 15** ✅: Fig. 6 interpretation rewritten to the defensible claim (accumulated
  independent hardware noise as circuit size grows is sufficient to explain the decline; correlated
  noise remains an open, unmeasured possibility). Fig. 2 explicitly flagged as a standalone
  encoded-memory benchmark, distinct in scope from the unencoded broadcasting circuits behind
  Figs. 5/6 — no combined QEC-broadcasting circuit has been benchmarked.
- [MS] **Item 17, 18 (corrected)** ✅: Methods section no longer lists dynamical decoupling as
  something optimization levels 0–3 do; states DD is a separate, explicitly-scheduled pass not used
  in the reported runs, and separately notes optimization level is distinct from Runtime error
  mitigation (Estimator-only, not used by our Sampler-based execution) — without proposing the
  withdrawn `resilience_level` option.
- [MS] **Item 19** — 🟡 honestly softened, not fully resolved: replaced the false "staggered DD"
  causal claim with an explicit statement that the drop-out periodicity is only a visual
  observation, not yet quantified (no autocorrelation/periodogram analysis has actually been run
  against saved delay-sweep data yet — that analysis helper is still Phase 5/8 future work; this
  phase only removed the unsupported claim rather than replacing it with a real quantification).
- [MS] **Item 41 (new)** ✅: Removed the incorrect `Fig.~\ref{fig:circuit}` cross-reference from the
  QEC-stages paragraph (that figure shows the *unencoded* circuit) rather than pointing at the wrong
  figure; no new QEC-circuit figure was added (still open if one is wanted).
- [MS] **Item 23** ✅: Added the original 1996 no-broadcasting theorem citation (Barnum, Caves, Fuchs,
  Jozsa, Schumacher, PRL 76, 2818) alongside the 2007 generalization.
- [MS] **Item 44 (new)** ✅: Added prior-art paragraph citing Kumar & Pathak (verified via arXiv:2305.00389
  abstract — confirms noise modeling + IBM proof-of-principle claims from the critique) and
  explicitly contrasted three distinguishing contributions (Dicke resource family, exact logical
  polynomial/break-even, dynamic-circuit QEC integration).
- [MS] **Items 24–27, 28** — ❌ still open: invalid-outcome-handling statement, decoder qubit-ordering
  clarity, circuit-scheduling statement, and the full copyedit pass are not yet done.

## Phase 5 — Dynamical decoupling & optimization-vs-mitigation code (corrected scope)

- [Code] **Item 17 (corrected, superseded 2026-09-XX)** ✅: The original plan assumed a custom
  `PassManager` (`ALAPScheduleAnalysis` + `PadDynamicalDecoupling`) would be needed and that
  Runtime's built-in DD toggle might not exist for `SamplerV2`/might not compose with dynamic
  circuits. **This was wrong on the first point** — confirmed against the
  `qiskit-ibm-runtime` 0.49 docs that `SamplerOptions.dynamical_decoupling` is a genuine, supported
  `SamplerV2` suboptions object (`enable`, `sequence_type`, `scheduling_method`,
  `extra_slack_distribution`, `skip_reset_qubits`), distinct from `resilience_level`
  (Estimator-only, correctly not used here). Implemented as a manual yes/no toggle:
  `HardwareBackend(..., dynamical_decoupling: bool = False)`, applied via a new `_sampler()` helper
  (`broadcasting/backend.py`) that sets `sampler.options.dynamical_decoupling.enable` before
  `run()`/`run_tau_sweep()`; recorded in saved run metadata. Whether this composes cleanly with our
  dynamic (mid-circuit-measurement + feedforward) circuits on real hardware is **still unverified
  empirically** — the API accepts the option, but actual behavior on a dynamic circuit should be
  checked against the first real DD-on hardware run.
- [Code] **Item 18 (withdrawn as originally scoped)**: Do **not** add a `resilience_level` parameter
  to `HardwareBackend` — it executes via `SamplerV2`, which doesn't accept it. If error mitigation is
  ever wanted for an Estimator-based measurement, scope that separately.
- [Code] Add an autocorrelation/periodogram helper for fidelity-vs-delay traces (Phase 4, item 19),
  usable directly on existing delay-sweep result files ✅: implemented as
  `autocorrelation_from_run`/`periodogram_from_run`/`plot_periodicity_comparison` in
  [broadcasting/plotting.py](broadcasting/plotting.py) (uses `scipy.signal.periodogram`; `scipy`
  added to `requirements.txt`). Wired into `run_broadcast.ipynb`'s new **Optional Figure 5 DD
  Periodicity Comparison** cell (`RUN_DD_COMPARISON`), which runs the `M=1,N=2` no-QEC tau sweep
  twice on one fixed backend (DD off, DD on) and compares.


## Phase 6 — Structured hardware circuit redesign (non-data prerequisite for Phase 8) — decision made: keep generic synthesis

**Update (2026-09-08, user decision):** a structured Dicke-state resource-prep circuit was built,
tested, and run on real hardware (see revision 5/4 notes below) as a genuine A/B test against
`qc.initialize`. The result: it performed *worse* on the one real hardware comparison run (0.872/0.794
vs. 0.909/0.822 fidelity). Given that result, **the structured-prep attempt has been reverted** —
`structured_state_prep`, `use_structured_prep`, and the comparison script/notebook cells are removed.
`qc.initialize` (generic isometry synthesis) is kept as the sole resource-state preparation path, and
the existing Gram–Schmidt `[[5,1,3]]` decode unitary is kept as-is — **no structured Clifford decoder
will be pursued either**. Item 16 (both the prep and decoder halves) is now closed as "decided
against" rather than "deferred"/"partial":

- [Code] **Item 16 (prep)** — ❌ **reverted, not pursued**: `structured_state_prep` was implemented,
  tested (exact statevector match to `build_initial_statevector`), and hardware-validated, but the
  real-hardware A/B result did not support it — reverted in favor of keeping `qc.initialize`.
- [Code] **Item 16 (decoder)** — ❌ **decided against, keeping Gram-Schmidt**: no structured Clifford
  decoder was built or will be built; `broadcasting/qec_513.py::five_qubit_decode_gate`'s
  Gram-Schmidt construction remains the only decoder. (Originally deferred pending verification
  difficulty; now a firm decision given the prep-side result above — not worth revisiting without
  new evidence that generic synthesis is actually the bottleneck.)
- [Code] **Item 25 (corrected approach)** ✅ *(kept — unrelated to the prep/decoder reversion)*:
  Implemented in `broadcasting/circuit.py` as `linear_feedforward=True` (now the default) — `M·nq`
  single-bit-conditioned phase rotations replacing the `(N+1)^M`-branch loop, using the
  additive-phase-decomposition identity `Σ_j n_j = Σ_{j,b} bit_{j,b}·2^b`. Verified to reproduce the
  old exponential feedforward's fidelities within shot noise for `(M,N)∈{(1,1),(1,2),(2,2)}`
  ([tests/test_feedforward.py](tests/test_feedforward.py)). The old exponential path is kept
  (`linear_feedforward=False`) for direct A/B comparison. **Behavior change, as anticipated**: for an
  *invalid* sender outcome (register value `>N`), the linear version applies the same linear phase
  formula rather than skipping correction (matching the review's explicitly endorsed design in
  §3.1) — documented in the function's docstring. This is a classical-control simplification
  independent of the encoder/decoder question and is unaffected by the reversion above.
- [Code] `ProtocolConfig` kept `linear_feedforward` (the `use_structured_prep` field was removed).
- [Code] **Item 24**: Add explicit handling/reporting of invalid sender-qudit outcomes in
  results-processing code, documenting the current no-correction behavior and whether it should
  change. — still open.

## Phase 7 — Reproducibility & configuration hygiene 🆕

- [Code] **Item 50** ✅: Added [README.md](README.md): architecture overview, repo structure, setup
  (venv + `pip install -r requirements.txt`), IBM Quantum account setup (new
  `channel="ibm_quantum_platform"` API), how to run tests, the `ProtocolConfig`/`Backend` (including
  `HPCBackend`) architecture, a full walkthrough of every `run_broadcast.ipynb` `MODE`, an explicit
  figure-by-figure table mapping each manuscript figure to the notebook mode/cell that produces its
  data, the HPC (`MODE="hpc"` + `scripts/merge_hpc_runs.py`) workflow, manuscript build commands, and
  the data-safety policy. Did not pin exact dependency versions (the repo has no lockfile and the
  installed versions here differ from the review's environment — Qiskit 2.5.2/Aer 0.17.2/Runtime
  0.49.0 vs. the review's 2.2.1/0.17.2/0.42.0 — recording *a* tested set precisely would go stale
  immediately; `requirements.txt` is left unpinned deliberately).
- [Code] Register the existing `slow` pytest marker (currently causes a warning) and separate
  quick mathematical tests from expensive integration checks. — still open.
- [Code] Make one configuration source authoritative across notebooks, CLI, backend, and serializer
  (builds on item 45); document the two meanings of `p_list` (backend-level sweep points vs.
  low-level per-receiver probabilities) and whether reduced states describe only the last sweep
  point. — still open.
- [Code] Consolidate duplicated logical-basis/stabilizer definitions across `qec_513.py` and
  `simulation.py` carefully — **keep the independent oracle from item 49 separate** even after
  consolidation, and add explicit native-qudit/little-endian conversion tests between the two state
  representations (`simulation.py`'s numerical path vs. `circuit.py`/`qec_513.py`'s Qiskit
  little-endian circuit path). — still open.

## Phase 8 — New data collection **[Data]**

Everything here requires new simulation or hardware runs; do this last, after Phases 0–7 land.
**Reuse existing data first** — item 14 (global/worst-case/covariance analysis) is now implemented as
a real cell in `visualizations.ipynb` ("Joint/Global Fidelity And Receiver Covariance"), which reads
directly from existing saved joint-receiver bitstrings with no new collection needed; verified against
`run_20260518_120232.json` at `τ=0`, reproducing the review's numbers exactly: mean local fidelity
0.9099, worst-receiver 0.8941, global/all-zero fidelity 0.8493, product-of-locals 0.827668, receiver
success-covariance 0.021634. Run that reanalysis across the other 12 hardware runs before deciding
what new data is actually needed, and keep the collection matrix small/bounded (a few representative
sizes, targeted ablations).

- [Data] **Item 31**: Re-run the `M=1,N=2` fidelity-vs-delay hardware experiment with enough
  additional shots/repeats that Receiver 1 vs. Receiver 2 asymmetry can be distinguished from shot
  noise. Goal is to determine whether it's statistical or reproducible — not to force agreement.
- [Data] **Item 33/39**: Collect additional `(M,N)` scaling data points **on a single consistent
  backend/shot-count** (fixing the Phase 3 cohort issue) rather than mixing backends as before;
  include larger protocol sizes than currently available.
- [Data] **Ablation series**: Run the structured-circuit ablation (Phase 6) — separately add resource
  prep, sender phase/Fourier ops, delay, feedforward, syndrome extraction, correction, decoding — to
  localize fidelity loss with measured gate counts, not estimates.
- [Data] **DD ablation**: Only pursue explicit no-DD / standard-DD / staggered-DD variants (Phase 5)
  if the reanalysis of existing delay-sweep data (Phase 5's autocorrelation helper) actually shows a
  periodic structure worth explaining; an inconclusive result is an acceptable outcome.
- [Data] **Metadata**: Archive job IDs, physical qubit layout, gate counts, depth, scheduled
  duration, readout errors, two-qubit error rates, backend `dt`, and contemporaneous `T1`/`T2` for
  every new hardware run — the current saved schema only stores the receiver fidelity register, not
  full shot-aligned classical outputs, so invalid sender-outcome frequencies can't be recovered from
  existing files; make sure new runs save enough to answer that question directly.
- [Data] Interleave/randomize delay settings within a job where scheduling permits, to separate
  genuine delay effects from time-ordered calibration drift.

## Phase 9 — Zenodo / release (last, per request)

- Resolve the coauthor placeholder, finalize the Zenodo deposit, and ensure the deposited code
  includes the Phase 1 recovery-map tests (plus the independent oracle from item 49) so
  reviewers/readers can verify correctness themselves. Reproducibility bookkeeping (Phase 7) should
  already be in place by this point so the deposit is a packaging task, not new work.

---

---

## What changed in revision 6 — reverted structured prep, trimmed Phase 1, README, joint-fidelity cell

At the user's request:
- **Removed `Untitled-1.ipynb`** — confirmed via diff to be a stale, untracked duplicate of an earlier
  version of `run_broadcast.ipynb` with no unique content.
- **Reverted the structured resource-state prep ("the other attempt")**, keeping generic `qc.initialize`
  as the sole encoder and the Gram-Schmidt `[[5,1,3]]` decode gate as the sole decoder — see the
  updated Phase 6 section above for the reasoning (the one real hardware A/B test showed structured
  prep performing *worse*, so it isn't worth carrying forward). Removed
  `structured_state_prep`/`use_structured_prep` from `circuit.py`/`protocol.py`/`backend.py`, deleted
  `scripts/submit_structured_test.py` and `tests/test_structured_circuits.py`, removed the
  corresponding notebook section, and replaced the test coverage with
  [tests/test_feedforward.py](tests/test_feedforward.py) (the unrelated, still-kept
  `linear_feedforward` improvement). 114/114 tests passing (down from 146 — the removed count matches
  the deleted structured-prep tests exactly, no unrelated coverage lost).
- **Trimmed Phase 1's tiered Monte Carlo plan** per instruction ("don't bother with the Tier 2 fast
  path, remove tiers not needed") — the speculative 4-tier hierarchy is dropped; only the closed-form
  result (done) and the existing dense/Monte-Carlo methods (already in production use) remain.
- **Fixed a real bug found while cleaning up**: the Configuration cell in `run_broadcast.ipynb` had a
  scrambled/merged line (`print(...)for i, sample in ...`) left over from an earlier multi-part edit
  in a previous revision — caught by compiling every notebook cell's source and fixed. All three
  notebooks (`run_broadcast.ipynb`, `visualizations.ipynb`, `qec_testing.ipynb`) now compile cleanly
  cell-by-cell (verified with a script, not just visual inspection).
- **Added [README.md](README.md)** (Phase 7, item 50) — architecture, setup, IBM account setup (new
  `ibm_quantum_platform` channel), the `ProtocolConfig`/`Backend` pattern, a full `run_broadcast.ipynb`
  walkthrough, and an explicit table mapping every manuscript figure to the mode/cell that produces its
  data.
- **Added a real joint-fidelity/covariance analysis cell** to `visualizations.ipynb` (previously this
  was only described as "computable" in the plan, via an ad-hoc terminal script, not implemented as
  reusable notebook code) — computes mean/worst/global fidelity and pairwise receiver covariance
  directly from any saved hardware run's joint counts; verified to reproduce the exact previously
  quoted numbers for `run_20260518_120232.json`.

---

## What changed in revision 5 — HPCBackend + Phase 4 manuscript edits

**Architecture note (user request):** the codebase already followed the requested OOP pattern for
three of four execution paths (`ProtocolConfig` as the "senders/receivers/error-correction/shots/
sweep" input object, handed to a `Backend` ABC subclass), but had no formal HPC backend class — HPC
runs went through a separate procedural script instead. Added `broadcasting.backend.HPCBackend`, a
fourth `Backend` subclass that builds (and, if `submit=True`, launches) the `sbatch` command for
`hpc/slurm_broadcast.sh` from the *same* `ProtocolConfig` used by `ExactBackend`/`SamplingBackend`,
so all four backends are now genuinely polymorphic and interchangeable from the notebook's
perspective. Details:
- `HPCBackend(mode, script_path, *, array, concurrency, submit)` — `mode` is explicit (`"exact"` or
  `"sampling"`), not inferred from `config.n_samples` truthiness (repeating that inference would have
  reintroduced the exact bug fixed in Phase 2's item 35).
- Extended `hpc/slurm_broadcast.sh` to forward `ALPHA`/`THETAS`/`OUTCOMES`/`SEED`/`P_MIN`/`P_MAX`
  (previously only `MODE`/`M`/`N`/`P_STEPS`/`USE_QEC` were passed through), so `HPCBackend` has full
  parity with `ProtocolConfig`.
- `results.py::save_run` gained an `hpc_submission` experiment type (a job-submission receipt with
  empty fidelities, not a completed sweep) so `HPCBackend` results don't get mislabeled as completed
  `aer_exact` runs.
- Wired into `run_broadcast.ipynb` as `MODE = "hpc"` (alongside the existing modes), with `HPC_MODE`/
  `HPC_SUBMIT`/`HPC_ARRAY`/`HPC_CONCURRENCY` configuration variables; `HPC_SUBMIT` defaults to `False`
  (only builds/prints the `sbatch` command — actually submitting requires running from a machine with
  `sbatch` on PATH, i.e. the HPC login node, which this fix was verified without doing).
- 6 new tests in `tests/test_backend.py` (mode validation, command construction, array-range
  formatting, submit=False never touching `subprocess`, submit=True parsing the job ID). 146/146
  tests passing throughout.

**Cleanup, per user request:** removed redundant/duplicate validation that had accumulated across the
structured-circuit comparison code (notebook cells and `scripts/submit_structured_test.py`) — dropped
the `N`-in-`{1,2}` pre-checks that duplicated validation already inside `structured_state_prep`,
dropped the `linear_feedforward` flag from the comparison (relies on its own default), dropped the
fake-backend transpile side-comparison, and switched hardware submission to `HardwareBackend`'s
built-in least-busy selection instead of a hardcoded backend name. Genuinely necessary validation
(the `alpha` range check in `add_fidelity`, the `NotImplementedError` inside `structured_state_prep`)
was kept, since those catch real correctness bugs found this session.

**Real preliminary hardware result** (requested run, executed on `ibm_marrakesh`, whichever backend
was least busy at the time): `M=1,N=2`, 4096 shots each —

| Circuit | Receiver 0 | Receiver 1 |
|---|---:|---:|
| generic | 0.9094 | 0.8215 |
| structured | 0.8723 | 0.7937 |

The structured circuit did *worse* on this single real run — opposite to the Phase 6 hypothesis. One
job pair, no repetition/error bars — not strong evidence either way, but a reminder that the
structured-prep benefit needs the proper ablation series (Phase 8), not just the local gate-count
comparison, before it's treated as established.

**Phase 4 (manuscript framing)** — see the Phase 4 section above for what's done; verified the
manuscript still compiles cleanly (`pdflatex` + `bibtex`, no undefined citations/references) with the
two new bibliography entries (`barnum1996noncommuting`, `kumar2024multiparty` — the latter's arXiv
identity independently confirmed via `arxiv.org/abs/2305.00389` before citing it).

---

## What changed in revision 4 — Phase 2 closed out, Phase 3 done, and a real blocker fixed

Finished Phase 2's remaining `[HPC-sensitive]` items and completed Phase 3 in full:

- **Phase 2 closeout**: `hpc/slurm_broadcast.sh`'s code sync is now `flock`-guarded (once per array
  submission, not once per task); added [scripts/merge_hpc_runs.py](scripts/merge_hpc_runs.py) to
  assemble per-task SLURM outputs into one sweep record; `qec_testing.ipynb`'s sweep-comparison cell
  now deduplicates by `job_id` and no longer defaults a missing `use_qec` field to `True`.
- **Phase 3 (figure provenance, cohort mismatch, convergence fit)**: see the Phase 3 section above —
  all items done, verified against the real 13-hardware-run dataset and smoke-tested against the
  real simulation backends.

**Unplanned but urgent fix:** while testing the preliminary hardware script from revision 3, actually
attempting to run it surfaced a real, immediate blocker — `run_broadcast.ipynb` used
`QiskitRuntimeService(channel="ibm_quantum", instance="ibm-q/open/main")`, but the installed
`qiskit-ibm-runtime` (0.42.0) has removed the `"ibm_quantum"` channel entirely (only
`"ibm_quantum_platform"`, `"ibm_cloud"`, `"local"` remain). This would have blocked *any* hardware
submission from this notebook. Fixed both call sites to `QiskitRuntimeService(name="mprest1")`,
matching the already-working pattern in `qec_testing.ipynb` and `scripts/submit_structured_test.py`
(both already used the modern named-saved-account API and were unaffected). Verified the fix
authenticates successfully and can query `service.least_busy(...)` — no hardware job was submitted in
the process of verifying this.

**Cleanup + first real hardware comparison:** simplified the structured-vs-generic comparison code
(notebook cells and `scripts/submit_structured_test.py`) — removed redundant `N`-validation that
duplicated checks already done inside `structured_state_prep`, dropped the `linear_feedforward`
flag from the comparison (it now just relies on its own default of `True`), dropped the fake-backend
transpile side-comparison, and switched hardware submission to `HardwareBackend`'s built-in
least-busy selection (`backend_name=None`) instead of a hardcoded backend name.

Ran the actual preliminary hardware comparison (`M=1, N=2`, `2×4096` shots, `ibm_marrakesh`,
optimization level 3):

| Circuit | Receiver 0 fidelity | Receiver 1 fidelity |
|---|---:|---:|
| generic (`qc.initialize` + exponential feedforward) | 0.9094 | 0.8215 |
| structured (Dicke prep + linear feedforward) | 0.8723 | 0.7937 |

**Honest result: the structured circuit did *worse* on this single real run**, opposite to the
hypothesis motivating Phase 6. This is one job pair on one backend at one point in time (no error
bars, no repetition, no isolation of which sub-circuit change is responsible) — not strong evidence
either way, but it means the structured-prep benefit is not a given and needs the proper ablation
series (Phase 8) rather than being assumed from the local gate-count comparison alone. Saved as
`results/run_20260908_132728_4fc6f552.json` (generic) and `results/run_20260908_132738_ef85f542.json`
(structured) using the new collision-safe filenames.

---

## What changed in revision 3 — preliminary hardware test ready to run

At the user's request, Phase 2 (correctness/provenance bug fixes) and the non-decoder parts of
Phase 6 (structured circuits) were implemented so a **preliminary hardware comparison could be
prepared now**, ahead of the rest of the plan. Nothing was submitted to real IBM hardware — that
step is left to the user, per the script's design (see below).

**Code changes** (133/133 tests passing, including 20 new tests):
- `broadcasting/results.py`: mode-mislabeling fix (item 35), collision-safe filenames (item 36).
- `broadcasting/fidelity.py`: generalized `add_fidelity` for arbitrary real `alpha` (item 37),
  proven to reduce to the exact old behavior at `alpha=1/√2` (no regressions).
- `broadcasting/backend.py`: passes `config.alpha` through to `add_fidelity`; records `backend.target.dt`
  in saved metadata (item 42).
- `hpc/run_experiment.py`: default `alpha` aligned with `ProtocolConfig` (item 45).
- `broadcasting/circuit.py`: new `structured_state_prep()` (Dicke-state prep for `N∈{1,2}`, item 16
  partial) and `linear_feedforward` bit-conditional byproduct correction (item 25), both opt-in via
  new `ProtocolConfig` fields `use_structured_prep`/`linear_feedforward` (default: old behavior
  preserved for `use_structured_prep`, new linear behavior is now default for `linear_feedforward`
  since it's strictly cheaper and proven equivalent for valid outcomes).
- New tests: [tests/test_results.py](tests/test_results.py) (round-trip/collision safety),
  [tests/test_structured_circuits.py](tests/test_structured_circuits.py) (structured-prep exact
  match to reference statevector; linear-vs-exponential feedforward equivalence).

**Preliminary test script:** [scripts/submit_structured_test.py](scripts/submit_structured_test.py).
Run with no arguments for a **local-only** sanity check (noiseless Aer fidelity check + transpiled
gate-count comparison against `FakeBrisbane`, no IBM account needed):

```
"/path/to/qiskit-env/bin/python" scripts/submit_structured_test.py
```

To actually submit to hardware (uses your saved `QiskitRuntimeService` account, small shot count by
default), you must explicitly pass `--submit`:

```
python scripts/submit_structured_test.py --submit --backend ibm_kingston --shots 2000
```

**Honest preliminary finding from the local-only check** (not yet hardware-validated): for `M=1,N=2`
transpiled against `FakeBrisbane`, the structured circuit's depth/two-qubit-gate-count improvement
over `qc.initialize` was **modest** (89→81 depth, 18→17 two-qubit gates), not the dramatic
"30-60+ CNOTs" reduction the review speculated for this specific small case — `qc.initialize`'s
generic synthesis turned out to be less wasteful than guessed for `N=2`. This is exactly the kind of
number Phase 6 asked to have *measured rather than estimated*; it may still be that larger `N` (once
structured prep is generalized) shows a bigger gap, or that the real hardware fidelity improvement
(distinct from raw gate count, e.g. via better qubit-layout locality) is more significant than the
transpiled gate count alone suggests — that's exactly what the preliminary hardware run should tell
us next.

---

## Notes on where things already look correct
- `broadcasting/plotting.py` already defaults `show_title=False` and has a `clear_titles`/`save_figure`
  helper that strips titles — the remaining title problem is stale exported PNGs (Phase 3), not the
  plotting code itself.
- The exact-mode recovery implementation in `broadcasting/simulation.py::qec_recover_and_decode`
  already applies the mathematically correct Kraus operators (equivalent to `V_Dec P_C E_s`).
- The current "exact" simulator's practice of fixing one sender-measurement outcome is **exact**, not
  an approximation to fix (see withdrawn item 12 in Phase 0/1) — this is a correction to revision 1
  of this plan, not to the manuscript, which never made the opposite claim.
- All 8 saved exact-simulation runs and the encoded-QEC hardware memory-benchmark's 15 injected
  weight-one Pauli errors already agree with the analytical fidelities/expected recoveries per the
  review's spot-checks — this supports keeping the existing simulation datasets rather than assuming
  the pre-fix manuscript equation error corrupted them.

