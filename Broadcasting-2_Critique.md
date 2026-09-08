# Overall assessment

This is a **promising but not yet publication-ready manuscript**. My recommendation would be **major revision**.

The core protocol is represented reasonably faithfully, the unencoded depolarizing-noise calculation is correct, and the low-noise crossover shown for the \([[5,1,3]]\) code is close to the exact value. However, there are two serious mathematical problems in the displayed QEC analysis, and the main experimental interpretation—that correlated hardware errors have been demonstrated—is not supported by the measurements shown. The hardware implementation also appears to conflate the performance of the broadcasting protocol with generic state-preparation, routing, decoding, and dynamic-circuit overhead.

The most serious points are:

1. Equations (32)–(33) are algebraically inconsistent with the definition of \(p_f\).
2. Equation (36) does not implement syndrome correction as written.
3. Figure 6 cannot, by itself, distinguish correlated errors from ordinary independent circuit errors that accumulate as the circuit grows.
4. The hardware QEC result appears to be a standalone encoded-memory test, not a complete QEC-enhanced broadcasting experiment.
5. The terminology surrounding “circumventing” no-broadcasting is conceptually misleading.

---

# 1. Correctness

## 1.1 Parts that are essentially correct

### The noiseless protocol

Equations (1)–(6) are consistent with the underlying \(M\)-sender, \(N\)-receiver protocol. The sender phase gates, Fourier measurements, and receiver correction produce the stated single-receiver target state. The manuscript should state explicitly that the full noiseless receiver output is

\[
\left(
\alpha e^{i\Phi}|0\rangle+
\beta e^{-i\Phi}|1\rangle
\right)^{\otimes N},
\qquad
\Phi=\sum_{j=1}^{M}\theta_j,
\]

rather than only giving the single-receiver state. fileciteturn0file0L81-L154

### The unencoded depolarizing calculation

For the channel convention

\[
\mathcal D_p(\rho)
=(1-p)\rho+\frac p3(X\rho X+Y\rho Y+Z\rho Z),
\]

the Bloch-vector contraction factor is indeed

\[
\eta=1-\frac{4p}{3}.
\]

The receiver state in Equation (18) and the fidelity

\[
F=\frac{1+\eta}{2}=1-\frac{2p}{3}
\]

are correct. The angle independence is also correct because the channel is isotropic. fileciteturn0file0L229-L342

The covariance argument actually proves more than the manuscript states. For arbitrary \(M,N\),

\[
\rho_{\mathrm{out}}
=
\mathcal D_p^{\otimes N}
\left(
|\psi_{\mathrm{target}}\rangle
\langle\psi_{\mathrm{target}}|^{\otimes N}
\right).
\]

Thus, under the idealized channel model, the local receiver fidelity is independent of \(M\) and \(N\). This should be presented as a general proposition rather than derived only for \(M=1,N=2\).

### The target-basis fidelity measurement

For a pure target state, rotating the target to \(|0\rangle\) and measuring the zero probability does give

\[
P(0)=
\langle\psi_{\mathrm{target}}|
\rho_{\mathrm{out}}
|\psi_{\mathrm{target}}\rangle.
\]

Equations (41)–(44) are therefore valid, although the phase notation could be simplified. fileciteturn0file0L806-L840

### The numerical location of the QEC crossover

The crossover shown in Figure 4 around \(p\simeq0.138\) is consistent with the exact behavior of the standard \([[5,1,3]]\) recovery. fileciteturn0file0L841-L861 The figure is therefore likely substantially correct even though the analytical explanation immediately preceding it is not.

---

## 1.2 Critical mathematical problem: Equations (31)–(33)

The manuscript defines

\[
p_f
=
1-(1-p)^5-5p(1-p)^4
\simeq 10p^2+O(p^3)
\]

as the probability of two or more physical Pauli errors. It then writes

\[
F\simeq 1-\frac{2}{3}10p_f^2,
\]

and equates this to the unencoded fidelity. That does not follow from the preceding definition. fileciteturn0file0L490-L532

If \(p_f\) is being treated as the effective logical depolarizing probability, the corresponding approximation would be

\[
F_{\mathrm{QEC}}
\simeq 1-\frac{2}{3}p_f
\simeq 1-\frac{20}{3}p^2.
\]

Equating this lowest-order approximation to

\[
F_{\mathrm{bare}}=1-\frac{2p}{3}
\]

