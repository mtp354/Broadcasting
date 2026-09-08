# Action Plan: Addressing the Broadcasting-2 Critique

This plan translates [Broadcasting-2_Critique.md](Broadcasting-2_Critique.md) plus additional
review comments into concrete, ordered work. Phases 0–4 require no new hardware/simulation
data collection and should be done first. Phases 5–6 require new data runs and are pushed to
the end, as requested. Zenodo/code-release cleanup is the final step.

**Status: Phase 0 and Phase 1 are complete** (analytical core, recovery-map fix, Monte Carlo
argmax fix, tests, and corresponding manuscript rewrite). See the end of each phase section
below for what changed.

## Legend
- **[Code]** — change in `broadcasting/` (or `hpc/`)
- **[MS]** — change in `manuscript/apstemplate.tex`
- **[Data]** — requires new simulation/hardware runs — deferred to Phase 6

---

## Master list of recommended changes (from the critique + additional comments)

### A. Mathematical/analytical correctness
1. Eqs. (32)–(33): `p_f` misused — replace with exact logical-channel polynomial `p_L(p)` and exact crossover `p* = (3-√6)/4`. (§1.2, §3.1)
2. State the general noise-factorization proposition (`F_local` independent of `M,N`; `F_global = (1-2p/3)^N`) instead of deriving only for `M=1,N=2`. (§1.1, §3.1)
3. Explain the second crossover at `p=3/4` where the Bloch contraction convention becomes negative. (§1.2)
4. Give the full noiseless receiver output state with `Φ = Σθⱼ`, not just the single-receiver case. (§1.1)
5. Eq. (36) recovery map is algebraically wrong as written (`V_Dec E_s P_C E_s` projects but never corrects). Replace with `V_Dec E_s† P_s`, reconcile with the density-matrix and Monte Carlo code. (§1.3, §3.2)
6. Add tests: all 15 weight-one Paulis corrected exactly; trace preservation over all syndrome branches; induced logical channel matches `p_L(p)`; noiseless encoded protocol gives unit fidelity for arbitrary `α,β,θ`. (§1.3, §3.2)

### B. Monte Carlo methodology
7. Fix description: syndrome is deterministic because a Pauli error maps a stabilizer codeword into one syndrome sector — not because the state is "pure". (§1.4)
8. Remove/justify `argmax` syndrome selection — compute syndrome directly from the sampled Pauli pattern; note that `argmax` is unsound for coherent/non-Pauli trajectories. (§1.4, §3.2)
9. **Work/memory accounting is incomplete and hard to interpret** — the stated `O(D)` memory / `O(n_s N D)` time omits the cost of accumulating `ρ̂` (`O(d_dec²)` per trajectory). Replace with a clearer, more interpretable complexity measure (see Phase 1 below). (§1.4, additional comment)
10. Recommend a much cheaper exact approach: sample/propagate logical Pauli errors directly on the unencoded `(N+1)^M · 2^N`-dimensional state instead of the full `2^{5N}`-dimensional encoded state; or use the exact logical channel analytically. (§1.4, §3.3)
11. Average scalar fidelity per trajectory instead of building an empirical density matrix when only fidelity is needed. (§1.4, §3.3)
12. Sum sender measurement branches exactly in the "exact" reference method instead of sampling one outcome. (§1.9)

### C. Hardware interpretation claims
13. Fig. 6 cannot distinguish correlated hardware errors from ordinary independent-but-accumulating circuit errors as circuit size grows — soften/narrow the claim. (§1.5, §3.6)
14. Report `F_local`, `F_global = (1-2p/3)^N`, and worst-receiver fidelity separately; local averages cannot diagnose correlation. (§1.5, §1.9, §3.5)
15. The `[[5,1,3]]` hardware result (Fig. 2) is a standalone encoded-memory test, not a full QEC-broadcasting demonstration — clarify scope mismatch with Figs. 5/6 (unencoded). (§1.6)
16. Replace generic Gram–Schmidt `32×32` decode unitary and `qc.initialize` resource-state loading with structured Clifford encoder/decoder and a Hamming-weight-based Dicke-state preparation circuit. (§1.6, §3.4)
17. Dynamical-decoupling claim is unsupported: Qiskit optimization levels 0–3 do not automatically apply DD; DD requires an explicit `PadDynamicalDecoupling` scheduling pass. Clarify text and, in code, either add explicit DD control or remove the DD attribution. (§1.7, additional comment)
18. Clarify the distinction between transpiler **optimization level** (layout/routing/synthesis) and Runtime **resilience level** (error mitigation in Estimator/Sampler primitives) — the manuscript currently conflates/uses only optimization level as a general "noise proxy." (additional comment)
19. Quantify "quasi-periodic dropouts" with autocorrelation/periodogram analysis instead of visual inference. (§1.7)

