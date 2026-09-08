# Reanalysis of existing hardware readouts

Derived from **16 broadcasting jobs / 819 per-theta, per-delay histograms** and **5 unique standalone memory jobs**. No new circuits, trajectories, or hardware jobs were collected. Raw JSON files were not changed.

Reproduce with `.venv/bin/python scripts/analyze_saved_hardware.py`. `summary.json` records source hashes, run metadata, tau-zero estimates and every trace's spectral summary; `points.json` contains all broadcasting point estimates, confidence intervals, paired differences and covariances. `figures/sources.json` pins publication inputs and records historical attribution evidence.

## Definitions and uncertainty

Receiver success is the zero bit in its target-basis readout, using little-endian receiver ordering. Joint/global fidelity is the observed all-zero frequency; worst fidelity is the minimum receiver marginal. The product of marginals is reported separately and is not assumed equal to the observed joint probability. Mean-fidelity uncertainty includes the shot-level receiver covariances.

Marginal and joint intervals are two-sided 95% Wilson score intervals. The worst-receiver interval takes the minimum bounds of Bonferroni-adjusted Wilson intervals, so receiver selection is accounted for approximately. Pair covariance and paired receiver differences use multinomial delta-method 95% intervals; these are asymptotic, unadjusted for comparisons over delays/pairs, and can degenerate at boundary counts. The covariance convention is E[Xi Xj] − E[Xi]E[Xj] in each empirical histogram.

These intervals quantify finite-shot uncertainty conditional on fixed probabilities and independent shots within a histogram. They exclude calibration drift, temporal shot correlation, and job-to-job variation. Historical counts lack shot ordering, calibrated layouts, and circuit revisions, so that assumption cannot be verified. No counts are pooled across jobs, theta samples or delay points.

Nonzero receiver-success covariance does not identify correlated physical noise. Shared preparation, feedforward, readout, and within-job drift can contribute; conversely, zero measured covariance does not rule out correlated noise in other bases.

## Tau-zero broadcasting results

Every point is shown separately. Dates/time in the source filename identify the run; theta index distinguishes multiple samples within a job. The receiver range in `tau0_fidelities.png` is receiver heterogeneity, not statistical uncertainty. `joint_and_worst_tau0.png` shows shot intervals.

| Run / theta | Backend / opt / shots | M,N | Mean | Worst (95% interval) | Joint (95% interval) | Receiver range |
|---|---|---|---:|---|---|---:|
| 20260408_160814 / 0 | ibm_kingston / 3 / 4096 | 1,2 | 0.9368 | 0.9329 [0.9236, 0.9411] | 0.8899 [0.8799, 0.8991] | 0.0078 |
| 20260408_161340 / 0 | ibm_marrakesh / 3 / 4096 | 1,3 | 0.8477 | 0.7031 [0.6858, 0.7199] | 0.6189 [0.6039, 0.6337] | 0.2261 |
| 20260408_161902 / 0 | ibm_marrakesh / 3 / 4096 | 1,4 | 0.5839 | 0.4392 [0.4199, 0.4587] | 0.1228 [0.1131, 0.1332] | 0.2124 |
| 20260408_162212 / 0 | ibm_marrakesh / 3 / 4096 | 2,2 | 0.6599 | 0.6130 [0.5959, 0.6299] | 0.4922 [0.4769, 0.5075] | 0.0938 |
| 20260408_162440 / 0 | ibm_marrakesh / 3 / 4096 | 2,3 | 0.5500 | 0.4995 [0.4808, 0.5182] | 0.1709 [0.1597, 0.1827] | 0.0769 |
| 20260408_162906 / 0 | ibm_fez / 3 / 4096 | 2,4 | 0.5009 | 0.4990 [0.4795, 0.5185] | 0.0632 [0.0562, 0.0711] | 0.0039 |
| 20260408_163129 / 0 | ibm_marrakesh / 3 / 4096 | 3,2 | 0.5042 | 0.5017 [0.4842, 0.5192] | 0.2317 [0.2190, 0.2449] | 0.0049 |
| 20260408_170544 / 0 | ibm_fez / 3 / 8192 | 1,2 | 0.9222 | 0.9053 [0.8978, 0.9123] | 0.8711 [0.8637, 0.8782] | 0.0338 |
| 20260408_170544 / 1 | ibm_fez / 3 / 8192 | 1,2 | 0.9155 | 0.9056 [0.8981, 0.9126] | 0.8583 [0.8506, 0.8657] | 0.0197 |
| 20260513_141704 / 0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8843 | 0.8695 [0.8609, 0.8776] | 0.8088 [0.8002, 0.8172] | 0.0295 |
| 20260513_144130 / 0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8470 | 0.7676 [0.7570, 0.7779] | 0.7217 [0.7119, 0.7313] | 0.1588 |
| 20260513_150433 / 0 | ibm_fez / 3 / 8192 | 1,2 | 0.8542 | 0.8234 [0.8137, 0.8326] | 0.7582 [0.7488, 0.7673] | 0.0618 |
| 20260518_120232 / 0 | ibm_kingston / 3 / 10000 | 1,2 | 0.9099 | 0.8941 [0.8870, 0.9008] | 0.8493 [0.8422, 0.8562] | 0.0316 |
| 20260518_122119 / 0 | ibm_kingston / 0 / 10000 | 1,2 | 0.8077 | 0.7662 [0.7566, 0.7756] | 0.6705 [0.6612, 0.6796] | 0.0830 |
| 20260908_132728_4fc6f552 / 0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8655 | 0.8215 [0.8077, 0.8345] | 0.7625 [0.7492, 0.7752] | 0.0879 |
| 20260908_132738_ef85f542 / 0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8330 | 0.7937 [0.7792, 0.8075] | 0.7170 [0.7030, 0.7306] | 0.0786 |
| 20260908_153150_79eab41b / 0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8474 | 0.8350 [0.8216, 0.8475] | 0.7473 [0.7338, 0.7604] | 0.0249 |