does give the rough estimate \(p\simeq0.1\). Thus, the likely intended Equation (32) was

\[
F_{\mathrm{QEC}}\simeq
1-\frac{2}{3}p_f
\simeq
1-\frac{2}{3}10p^2,
\]

not \(1-\frac23 10p_f^2\).

More importantly, the entire crossover can be obtained exactly. For the recovery specified in the paper—each nonzero syndrome is mapped to its unique weight-one Pauli representative—the induced logical channel under independent physical depolarizing noise is itself depolarizing. Direct enumeration of all \(4^5\) physical Pauli patterns gives the logical nonidentity probability

\[
\begin{aligned}
p_L(p)
={}&90\left(\frac p3\right)^2(1-p)^3
+210\left(\frac p3\right)^3(1-p)^2\\
&+270\left(\frac p3\right)^4(1-p)
+198\left(\frac p3\right)^5\\[1mm]
={}&10p^2-\frac{200}{9}p^3
+\frac{160}{9}p^4
-\frac{128}{27}p^5 .
\end{aligned}
\]

Consequently,

\[
F_{\mathrm{QEC}}(p)
=
1-\frac{2}{3}p_L(p).
\]

The low-noise break-even point satisfies \(p_L(p)=p\), giving

\[
p_\star=\frac{3-\sqrt6}{4}
\simeq 0.1376276.
\]

This explains the numerical crossover in Figure 4 almost exactly and would be a much stronger result than the current heuristic.

The explanation following Equation (33) is also incorrect. The manuscript says the estimate is low because not all two-qubit errors are miscorrected, giving “a double bitflip on the same qubit” and “two phase flip errors” as examples. Under the one-shot channel model:

- A “double bitflip on the same qubit” is not one of the weight-two channel events; each physical qubit receives one Pauli draw. Sequentially, \(X^2=I\).
- Two \(Z\) errors on distinct qubits are genuine weight-two errors and are not correctable by a distance-three code.
- For the standard minimum-weight recovery, all 90 distinct-qubit weight-two Pauli patterns induce a nontrivial logical Pauli.

The difference between \(0.1\) and \(0.1376\) comes principally from truncating the exact polynomial at order \(p^2\), with additional contributions and cancellations from weight-three and higher errors—not from correctable weight-two errors.

A secondary point is that the paper plots \(p\) up to one. Under its convention, \(p=3/4\) is the completely depolarizing channel; for \(p>3/4\), the Bloch contraction becomes negative. The channel remains CPTP, but it is no longer the usual monotone interpolation toward the maximally mixed state. The second equality of encoded and unencoded fidelity at \(p=3/4\), visible in Figure 4, should be explained.

---

## 1.3 Critical mathematical problem: the recovery map in Equation (36)

Let \(P_C\) denote the codespace projector and let \(E_s\) be the chosen Pauli representative for syndrome \(s\). The projector onto syndrome sector \(s\) is

\[
P_s=E_sP_CE_s^\dagger.
\]

The recovery-decoding Kraus operator should therefore be

\[
\begin{aligned}
K_s
&=
V_{\mathrm{Dec}}E_s^\dagger P_s\\
&=
V_{\mathrm{Dec}}E_s^\dagger
E_sP_CE_s^\dagger\\
&=
V_{\mathrm{Dec}}P_CE_s^\dagger .
\end{aligned}
\]

For Hermitian Pauli representatives, this becomes \(V_{\mathrm{Dec}}P_CE_s\).

Equation (36), however, applies

\[
V_{\mathrm{Dec}}E_sP_CE_s|\psi\rangle,
\]

which is \(V_{\mathrm{Dec}}P_s|\psi\rangle\): it projects onto the syndrome sector but does not correct the state back to the codespace before applying \(V_{\mathrm{Dec}}\). fileciteturn0file0L623-L635 The density-matrix description has the same omission when it describes syndrome projectors followed directly by \(V_{\mathrm{Dec}}\). fileciteturn0file0L569-L572

Because the manuscript defines

\[
V_{\mathrm{Dec}}
=
|0\rangle\langle0_L|
+
|1\rangle\langle1_L|,
\]

it has support only on the codespace. Applied literally, Equation (36) would annihilate every nonzero-syndrome branch rather than decode it.

The fact that Figure 4 looks physically reasonable strongly suggests that the source code may implement the correct recovery and the displayed equation is wrong. But this cannot be assumed. The manuscript must reconcile the mathematical map, the density-matrix implementation, and the Monte Carlo implementation. At minimum, the code should include tests showing that:

1. All 15 weight-one Pauli errors are corrected exactly.
2. Every recovery map is trace preserving when all syndrome branches are summed.
3. The induced logical channel matches the polynomial above.
4. The noiseless encoded protocol gives unit fidelity for arbitrary \(\alpha,\beta,\theta\).

This is a publication-blocking issue until resolved.

---

## 1.4 The Monte Carlo methodology is valid in principle but inefficient and inaccurately described

Sampling Pauli trajectories is an unbiased way to simulate a Pauli channel. However, several statements in the Monte Carlo section need correction. fileciteturn0file0L606-L661

First, a pure state does **not** generally have a deterministic syndrome. The syndrome is deterministic here because a sampled Pauli error maps the codespace into one definite syndrome subspace. The relevant property is “Pauli error acting on a stabilizer codeword,” not purity.

Second, using

\[
s^\star=\arg\max_s p_s
\]

is unnecessary and conceptually dangerous. For an exact Pauli trajectory, the syndrome can be computed directly from the sampled error pattern. For coherent or non-Pauli trajectories, the distribution would not generally be concentrated on one syndrome, and selecting the largest branch would be biased.

Third, the stated memory cost omits the empirical decoded density matrix

\[
\widehat\rho
=
\frac1{n_s}\sum_i|\psi_i\rangle\langle\psi_i|.
\]

If the decoded dimension is

\[
d_{\mathrm{dec}}=(N+1)^M2^N,
\]

then storing \(\widehat\rho\) costs \(O(d_{\mathrm{dec}}^2)\), even though each encoded trajectory costs only \(O(D)\). Constructing the outer products also adds \(O(n_s d_{\mathrm{dec}}^2)\) work. The claimed \(O(D)\) total memory and \(O(n_sND)\) total time are therefore not generally complete.

More fundamentally, there is no need to simulate \(5N\) encoded qubits for this noise model. A substantially better procedure is:

1. Precompute the mapping from every five-qubit Pauli pattern to its residual logical Pauli.
2. Sample one logical Pauli per receiver block.
3. Apply it directly to the unencoded resource state of dimension \((N+1)^M2^N\).

For independent depolarizing noise, one can simply sample from the exact logical channel with probability \(p_L(p)\), or apply that logical channel analytically. This reduces the state dimension from

\[
(N+1)^M2^{5N}
\quad\text{to}\quad
(N+1)^M2^N.
\]

If only fidelity is required, it is better still to average the scalar fidelity trajectory by trajectory instead of accumulating a density matrix.

Finally, agreement between two implementations is not fully independent validation if they share the same syndrome table, recovery convention, or erroneous operator formula. The exact logical polynomial supplies the independent benchmark that is currently missing.

---

## 1.5 The manuscript does not establish correlated hardware errors

The strongest unsupported conclusion is the inference from Figure 6 that the decreasing fidelity with receiver count “likely indicate[s] correlated noise structures.” fileciteturn0file0L909-L920

The argument appears to be:

1. In the abstract channel model, each receiver is acted on by an independent depolarizing channel.
2. Average local fidelity is independent of \(N\).
3. Hardware fidelity decreases with \(N\).
4. Therefore the hardware errors must be correlated.

Step 4 does not follow. When \(N\) changes on hardware, the circuit itself changes:

- the resource-state preparation becomes larger and deeper;
- additional routing and SWAPs may be required;
- the sender qudit dimension and Fourier transform change;
- more qubits spend time idle;
- the number and location of two-qubit gates change;
- the dynamic-circuit duration and classical-control overhead can change;
- different physical qubits and couplers may be selected.

Independent gate, readout, relaxation, and dephasing errors can therefore produce an \(N\)-dependent average receiver fidelity even with no correlated noise at all. The statement that independent channels should not depend on \(N\) applies only to the idealized model in which an already-perfect resource state is followed by one fixed local channel per receiver—not to the full compiled hardware circuit.

There is also a metric problem. The paper studies average single-receiver fidelity. Under independent channels,

\[
F_{\mathrm{local}}=1-\frac{2p}{3}
\]

is independent of \(N\), but the fidelity that **all receivers are simultaneously correct** is

\[
F_{\mathrm{global}}
=
\left(1-\frac{2p}{3}\right)^N,
\]