### D. No-broadcasting framing & terminology
20. Reword "circumventing" no-cloning/no-broadcasting — the protocol works because it falls outside the theorems' hypotheses (restricted state family, prior entanglement, sender knowledge), not because the theorems are violated. (§1.8, §3.6)
21. State precisely what "privacy" means here: receivers learn only the aggregate `Σθⱼ`, not individual `θⱼ`. (§1.8)
22. Soften the "useful cryptographic primitive" conclusion, or add an explicit application/security/threat model. (§1.9)
23. Cite the original 1996 no-broadcasting theorem in addition to the 2007 generalization; fix misattributed references (device `T1` range, self-testing citation). (§1.9)

### E. Presentation / secondary issues
24. Report invalid sender-qudit outcomes (e.g., outcome `3` when `N=2`) and state whether they are rejected/mapped/uncorrected. (§1.9)
25. Replace the `(N+1)^M`-branch exponential feedforward description with the actual dependency on `Σⱼnⱼ mod (N+1)` (aggregate branches only). (§1.9)
26. Clarify decoder qubit ordering / little-endian convention explicitly (Eqs. 25–26 vs Eq. 40). (§1.9)
27. Report circuit scheduling explicitly (are senders idle too, or only receivers?). (§1.9)
28. Full copyedit pass (grammar errors listed in §1.9).
29. Resolve coauthor placeholder and Zenodo placeholder — actually deposit code/data (deferred to end, per user request). (§1.9)

### F. Additional comments from user (not in critique doc)
30. Log-scale sampling-convergence plot: verify the `1/√n` reference line is scaled/anchored correctly.
31. Add data so the two receiver fidelity lines are not asymmetric at low shot counts (Fig. "delay time vs fidelity", Receiver 1 vs Receiver 2). **[Data]**
32. Remove titles from all published graphs.
33. Scaling-fidelity hardware figure needs: more data points, larger `M,N` **[Data]**, compressed x-axis, more distinct colors, and average/worst-case/full-spread receiver fidelity plotted as points (not just the mean).
34. Zenodo code release can be left to the very end.

---

## Phase 0 — Analytical core (no data needed) — ✅ DONE

- [MS] **Item 1–4**: Rewrite the QEC section around Eq. (31)–(33). Replace with the exact logical-channel polynomial
  `p_L(p) = 10p² − (200/9)p³ + (160/9)p⁴ − (128/27)p⁵`, `F_QEC = 1 − (2/3)p_L(p)`, and `p* = (3−√6)/4 ≈ 0.1376`.
  Add a short appendix/table deriving the Pauli-weight enumerator coefficients (90, 210, 270, 198). Add the general
  factorization proposition (`F_local`, `F_global`) as its own numbered result, generalized for all `M,N`. Explain the
  `p=3/4` degenerate crossover.
- [Code] Add a small verification utility (e.g. `broadcasting/qec_513.py::logical_error_polynomial` or a test-only
  helper) that evaluates `p_L(p)` from direct enumeration over all `4^5` Pauli patterns and cross-checks it against
  `qec_recover_and_decode`'s exact-mode output as a function of `p`. This becomes the "independent ground truth" the
  critique asks for (§1.4 last paragraph).
- [MS] **Item 5**: Correct Eq. (36) to `V_Dec E_s† P_s` (`P_s = E_s P_C E_s†`); note that
  `broadcasting/simulation.py`'s exact path (`qec_recover_and_decode`, `K_local` construction) already implements this
  correct formula (`V_dec @ E_s @ Pi_s` simplifies to `V_dec @ P_code @ E_s` for Hermitian involutory Pauli reps) — the
  bug is confined to the written equation and the Monte Carlo pseudocode, not the exact-mode implementation. State this
  explicitly in the text.