## Pair covariance and receiver asymmetry

The table gives every N=2 tau-zero pair, within a single theta/job, as estimate ± asymptotic SE. All other pairs/delays are retained in `points.json`. No multiplicity-adjusted significance claim is made.

| Run / theta | Cov(success 0, success 1) | F0 − F1 |
|---|---:|---:|
| 20260408_160814 / 0 | 0.01237 ± 0.00177 | 0.00781 ± 0.00478 |
| 20260408_162212 / 0 | 0.05890 ± 0.00354 | 0.09375 ± 0.00893 |
| 20260408_163129 / 0 | -0.02247 ± 0.00389 | -0.00488 ± 0.01153 |
| 20260408_170544 / 0 | 0.02096 ± 0.00154 | 0.03381 ± 0.00351 |
| 20260408_170544 / 1 | 0.02029 ± 0.00154 | -0.01965 ± 0.00373 |
| 20260513_141704 / 0 | 0.02711 ± 0.00177 | 0.02954 ± 0.00428 |
| 20260513_144130 / 0 | 0.01060 ± 0.00144 | 0.15881 ± 0.00525 |
| 20260513_150433 / 0 | 0.02939 ± 0.00187 | -0.06177 ± 0.00479 |
| 20260518_120232 / 0 | 0.02163 ± 0.00143 | -0.03160 ± 0.00347 |
| 20260518_122119 / 0 | 0.01984 ± 0.00173 | 0.08300 ± 0.00517 |
| 20260908_132728_4fc6f552 / 0 | 0.01533 ± 0.00220 | 0.08789 ± 0.00696 |
| 20260908_132738_ef85f542 / 0 | 0.02468 ± 0.00263 | 0.07861 ± 0.00742 |
| 20260908_153150_79eab41b / 0 | 0.02936 ± 0.00270 | 0.02490 ± 0.00698 |

## Delay periodicity

Each receiver and receiver-mean trace is analyzed separately for each theta. Uniform sweeps with at least eight points use a linearly detrended Hann periodogram. The dominant nonzero frequency, Fourier-bin resolution, cycles in the observed span, selected-frequency sinusoid amplitude and first positive autocorrelation peak are saved. Peaks selected from the same trace are exploratory; no post-selection significance or shared physical cause is established. Fewer than three cycles are flagged as poorly resolved against smooth drift; fewer than four grid samples per cycle are flagged near Nyquist, where aliasing and sampling resolution limit interpretation. Ordered delays also confound elapsed acquisition time with delay, and no repetition-based frequency uncertainty can be recovered.