which decreases with \(N\) even under perfectly independent noise. Thus, the claim that independent noise has no scaling effect depends entirely on using a local-average metric.

Moreover, local marginals cannot diagnose correlations. A correlated error process and an independent error process can have exactly the same one-qubit marginal fidelities. To claim correlated errors, the authors need measurements such as:

- joint all-receiver fidelity;
- pairwise error covariance;
- joint output bitstring distributions;
- syndrome correlations between blocks;
- simultaneous versus isolated-qubit benchmarking;
- comparison against an independent device-calibrated noise model of the same transpiled circuit.

The current fidelity circuit already rotates every target receiver state to \(|0\rangle\). Therefore, no additional measurement basis is needed to estimate the global target fidelity: it is simply the observed frequency of the all-zero receiver string. The same data can also provide target-basis pairwise covariances.

The conclusion should presently say that the data show **circuit-size-dependent degradation consistent with accumulated hardware noise**, with correlated errors remaining one possible explanation. The stronger claims in the abstract and conclusion are not justified. fileciteturn0file0L8-L16 fileciteturn0file0L921-L939

---

## 1.6 The hardware implementation confounds QEC with generic circuit synthesis

The hardware methods use an arbitrary Gram–Schmidt completion to construct a \(32\times32\) decoding unitary. fileciteturn0file0L790-L805 This is mathematically a possible extension of the decoder, but it is a poor choice for a hardware benchmark.

A \([[5,1,3]]\) stabilizer encoder and decoder can be implemented using a structured Clifford circuit. A generic dense unitary produced by Gram–Schmidt can transpile into a very deep sequence of one- and two-qubit gates. Consequently, the encoded fidelity near \(1/2\) in Figure 2 may say more about generic-unitary synthesis than about the feasibility of the five-qubit code or QEC on the backend. The paper shows that the particular implementation fails to reach break-even, but not why it fails. fileciteturn0file0L685-L711