- [Code] **Item 8**: In `broadcasting/simulation.py::qec_recover_and_decode`, the sampling branch (`_kraus_state`)
  currently uses `argmax` over probability across all 16 syndrome Kraus operators. Since trajectories are generated by
  explicitly sampled Pauli errors, replace this with direct syndrome computation from the applied error pattern
  (track the injected Pauli per trajectory and look up its syndrome instead of re-deriving it via argmax). Keep
  `argmax`/full projection only as a fallback path clearly documented as invalid for non-Pauli noise.

## Phase 1 — Recovery-map tests & Monte Carlo work/memory clarity — ✅ core items done, items 10–12 deferred

- [Code] **Item 6**: Add unit tests (in [tests/test_qec_513.py](tests/test_qec_513.py) and/or a new
  `tests/test_qec_recovery.py`) for:
  - all 15 weight-one Pauli errors decode exactly to the intended logical state;
  - the full set of Kraus operators for the recovery map is trace-preserving (`Σ Kₛ† Kₛ = I` on the codespace);
  - the induced logical error probability from Monte Carlo sampling matches `p_L(p)` within statistical error;
  - the noiseless encoded protocol gives fidelity 1 for random `α, β, θ`.
- [Code] **Item 9**: Replace the `O(D)`/`O(n_s N D)` complexity claim with a clearer, more interpretable measure.
  Concretely: report (a) per-trajectory state-vector dimension actually used (`(N+1)^M · 2^{5N}` before decode vs.
  `(N+1)^M · 2^N` after), (b) wall-clock time and peak memory actually measured for representative `(M,N)`, and (c)
  whether a density-matrix accumulator (`ρ̂`) is used at all. This replaces asymptotic claims that omit the `O(d_dec²)`
  accumulation cost with a directly measured, reproducible number.
- [Code] **Item 10, 11**: Add a fast path that samples/generates the logical Pauli error directly (using the exact
  `p_L(p)` distribution) and applies it to the unencoded resource state, bypassing full `2^{5N}` encoded simulation.
  Add an option to accumulate only the scalar per-trajectory fidelity rather than the full empirical density matrix
  when only fidelity is required.
- [Code] **Item 12**: In the "exact" density-matrix reference path, sum over all sender measurement outcomes
  (weighted by their probabilities) rather than sampling a single outcome. **(not yet implemented)**
- [MS] Rewrite the Monte Carlo methodology paragraphs to reflect items 7–12 and the new complexity reporting.

**Implementation notes (2026-09-08):** Items 5–9 are done. `broadcasting/simulation.py` now exposes
`five_qubit_recovery_kraus_operators()`, `pauli_label_syndrome()`, `logical_error_polynomial()`, and
`logical_error_probability_bruteforce()`; `depolarizing_channels_encoded()` tracks per-trajectory Pauli
frames (`"pauli_labels"`), and `qec_recover_and_decode()` uses them for deterministic O(1) recovery instead
of the `argmax` search (with an `argmax` + `RuntimeWarning` fallback kept for backward compatibility with
hand-built trajectories lacking labels). New tests in `tests/test_qec_recovery.py` cover exact weight-one
correction, trace preservation, the closed-form vs. brute-force logical polynomial, the exact break-even
point, noiseless unit fidelity, and the sampled-vs-exact fidelity match. The manuscript's Eq. (31)-(33),
Eq. (36), and the Monte Carlo complexity paragraph were rewritten accordingly. **Items 10–12** (a fast
logical-Pauli-only sampling path bypassing the `2^{5N}`-dimensional encoded state, a scalar-fidelity-only
accumulation mode, and exact summation over all sender outcomes instead of one sampled outcome) are **not
yet implemented** and remain open for a follow-up pass.

## Phase 2 — Plotting fixes (non-data)

- [Code] **Item 32**: Audit all figure-generation cells/functions and ensure `show_title=False` (or no title call) is
  used everywhere a figure is exported for the manuscript. `broadcasting/plotting.py::save_figure` /
  `clear_titles` already strip titles by default — confirm every notebook cell producing a manuscript figure calls
  `save_figure(..., strip_titles=True)` (default) and doesn't rely on `plt.title`/`fig.suptitle` calls that bypass it.
