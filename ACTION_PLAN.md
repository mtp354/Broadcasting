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

## Phase 1 — Recovery-map tests & tiered simulation strategy — 🟡 core items done, fast-path deferred

**Status:** Items 6, 7, 8 are done and tested (92 tests passing). Item 9 is only partially reflected
in the manuscript (text now *describes* the accounting gap but doesn't measure it, and undercounts:
see below). Items 10–11 are unimplemented; item 12 is **withdrawn** (see Phase 0 — proven exact, not
needed). Manuscript wording around 10-11 was too generous ("... or, when only fidelity is required,
accumulate the scalar per-trajectory fidelity directly...") — **soften that sentence** to describe it
as a recommended future option, not an available one, until it's actually implemented.

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
- [Code] **Items 10, 11 (Tier 2/streaming fast path)** — formalize as a 4-tier simulation hierarchy
  per the review, and implement Tiers 1–2 as the follow-up work package:
  1. **Tier 1 — closed form, O(1):** `F_bare(p)=1-2p/3`, `F_QEC(p)=1-(2/3)p_L(p)` (done, Phase 0).
  2. **Tier 2 — logical Pauli-frame sampling, O(N):** sample logical Paulis directly from
     `{1-p_L(p), p_L(p)/3, p_L(p)/3, p_L(p)/3}` on the unencoded `(N+1)^M·2^N` state. This should
     become the default path for the independent-depolarizing-noise case explored in this paper.
  3. **Tier 3 — streaming physical Pauli Monte Carlo, O(D) peak memory:** sample physical Paulis,
     look up syndromes via `pauli_label_syndrome`, apply `K_s`, accumulate scalar fidelity on the fly
     without retaining trajectory vectors or building `ρ̂`. This is the corrected version of the
     current sampling path.
  4. **Tier 4 — dense encoded density matrix, O(D²):** keep as the small-system (`M≤1,N≤2`) reference
     used to validate Tiers 1–3, exactly as it's used today.
- [MS] Rewrite the Monte Carlo methodology section once Tiers 2–3 exist, replacing the "available
  option" wording with an accurate description of what's implemented and what's the recommended
  default for this noise model.

## Phase 2 — Correctness & provenance bug fixes 🆕 (HPC-sensitive, do before further data reanalysis)

New phase inserted ahead of plotting/manuscript polish, per the review's recommended sequencing
("fix concrete data/API bugs before further investment"). All items here are code/analysis fixes;
**none require deleting or rewriting existing result files** (see HPC ground rules above).

- [Code] **Item 35**: Fix `results.py`'s mode-resolution logic to record what was *actually executed*
  (resolve backend mode once, from the executing backend object, not from `config.n_samples`
  truthiness) and serialize the effective mode/sample-count/seed. Add round-trip tests (**item 47**)
  for exact and sampling runs, not just hardware sweeps.
- [Code] **Item 36, 46 [HPC-sensitive]**: Add a collision-safe filename suffix
  (`SLURM_JOB_ID`/`SLURM_ARRAY_TASK_ID`/uuid fallback) to `results.py`'s default filename generation.
  Test on a throwaway `--array=0-1` dry run before using in a real submission. Separately, fix
  `hpc/slurm_broadcast.sh` so the code `rsync` happens once (e.g. before submitting the array, or in
  a single setup job) instead of once per concurrent array task.
- [Code] **Item 38 [HPC-sensitive]**: Add `scripts/merge_hpc_runs.py`: a read-only utility that
  assembles per-task SLURM array JSON outputs (each a single `p` point) into one sweep record for
  plotting, without modifying the source per-task files.
- [Code] **Item 37**: Generalize `broadcasting/fidelity.py::add_fidelity` for arbitrary real `alpha`
  (`Ry(-2·arccos(alpha))` then `Rz(2Φ)`, reducing to the current equatorial circuit when
  `alpha=1/√2`), or add explicit validation that rejects/warns on non-equatorial `alpha` until fixed.
  Add tests at `alpha∈{0,1}` (computational-basis endpoints) and a few interior values.
- [Code] **Item 45**: Align `hpc/run_experiment.py`'s default `alpha` with `ProtocolConfig`
  (`1/√2`), leaving already-recorded runs' own saved `alpha` untouched.
- [Code] **Item 43**: Add a small dedup-by-job-ID step in analysis code for `results/qec513/`
  (exclude the confirmed duplicate `..._163539.json` from repetition counts), without deleting the
  file.
- [Code] **Item 42**: Query `backend.target.dt` (or the equivalent Runtime metadata) and persist it
  per hardware run going forward; keep the hardcoded `4e-3` only as a documented fallback for
  existing Kingston/Marrakesh/Fez records where it's verified correct.
- [Code] **Item 48**: Document the `alpha` real-vs-complex convention mismatch between
  `broadcasting/simulation.py` (real `alpha`) and `broadcasting/circuit.py` (complex `alpha`,
  modulus used) in both modules' docstrings, or unify if feasible without breaking either call site.

## Phase 3 — Plotting, figure provenance & data-cohort fixes (no data needed)

- [Code] **Item 40**: Adopt a figure-manifest approach — one small script/notebook cell per figure
  that names its generator, input run IDs, configuration, output path, and caption facts — and make
  it the single source that writes into `manuscript/` (or `figures/`) under the **exact filenames the
  manuscript embeds**, fixing the `mc_sampling_convergence.png`/`qec vs no qec vs sampling.png`/
  `fidelity scaling hardware.png` vs. exported-name mismatches (item 40).
- [Code] **Item 39**: Fix the hardware-scaling figure's cohort mismatch — filter/stratify
  `visualizations.ipynb`'s "Hardware Fidelity At Tau Zero" cell by backend and shot count explicitly;
  do not plot points from different backends as if they were a controlled `N`-scaling sweep. Correct
  the caption to state the true multi-backend, multi-shot-count cohort (or restrict the figure to a
  single backend if that's the intended comparison).
- [Code] **Item 32**: Re-verify title removal *on the actual regenerated figures* once the filename
  fix above lands — the helper defaults were already correct, but the currently-embedded PNGs
  predate the fix and still show titles.
- [Code] **Item 30**: Fit `log(error)` vs. `log(n_s)` by linear regression across multiple RNG seeds
  in the sampling-convergence cell, reporting the fitted exponent and its uncertainty, instead of
  overlaying an assumed `1/√n` line anchored to one point.
- [Code] **Item 33 (non-data parts)**: compress the x-axis, use a colorblind-safe qualitative palette
  instead of `magma`, and add worst-receiver/full-spread series — **only after** item 39's cohort fix,
  so the added polish isn't applied to a figure that's still comparing incomparable backends.
- [Code] Add basic dataset-validation helpers (duplicate-job detection, backend/shots consistency
  checks) reusable across the figure-generation scripts.

## Phase 4 — Manuscript framing, terminology & prior art (no data needed)

- [MS] **Item 20, 21**: Reword introduction's "circumvented" language; add explicit statement that
  receivers learn only `Σθⱼ` and the classical string `n̄` is independent of any individual `θⱼ`.
- [MS] **Item 22**: Soften "useful cryptographic primitive" claim — state precisely what privacy
  property holds (no Byzantine agreement / authentication claims).
- [MS] **Item 13, 14, 15**: Rewrite the Fig. 6 interpretation to state "circuit-size-dependent
  degradation consistent with accumulated hardware noise; correlated errors remain one possible
  explanation." Clarify Fig. 2 is a standalone encoded-memory test, distinct in scope from unencoded
  Figs. 5/6.
- [MS] **Item 17, 18 (corrected)**: State plainly that optimization levels 0–3 govern
  layout/routing/synthesis and do not by default enable dynamical decoupling. Distinguish transpiler
  `optimization_level` from Runtime error mitigation, **without** proposing a `resilience_level`
  option for the Sampler path this project actually uses (that option is Estimator-only).
- [MS] **Item 19**: Replace the visual "quasi-periodic" claim with a quantified
  autocorrelation/periodogram statement — allow the result to be inconclusive/negative; don't force
  a periodicity conclusion the data doesn't support.
- [MS] **Item 41 (new)**: Fix the Fig. 3 label/caption mismatch — either point the QEC-circuit
  paragraph at the correct figure (add one showing the actual 3-stage syndrome-extraction circuit if
  none currently exists) or correct the text to reference the right figure.
- [MS] **Items 24–27**: Add explicit statements on invalid sender-qudit outcome handling (clarify:
  currently *no correction is applied*, not rejection), the compressed feedforward dependency (once
  Phase 6 lands), decoder qubit-ordering convention, and circuit scheduling.
- [MS] **Item 23, 28**: Add 1996 no-broadcasting citation, fix misattributed references, full
  copyedit pass.
- [MS] **Item 44 (new)**: Add prior-art differentiation from critique §2.1 — cite Kumar & Pathak
  (*Quantum Inf. Process.* 23, 148, 2024) and explicitly contrast: (1) the Sukeno–Hillery
  `M`-sender/`N`-receiver Dicke resource family vs. their graph/cluster-state construction, (2) the
  exact factorization theorem (Phase 0) and exact `[[5,1,3]]` logical polynomial/break-even, (3) the
  dynamic-circuit QEC syndrome-extraction implementation.

## Phase 5 — Dynamical decoupling & optimization-vs-mitigation code (corrected scope)

- [Code] **Item 17 (corrected)**: Add an explicit, opt-in DD control path if DD experiments are
  pursued (Phase 8) — build a `PassManager` with `ALAPScheduleAnalysis` + `PadDynamicalDecoupling`
  compatible with the dynamic-circuit path actually used here (verify against the pinned
  `qiskit`/`qiskit-ibm-runtime` versions first; Runtime's built-in DD toggle may not compose with
  dynamic circuits — confirm before relying on it).
- [Code] **Item 18 (withdrawn as originally scoped)**: Do **not** add a `resilience_level` parameter
  to `HardwareBackend` — it executes via `SamplerV2`, which doesn't accept it. If error mitigation is
  ever wanted for an Estimator-based measurement, scope that separately.
- [Code] Add an autocorrelation/periodogram helper for fidelity-vs-delay traces (Phase 4, item 19),
  usable directly on existing delay-sweep result files — no new data required for this analysis.

## Phase 6 — Structured hardware circuit redesign (non-data prerequisite for Phase 8)

These are code changes that must land *before* any new hardware data collection in Phase 8.

- [Code] **Item 16 (refined)**: Replace `qc.initialize(init_state, ...)` in `broadcasting/circuit.py`
  with a structured Dicke-state preparation circuit. **Convention correction from review**: the
  sender register must encode `k = N - popcount(receiver_bits)` (the number of receiver **zeros**),
  matching the existing resource-state/phase convention — a generic "Hamming weight" without this
  qualifier implements a different (mirrored) protocol. Validate the structured circuit against the
  existing `get_initial_state`/statevector construction on asymmetric, non-equatorial inputs before
  comparing gate counts.
- [Code] **Item 16 (decoder)**: Replace the generic Gram–Schmidt `32×32` decode unitary
  (`broadcasting/qec_513.py::five_qubit_decode_gate`) with a structured Clifford `[[5,1,3]]`
  encoder/inverse-decoder circuit. Validate against the existing codespace mapping (`|0_L⟩→|00000⟩`,
  `|1_L⟩→|00001⟩`) and all 15 single-qubit errors before comparing gate counts against the
  Gram-Schmidt baseline.
- [Code] **Item 25 (corrected approach)**: Replace the `(N+1)^M`-branch exponential feedforward with
  `M·⌈log2(N+1)⌉` independent single-bit conditional phase rotations (phase corrections commute and
  decompose bit-by-bit: `P(-φ_n̄) = Π_j Π_b [P(-2π·2^b/(N+1))]^{c_{j,b}}`), **not** real-time classical
  modular-arithmetic evaluation — IBM dynamic-circuit runtimes place real restrictions on classical
  expression evaluation, and per-bit conditional gates avoid needing any arithmetic at all. Explicitly
  preserve or revise the invalid-outcome policy (currently: unmatched outcomes get no correction).
- [Code] For every redesigned circuit, measure and report qubit count, depth, two-qubit gate count,
  duration, and conditional-operation count (both before/after, so the "structured vs. generic"
  improvement is a measured number, not an estimate) — feeds directly into Phase 4's manuscript text.
- [Code] **Item 24**: Add explicit handling/reporting of invalid sender-qudit outcomes in
  results-processing code, documenting the current no-correction behavior and whether it should
  change.

## Phase 7 — Reproducibility & configuration hygiene 🆕

- [Code] **Item 50**: Add a short `README.md`: architecture overview, environment setup, one small
  simulation command, how to run tests, manuscript build command, and the distinction between the
  broadcasting protocol (`run_broadcast.ipynb`) and the standalone `qec_testing.ipynb` memory
  benchmark. Pin a tested dependency set (the review's validation environment: Qiskit 2.2.1,
  Aer 0.17.2, Runtime 0.42.0, NumPy 2.3.3) and record versions with future runs.
- [Code] Register the existing `slow` pytest marker (currently causes a warning) and separate
  quick mathematical tests from expensive integration checks.
- [Code] Make one configuration source authoritative across notebooks, CLI, backend, and serializer
  (builds on item 45); document the two meanings of `p_list` (backend-level sweep points vs.
  low-level per-receiver probabilities) and whether reduced states describe only the last sweep
  point.
- [Code] Consolidate duplicated logical-basis/stabilizer definitions across `qec_513.py` and
  `simulation.py` carefully — **keep the independent oracle from item 49 separate** even after
  consolidation, and add explicit native-qudit/little-endian conversion tests between the two state
  representations (`simulation.py`'s numerical path vs. `circuit.py`/`qec_513.py`'s Qiskit
  little-endian circuit path).

## Phase 8 — New data collection **[Data]**

Everything here requires new simulation or hardware runs; do this last, after Phases 0–7 land.
**Reuse existing data first** — the review demonstrates that global/worst-case/covariance analysis
(item 14) is already computable from the 13 existing hardware runs' saved joint-receiver bitstrings
without any new collection (e.g. `run_20260518_120232.json` at `τ=0`: mean local fidelity 0.9099,
worst-receiver 0.8941, global/all-zero fidelity 0.8493, product-of-locals 0.827671, receiver
success-covariance 0.0216). Do this reanalysis before deciding what new data is actually needed, and
keep the collection matrix small/bounded (a few representative sizes, targeted ablations).

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