The table reports receiver-mean trace peaks. Native dt is retained whenever no recorded or documented historical dt is available. Microseconds for May18 Kingston use an explicitly marked same-device/day inference from the memory notebook; September Marrakesh uses dt recorded in the result. Frequency resolution is in cycles per displayed time unit.

| Run / theta | Dominant period | Frequency resolution | Cycles in span | Trend-residual variance explained by selected sinusoid |
|---|---:|---:|---:|---:|
| 20260408_160814 / 0 | 273.333 dt | 0.000244 | 14.63 (near Nyquist) | 0.114 |
| 20260408_161340 / 0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.663 |
| 20260408_161902 / 0 | 615.000 dt | 0.000163 | 9.76 | 0.199 |
| 20260408_162212 / 0 | 410.000 dt | 0.000163 | 14.63 (near Nyquist) | 0.176 |
| 20260408_162440 / 0 | 307.500 dt | 0.000163 | 19.51 (near Nyquist) | 0.071 |
| 20260408_162906 / 0 | 361.765 dt | 0.000163 | 16.59 (near Nyquist) | 0.256 |
| 20260408_163129 / 0 | 307.500 dt | 0.000163 | 19.51 (near Nyquist) | 0.181 |
| 20260408_170544 / 0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.839 |
| 20260408_170544 / 1 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.858 |
| 20260513_141704 / 0 | Unavailable: Fewer than eight delay points. | — | — | — |
| 20260513_144130 / 0 | 361.765 dt | 0.000163 | 16.59 (near Nyquist) | 0.135 |
| 20260513_150433 / 0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.784 |
| 20260518_120232 / 0 | 0.504 us | 0.041322 | 47.60 (near Nyquist) | 0.066 |
| 20260518_122119 / 0 | 0.440 us | 0.041322 | 54.55 (near Nyquist) | 0.049 |
| 20260908_132728_4fc6f552 / 0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 20260908_132738_ef85f542 / 0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 20260908_153150_79eab41b / 0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.984 |

## Standalone memory records

One duplicate save of job d82dopugbeec73allus0 is excluded. Encoded/bare labels were not saved in legacy JSON; the manifest attributes them from archived notebook definitions, job outputs and comparisons. The two bare controls were collected May18 and June18, unlike the encoded May13 runs; they are not controlled same-session comparisons. Fez remains a separate cohort. Joint receiver-pair quantities are undefined for this single recovered-qubit readout.

| File | Backend / opt / encoding | Shots | F(tau=0), 95% Wilson | F(final delay), 95% Wilson |
|---|---|---:|---|---|
| qec513_delay_sweep_20260507_084654.json | ibm_fez / 0 / encoded | 8192 | 0.4662 [0.4554, 0.4770] | 0.4769 [0.4661, 0.4878] |
| qec513_delay_sweep_20260513_123922.json | ibm_kingston / 3 / encoded | 8192 | 0.4775 [0.4667, 0.4884] | 0.4709 [0.4602, 0.4818] |
| qec513_delay_sweep_20260513_163257.json | ibm_kingston / 0 / encoded | 8192 | 0.4906 [0.4798, 0.5014] | 0.4846 [0.4738, 0.4954] |
| qec513_delay_sweep_20260518_132249.json | ibm_kingston / 3 / bare | 8192 | 0.9971 [0.9956, 0.9980] | 0.6670 [0.6567, 0.6771] |
| qec513_delay_sweep_20260618_104151.json | ibm_kingston / 0 / bare | 8192 | 0.9323 [0.9266, 0.9375] | 0.8661 [0.8585, 0.8733] |

## What the saved evidence supports

The saved counts establish joint and marginal target-basis success probabilities and often substantial receiver asymmetry. They permit descriptive delay spectra and comparisons of individual records. Mixed backend, date, shot count, optimization, theta and unarchived circuit/layout history prevent a controlled network-size scaling conclusion. September points remain separate from April/May runs even when nominal settings match.

New controlled repeated sweeps are needed to estimate reproducible periods and between-job uncertainty. Consistent-backend size points with archived effective configuration, compiled circuit/layout, calibration and shot-aligned outputs are needed for scaling. The old multi-seed convergence image remains withdrawn pending correctly seeded and archived repetitions; this reanalysis collected none.