- [Code] **Item 30**: In [run_broadcast.ipynb](run_broadcast.ipynb) "Optional Sampling Convergence" cell, check the
  `1/sqrt(n)` reference line: it's currently anchored as
  `errors[0] * sqrt(n_sweep[0]) / sqrt(n_sweep)`, i.e. normalized to the *first* observed data point. Verify (a) this
  anchor point isn't itself noisy/atypical (consider anchoring to a fit or to the geometric mean of several trajectory
  seeds instead of a single point), and (b) confirm the exponent is `-1/2` by fitting `log(error)` vs `log(n)` and
  reporting the fitted slope instead of just overlaying an assumed line.
- [Code] **Item 33 (non-data parts)**: Rework `hardware_tau0_scaling.png` generation (in
  [visualizations.ipynb](visualizations.ipynb), "Hardware Fidelity At Tau Zero" cell):
  - compress the x-axis (e.g. use integer `N` ticks with less whitespace, or a log/sqrt scale if the range grows);
  - replace the `magma` colormap keyed by `M` with a more distinct, colorblind-safe qualitative palette
    (e.g. `tab10`/`Set2`) since `magma` produces low contrast between adjacent `M` values;
  - for each `(M,N)` point, also plot worst-receiver fidelity and the full spread (min/max or all per-receiver values)
    as additional point series/error bars, not just the mean.
  (Adding the actual larger-`M,N` data points is deferred to Phase 6.)

## Phase 3 — Manuscript framing & terminology (no data needed)

- [MS] **Item 20, 21**: Reword introduction's "circumvented" language per §1.8; add explicit statement that receivers
  learn only `Σθⱼ`.
- [MS] **Item 22**: Soften "useful cryptographic primitive" claim or add explicit threat model.
- [MS] **Item 13, 14, 15**: Rewrite the Fig. 6 interpretation paragraph to state "circuit-size-dependent degradation
  consistent with accumulated hardware noise; correlated errors remain one possible explanation," per the critique's
  suggested defensible conclusion (§3.6). Clarify Fig. 2 is a standalone encoded-memory test, distinct in scope from
  the unencoded Figs. 5/6.
- [MS] **Item 17, 18**: Correct the dynamical-decoupling attribution — state plainly that Qiskit optimization levels
  0–3 govern layout/routing/synthesis and do **not** by default enable dynamical decoupling, which requires an
  explicit `PadDynamicalDecoupling` pass. Add a short clarifying paragraph distinguishing transpiler
  **optimization_level** from Runtime **resilience_level** (error mitigation), since the manuscript currently implies
  optimization level alone is a general "noise proxy" that covers both concerns.
- [MS] **Item 19**: Replace the visual "quasi-periodic" claim with a quantified autocorrelation/periodogram statement
  (analysis can be done on already-collected delay-sweep data — no new data required).
- [MS] **Items 24–27**: Add explicit statements on invalid sender-qudit outcome handling, the compressed
  `Σnⱼ mod (N+1)` feedforward dependency, decoder qubit-ordering convention, and circuit scheduling (senders vs.
  receivers idling).
- [MS] **Item 23, 28**: Add 1996 no-broadcasting citation, fix misattributed references, full copyedit pass.
- [MS] **Item 3.6 title/conclusion**: Consider the suggested title/central-conclusion rewording from §3.6.

## Phase 4 — Code correctness / dynamical decoupling & optimization vs. resilience level [Code]

- [Code] **Item 17, 18**: In `broadcasting/backend.py`, `optimization_level` is passed to the transpiler
  (currently the only "noise proxy" knob; no `resilience_level` or explicit DD pass exists anywhere in
  `broadcasting/` or `hpc/`). Add:
  - an explicit, documented DD control path (e.g. a `dynamical_decoupling: bool` / `dd_sequence: str | None` option
    that builds a `PassManager` with `PadDynamicalDecoupling` when requested, scheduled via `ALAPScheduleAnalysis`),
    so DD is opt-in and traceable rather than implicitly assumed;
  - a separate, explicit `resilience_level` parameter (for Runtime primitives) distinct from `optimization_level`,
    so the two concepts are not conflated in code either.
- [Code] Add a small analysis helper for autocorrelation/periodogram of fidelity-vs-delay traces to support the
  quantified "dropout periodicity" claim (Phase 3, Item 19) using existing delay-sweep result files in
  [results/](results).