The same concern applies to resource-state preparation. The circuit is described as “loading” the entire resource state, and Figure 3 shows a generic \(|\psi\rangle\)-initialization block. fileciteturn0file0L700-L706 Qiskit’s `Initialize` operation invokes generic state-preparation/isometry synthesis rather than exploiting the mathematical structure of the state. ([quantum.cloud.ibm.com](https://quantum.cloud.ibm.com/docs/api/qiskit/qiskit.circuit.library.Initialize))

A scalable structured preparation is available. Begin with

\[
(\alpha|0\rangle+\beta|1\rangle)^{\otimes N}
\]

on the receiver qubits, coherently compute their Hamming weight \(k\) into a sender register, and copy that computational-basis value into the other sender registers. Grouping bitstrings by weight produces exactly the Dicke-state decomposition in Equation (1). This would replace generic amplitude loading with a transparent circuit whose cost can be analyzed.

There is also an important scope mismatch: as presented, the hardware QEC result in Figure 2 is a standalone encoded-qubit storage experiment, while the broadcasting results in Figures 5 and 6 are unencoded. fileciteturn0file0L685-L711 fileciteturn0file0L862-L900 The manuscript should not imply that a complete QEC-enhanced broadcasting circuit was experimentally demonstrated unless such results are added.

A defensible conclusion is:

> This particular non-fault-tolerant, generically synthesized five-qubit implementation does not reach break-even on the tested backend.

It is not yet defensible to conclude broadly that current hardware cannot implement useful QEC for this protocol.

---

## 1.7 The dynamical-decoupling explanation is unsupported

The manuscript says the transpiler optimization levels incorporate techniques including dynamical decoupling, and later attributes the low-fidelity dropouts to a “staggered dynamical decoupling regime.” fileciteturn0file0L679-L695 fileciteturn0file0L895-L908

IBM’s documented preset optimization levels concern layout, routing, cancellation, and resynthesis; dynamical decoupling is not listed as an automatic consequence of choosing optimization level \(0\)–\(3\). ([quantum.cloud.ibm.com](https://quantum.cloud.ibm.com/docs/en/guides/set-optimization)) IBM documents dynamical decoupling as a separate scheduled pass requiring explicit scheduling and `PadDynamicalDecoupling`. ([quantum.cloud.ibm.com](https://quantum.cloud.ibm.com/docs/guides/dynamical-decoupling-pass-manager))

Therefore, unless a runtime option or custom pass manager was used and omitted from the paper, the dropouts cannot be attributed to dynamical decoupling. The cited staggered-DD work notes that dropouts and instability can occur, but that does not establish the cause of the present data. ([arxiv.org](https://arxiv.org/html/2403.05391v2))

The authors should report the actual scheduled circuit or timeline and repeat the experiment under at least:

1. No dynamical decoupling.
2. A specified standard sequence.
3. A specified staggered sequence.
4. Multiple transpiler seeds and layouts.

The claim of “quasi-periodicity” should also be quantified using an autocorrelation, periodogram, or Fourier analysis rather than inferred visually from one trace.

---

## 1.8 The no-broadcasting framing should be corrected

The introduction says that no-cloning and no-broadcasting can be “circumvented” under restricted conditions. fileciteturn0file0L17-L30 This is likely to attract an avoidable conceptual objection.

The protocol does not take an arbitrary unknown input state and create two output marginals equal to that state. Instead, the senders remotely prepare multiple copies of a state drawn from a known restricted family, using prior entanglement and classical communication. The originating 2022 paper explicitly describes this as remote state preparation when the sender knows a state from a restricted set, and the 2023 generalization calls the procedure a restriction and extension of remote state preparation. ([link.aps.org](https://link.aps.org/doi/10.1103/PhysRevA.105.042611))

Thus, the no-go theorems are not violated or mathematically circumvented; their hypotheses do not apply to the task being performed. Better wording would be:

> The task avoids the scope of the no-cloning and no-broadcasting theorems by restricting the state family and assuming prior entanglement and sender knowledge of the phase.

Similarly, “privacy” needs a threat model. The classical Fourier outcomes may be independent of the phases, but the receivers are intentionally given phase-encoded quantum states and can estimate the aggregate phase from sufficiently many copies. The precise property appears to be that the classical correction messages reveal no additional phase information, and in the multi-sender setting the receivers obtain only the aggregate \(\sum_j\theta_j\), not each individual contribution. That should be stated explicitly.

---

## 1.9 Other technical and presentation issues

Several secondary issues should also be corrected:

- **Local versus global success:** The paper repeatedly speaks about protocol scalability while measuring average local fidelity. It should report average, worst-receiver, and joint product-state fidelity separately.

- **Unused qudit basis states:** When \(N+1\) is not a power of two, the binary sender encoding contains unused states. For \(N=2\), hardware errors can produce measurement outcome \(3\). The paper must report the frequency of invalid outcomes and define whether they are rejected, mapped, or left uncorrected. fileciteturn0file0L172-L178

- **Exponential feedforward description:** The circuit introduces a branch for every tuple in \(\{0,\ldots,N\}^M\), although the correction depends only on
  \[
  \sum_j n_j\bmod(N+1).
  \]
  It can be implemented with only \(N+1\) aggregate branches or as sequential per-sender corrections. The current \((N+1)^M\)-branch description is not scalable. fileciteturn0file0L734-L766

- **Decoder ordering:** Equations (25)–(26) place the logical qubit in the first tensor factor, while Equation (40) maps \(|1_L\rangle\) to \(|00001\rangle\). This may be intended to reflect Qiskit’s little-endian convention, but the tensor ordering and the register being retained by the partial trace must be made explicit. fileciteturn0file0L390-L413 fileciteturn0file0L790-L805

- **The “exact” calculation samples a measurement outcome:** A density-matrix reference method should sum all sender outcomes rather than sample one, especially because \((N+1)^M\) is small in the reported cases. fileciteturn0file0L580-L605

- **Circuit scheduling is unspecified:** A delay placed only on receiver wires does not by itself establish that only receivers experience a corresponding idle interval. Sender operations may be scheduled concurrently, or barriers may cause the senders to idle as well. The scheduled timeline is required.

- **Error bars and repetitions:** Shot-noise error bars, repeated jobs, day-to-day drift, and variation across transpiler seeds are missing. Ten thousand shots control binomial uncertainty but not calibration drift.

- **Backend metadata:** The paper should archive job IDs, physical-qubit layout, gate counts, depth, scheduled duration, readout errors, two-qubit errors, and the contemporaneous \(T_1,T_2\) values for the particular qubits used. IBM’s own device-characterization workflow emphasizes per-qubit SPAM, randomized-benchmarking, \(T_1\), and \(T_2\) measurements rather than a device-wide range. ([quantum.cloud.ibm.com](https://quantum.cloud.ibm.com/docs/en/tutorials/refresh-backend-properties-with-real-time-benchmarking))

- **Cryptographic claims:** High state fidelity alone does not establish authentication, confidentiality, or composable cryptographic security. The conclusion’s description of broadcasting as a useful cryptographic primitive needs either an explicit application/security statement or softer language. fileciteturn0file0L930-L939

- **Incomplete manuscript elements:** The coauthor placeholder and Zenodo placeholder must be resolved, and the code and raw data must actually be deposited. fileciteturn0file0L940-L947

- **References:** The original 1996 no-broadcasting theorem should be cited, not only the 2007 generalized theorem. The device-specific \(T_1\) range should not be attributed to the general Qiskit paper. Reference [3] on self-testing does not appear to support the surrounding introductory claim.

- **Copyediting:** There are frequent grammatical errors and awkward constructions, including “limitations quantum information,” “current hardware are,” “for with QEC,” and “unoptimizated.” A full technical copyedit is necessary.

---

# 2. Impact

## 2.1 Current prospective impact

In its present form, the likely impact is **modest and specialized**.

The underlying protocol family is a relatively small branch of multiparty remote state preparation. The APS pages currently list seven citing articles for the 2022 restricted-state paper and six for the 2023 generalization, indicating an active but focused literature rather than a broad subfield. ([link.aps.org](https://link.aps.org/doi/10.1103/PhysRevA.105.042611))

There is also significant prior-art overlap. A 2024 paper by Kumar and Pathak already:

- frames known-state “broadcasting” as multiparty remote state preparation;
- studies the effects of noise;
- and reports an IBM quantum-computer proof of principle. ([link.springer.com](https://link.springer.com/article/10.1007/s11128-024-04370-5))

That work concerns a different resource construction, so it does not eliminate the novelty here. But it means that “noise plus IBM implementation of quantum broadcasting” is not itself a new contribution. The present paper must define its distinctive advance as some combination of:

- analysis of the particular Sukeno–Hillery \(M\)-sender/\(N\)-receiver resource;
- integration of block-level QEC;
- an exact break-even calculation;
- dynamic-circuit implementation;
- and a controlled study of deviations from independent-channel predictions.

At present, only the first two are clearly present, and the QEC analysis is largely a standard logical-channel calculation once the broadcasting protocol is factored out.

The Monte Carlo work is also unlikely to have substantial methodological impact for independent Pauli noise, because the exact logical channel can be calculated analytically and simulated directly on the logical receiver qubits. The hardware results currently demonstrate that large generic circuits and the chosen five-qubit implementation perform poorly, but they do not yet reveal broadcasting-specific limitations or correlated error structure.

## 2.2 Where the paper could become impactful

There is a potentially strong and coherent paper hidden inside the draft:

1. **A general noise-factorization result.** Show precisely when a receiver channel can be pushed through the Fourier measurement and byproduct corrections. Extend this from depolarizing noise to phase-covariant, Pauli, amplitude-damping, or correlated receiver channels.

2. **An exact QEC threshold.** The exact logical polynomial and
   \[
   p_\star=\frac{3-\sqrt6}{4}
   \]
   provide a clean analytical result and an independent validation of the numerics.

3. **An experimentally controlled breakdown of the independent-channel model.** Compare hardware results against the same transpiled circuit under a calibrated independent noise model, and then directly measure residual correlations.

4. **A scalable circuit construction.** Replace generic state initialization and decoding with structured resource preparation and Clifford QEC circuits.

5. **An operational network metric.** Distinguish local receiver fidelity, global all-receiver fidelity, and application-level success.

The most potentially interesting empirical result is the delay-dependent dropout structure. If its periodicity and physical origin were identified using explicit DD controls, scheduling information, and repeated experiments, it could become a meaningful hardware-noise result rather than an anecdotal observation.

A carefully revised paper could therefore make a **useful contribution to the intersection of restricted remote-state preparation, quantum networking, and small-code hardware benchmarking**. In its current form, however, the mathematical inconsistencies and unsupported causal claims substantially reduce both credibility and likely impact.

---

# 3. Prioritized suggestions for improvement

## 3.1 Rebuild the analytical core

The paper should center two exact propositions.

### Proposition 1: factorization of independent depolarizing noise

For all \(M,N\),

\[
\rho_{\mathrm{out}}
=
\mathcal D_p^{\otimes N}
\left(
|\psi_\Phi\rangle
\langle\psi_\Phi|^{\otimes N}
\right),
\qquad
\Phi=\sum_j\theta_j.
\]

Then state both

\[
F_{\mathrm{local}}=1-\frac{2p}{3},
\qquad
F_{\mathrm{global}}
=
\left(1-\frac{2p}{3}\right)^N.
\]

This immediately separates local robustness from network-level scalability.

### Proposition 2: exact logical channel of the five-qubit code

Replace Equations (31)–(33) with

\[
p_L(p)
=
10p^2-\frac{200}{9}p^3
+\frac{160}{9}p^4
-\frac{128}{27}p^5,
\]

\[
F_{\mathrm{QEC}}(p)
=
1-\frac{2}{3}p_L(p),
\]

and

\[
p_\star=\frac{3-\sqrt6}{4}.
\]

Include either a Pauli-enumerator table or a short appendix deriving the coefficients.

## 3.2 Correct and validate the recovery map

Replace Equation (36) with

\[
|\psi\rangle
\longmapsto
\frac{
V_{\mathrm{Dec}}E_s^\dagger P_s|\psi\rangle
}{
\sqrt{p_s}
},
\qquad
P_s=E_sP_CE_s^\dagger.
\]

Then reconcile this expression with the density-matrix implementation.

Add automated tests for all 16 syndromes, all 15 correctable Pauli errors, trace preservation, logical-channel probabilities, and noiseless fidelity. The code release should make these tests visible.

## 3.3 Simplify the numerical methods

For the independent Pauli model, replace encoded-state propagation with an exact logical channel or Pauli-frame simulation. Retain the statevector Monte Carlo only for models where it is actually necessary, such as coherent errors or explicitly correlated non-Pauli noise.

When Monte Carlo is used:

- average observables directly rather than building \(\widehat\rho\);
- report confidence intervals over independent repetitions;
- fit the convergence exponent rather than showing one realization;
- sum sender measurement branches exactly;
- use the analytical result as the ground truth.

## 3.4 Redesign the hardware implementation

Use:

- a structured Hamming-weight resource-state preparation circuit;
- a known Clifford encoder and inverse decoder for the \([[5,1,3]]\) code;
- explicit stabilizer-recovery circuits;
- a compressed feedforward scheme based only on \(\sum_j n_j\bmod(N+1)\).

For every circuit, report:

\[
\text{qubits},\quad
\text{depth},\quad
\text{two-qubit gates},\quad
\text{duration},\quad
\text{measurements},\quad
\text{conditional operations}.
\]

Run ablation experiments that separately add:

1. Resource-state preparation.
2. Sender phase and Fourier operations.
3. Delay.
4. Dynamic feedforward.
5. Syndrome extraction.
6. Correction.
7. Decoding.

That will identify whether the loss comes from encoding, routing, syndrome measurement, decoder synthesis, or readout.

## 3.5 Test correlations rather than infer them

For each \(M,N\), compare:

- ideal simulation;
- independent depolarizing model;
- backend-calibrated independent gate/readout/thermal model;
- hardware.

From the same receiver readout strings, report:

- average local fidelity;
- worst-receiver fidelity;
- all-zero/global fidelity;
- pairwise receiver covariance;
- invalid sender-qudit outcomes.

Repeat simultaneous and isolated receiver experiments on the same physical qubits. If possible, add idle–idle and driven–idle experiments similar to crosstalk characterization.

Use explicitly controlled DD sequences and compare no-DD, standard DD, and staggered DD. Quantify any periodicity rather than describing it visually.

## 3.6 Narrow and strengthen the claims

A more accurate title would be:

> **Noise and Error Correction in Entanglement-Assisted Restricted-State Broadcasting**

or

> **Noise and Hardware Scaling in Multiparty Remote State Preparation**

A defensible central conclusion would be:

> For independent Pauli-depolarizing receiver links, noise factors through the restricted-state broadcasting protocol. Standard \([[5,1,3]]\) recovery improves local receiver fidelity for \(p<(3-\sqrt6)/4\). A non-fault-tolerant implementation on the tested IBM Kingston calibration snapshot did not reach break-even. Hardware fidelity decreased with circuit size, although the present data do not distinguish accumulated independent circuit errors from correlated noise.

That formulation preserves the genuine findings while removing the conclusions that the current analysis does not establish. After the recovery-map correction, exact logical-channel analysis, structured circuit implementation, and controlled hardware comparison, the manuscript would have a much clearer and more credible contribution.