## Phase 5 — Hardware circuit redesign (structured, non-data prerequisite)

These are code changes that must land *before* the new hardware data collection in Phase 6.

- [Code] **Item 16**: Replace `qc.initialize(init_state, ...)` in `broadcasting/circuit.py` with a structured
  Hamming-weight-based Dicke-state preparation circuit (compute Hamming weight of receiver qubits into a sender
  register, copy to remaining sender registers) instead of Qiskit's generic `Initialize`/isometry synthesis.
- [Code] **Item 16**: Replace the generic Gram–Schmidt `32×32` decode unitary
  (`broadcasting/qec_513.py::five_qubit_decode_gate`) with a structured Clifford `[[5,1,3]]` encoder/inverse-decoder
  circuit, and correspondingly update the hardware circuit-construction path.
- [Code] **Item 25**: Replace the `(N+1)^M`-branch exponential feedforward in the dynamic circuit with a compressed
  implementation keyed only on `Σⱼnⱼ mod (N+1)` (aggregate correction), likely in `broadcasting/protocol.py` /
  `broadcasting/circuit.py`.
- [Code] For every redesigned circuit, add reporting of qubit count, depth, two-qubit gate count, duration, and
  conditional-operation count (for the ablation study in Phase 6).
- [Code] **Item 24**: Add explicit handling/reporting of invalid sender-qudit outcomes (e.g. outcome `3` for `N=2`)
  in the results-processing code (`broadcasting/results.py` / `broadcasting/fidelity.py`).

## Phase 6 — New data collection **[Data]**

Everything here requires new simulation or hardware runs; do this last, after Phases 0–5 land.

- [Data] **Item 31**: Re-run the `M=1,N=2` fidelity-vs-delay hardware experiment with enough additional shots/repeats
  that Receiver 1 vs. Receiver 2 fidelity asymmetry can be distinguished from shot noise (increase shots and/or add
  repeated jobs across time to separate drift from a real asymmetry).
- [Data] **Item 33**: Collect additional `(M,N)` scaling data points, including larger protocol sizes than currently
  available, for the hardware scaling-fidelity figure; ensure enough repetitions per point to report worst-case and
  full-spread receiver fidelity (Phase 2's plotting changes render this once collected).
- [Data] **Item 25/Ablation (§3.4)**: Run the ablation series on the redesigned circuits — separately add resource
  prep, sender phase/Fourier ops, delay, feedforward, syndrome extraction, correction, decoding — to localize fidelity
  loss.
- [Data] **Item 14/§3.5 (correlation tests)**: Collect joint all-receiver ("global") fidelity, pairwise receiver
  covariance, and simultaneous-vs-isolated-qubit benchmarking data; compare hardware against a backend-calibrated
  independent noise-model simulation of the same transpiled circuit.
- [Data] **Item 17/19 (DD ablation)**: Run explicit no-DD / standard-DD / staggered-DD variants (using the Phase 4 DD
  control) and multiple transpiler seeds/layouts to test the dropout/DD hypothesis.
- [Data] **Item 27 (error bars/repetitions/drift)**: Add repeated jobs across days and multiple transpiler seeds to
  quantify calibration drift, beyond existing shot-noise error bars.
- [Data] **Item 27 (backend metadata)**: Archive job IDs, physical qubit layout, gate counts, depth, scheduled
  duration, readout errors, two-qubit error rates, and contemporaneous `T1`/`T2` for each hardware run going forward.

## Phase 7 — Zenodo / release (last, per request)

- [Item 34/29] Resolve the coauthor placeholder, finalize the Zenodo deposit, and ensure the deposited code includes
  the Phase 1 recovery-map tests so reviewers/readers can independently verify correctness.

---

## Notes on where things already look correct
- `broadcasting/plotting.py` already defaults `show_title=False` and has a `clear_titles`/`save_figure` helper that
  strips titles — Phase 2's title work is mostly an audit to make sure every figure-producing cell actually uses it.
- The exact-mode recovery implementation in `broadcasting/simulation.py::qec_recover_and_decode` already applies the
  mathematically correct Kraus operators (equivalent to `V_Dec P_C E_s`) — only the manuscript equation and the
  Monte-Carlo `argmax` pseudocode need correcting, not the exact-mode code path.
