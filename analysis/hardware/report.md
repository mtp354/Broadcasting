# Saved hardware readout analysis

Derived from **25 broadcasting jobs / 58 case records / 1581 per-theta, per-delay histograms** and **5 unique standalone memory jobs**. This analysis collected no data and did not change raw JSON files.

Use `scripts/analyze_saved_hardware.py --results-dir RESULTS --output-dir OUTPUT` to reproduce. `summary.json` records source hashes, configuration, execution case/repeat identities, tau-zero estimates, and each trace's spectral summary. `points.json` contains every broadcasting and memory histogram's statistics. See the project README for setup and the collection workflow; `manuscript/figure_sources.json` pins publication inputs.

## Execution identity and inserted delays

Case names are labels; the archived factor vector defines the intervention. For receiver i, `added delay = receiver_delay_factors[i] × tau_dt`, in backend dt units. A zero factor inserts no extra delay on that receiver. Other gates and scheduler-induced idle time still contribute. Spectral periods are reported against the sweep parameter tau, not each receiver's multiplied delay.

| Run ID | Repeat (zero-based) | Runtime job ID | Case | Receiver delay factors |
|---|---:|---|---|---|
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m3_n2 | [1, 1] |
| 5bfbc6524097416e8c6642cc0568c656 | 0 | dago8l8mhr3c73e5ejq0 | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m1_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m1_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m2_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m1_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m3_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m1_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m2_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m3_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m2_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m2_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m3_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m2_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m3_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m2_n1 | [1] |
| 5bfbc6524097416e8c6642cc0568c656 | 1 | dago8lomhr3c73e5ejrg | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m1_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m1_n2 | [1, 1] |
| 5bfbc6524097416e8c6642cc0568c656 | 2 | dago8m39k43c73adlll0 | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m3_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m2_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m3_n2 | [1, 1] |
| 132048dd9bb34e83b92f8bd556a82d39 | 1 | dagbmv7i3e6s738m6esg | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m2_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m3_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m2_n1 | [1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m3_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m3_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m3_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m2_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m1_n4 | [1, 1, 1, 1] |
| 132048dd9bb34e83b92f8bd556a82d39 | 2 | dagbmvfi3e6s738m6eu0 | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m2_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m1_n3 | [1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m1_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m3_n4 | [1, 1, 1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 0 | dagc3m0mhr3c73e4uee0 | m2_n4 | [1, 1, 1, 1] |
| 132048dd9bb34e83b92f8bd556a82d39 | 0 | dagbmuhhvn6c73cqci1g | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 1 | dagc3momhr3c73e4uefg | m1_n2 | [1, 1] |
| cdee2ecff84c48eaa180e7be593ef00f | 2 | dagc3nfi3e6s738m6u50 | m1_n1 | [1] |

## Definitions and uncertainty

Receiver success is the zero bit in the target-basis readout, using little-endian receiver ordering. Joint fidelity is the all-zero frequency; worst fidelity is the minimum receiver marginal. The product of marginals is reported separately and is not assumed equal to joint success. Mean-fidelity uncertainty includes shot-level receiver covariances.

Marginal and joint intervals are two-sided 95% Wilson intervals. The worst-receiver interval uses minimum bounds from Bonferroni-adjusted Wilson intervals, approximately accounting for receiver selection. Covariance and paired differences use asymptotic multinomial delta-method intervals, unadjusted for comparisons over delays/pairs; these may degenerate at boundary counts. Covariance means E[Xi Xj] − E[Xi]E[Xj].

These intervals assume independent shots with fixed probabilities within each histogram. They exclude calibration drift, temporal shot correlation, and job-to-job variation. Cases sharing a Runtime job remain distinct cases, not independent job repetitions. Counts are never pooled across jobs, cases, theta samples, or delays. Canonical delay order in a saved array does not imply execution order; consult the saved submitted PUB order, shot alignment, and execution-span metadata when available.

Nonzero success covariance does not identify correlated physical noise: shared preparation, feedforward, readout, and drift can contribute. Zero covariance in this basis also does not rule out correlated noise.

## Tau-zero broadcasting results

Rows remain separate by job/case/theta. `scaling_points.json` contains the opt3, zero-delay receiver means and ranges with each observation's identity. Receiver ranges describe heterogeneity, not statistical uncertainty. All optimization levels remain in the statistics below. Figure rendering is controlled in `visualizations.ipynb`.

| Run or repeat/case / theta | Backend / opt / shots | M,N | Mean | Worst (95%) | Joint (95%) | Receiver range |
|---|---|---|---:|---|---|---:|
| repeat 0 / m3_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 3,2 | 0.4943 | 0.4905 [0.4781, 0.5029] | 0.2467 [0.2375, 0.2562] | 0.0077 |
| repeat 0 / m1_n2 / θ0 | ibm_kingston / 3 / 10000 | 1,2 | 0.8516 | 0.8133 [0.8044, 0.8219] | 0.7399 [0.7312, 0.7484] | 0.0766 |
| 1ae607ae77f87dc162ba8f01 / θ0 | ibm_kingston / 3 / 10000 | 1,2 | 0.9099 | 0.8941 [0.8870, 0.9008] | 0.8493 [0.8422, 0.8562] | 0.0316 |
| repeat 1 / m1_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 1,4 | 0.5479 | 0.4138 [0.4003, 0.4275] | 0.0861 [0.0802, 0.0923] | 0.2230 |
| repeat 0 / m1_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 1,1 | 0.9650 | 0.9650 [0.9608, 0.9687] | 0.9650 [0.9608, 0.9687] | 0.0000 |
| repeat 0 / m2_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 2,1 | 0.8831 | 0.8831 [0.8759, 0.8898] | 0.8831 [0.8759, 0.8898] | 0.0000 |
| 33f32cfedb0f423158c6e25d / θ0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8330 | 0.7937 [0.7792, 0.8075] | 0.7170 [0.7030, 0.7306] | 0.0786 |
| repeat 0 / m1_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 1,3 | 0.8601 | 0.8204 [0.8101, 0.8304] | 0.7107 [0.7008, 0.7204] | 0.0629 |
| repeat 2 / m3_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 3,1 | 0.8878 | 0.8878 [0.8808, 0.8945] | 0.8878 [0.8808, 0.8945] | 0.0000 |
| repeat 1 / m1_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 1,1 | 0.9655 | 0.9655 [0.9613, 0.9692] | 0.9655 [0.9613, 0.9692] | 0.0000 |
| repeat 0 / m2_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 2,3 | 0.5572 | 0.5253 [0.5120, 0.5385] | 0.2200 [0.2111, 0.2291] | 0.0624 |
| 38cff65a6e2f2859f7eb55bd / θ0 | ibm_kingston / 0 / 10000 | 1,2 | 0.8077 | 0.7662 [0.7566, 0.7756] | 0.6705 [0.6612, 0.6796] | 0.0830 |
| repeat 0 / m3_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 3,1 | 0.9042 | 0.9042 [0.8976, 0.9104] | 0.9042 [0.8976, 0.9104] | 0.0000 |
| repeat 1 / m2_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 2,2 | 0.6371 | 0.6086 [0.5965, 0.6207] | 0.4296 [0.4189, 0.4403] | 0.0569 |
| 4376189d8a394b68adef32da / θ0 | ibm_marrakesh / 3 / 4096 | 1,4 | 0.5839 | 0.4392 [0.4199, 0.4587] | 0.1228 [0.1131, 0.1332] | 0.2124 |
| repeat 0 / m2_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 2,2 | 0.6431 | 0.5978 [0.5856, 0.6099] | 0.4464 [0.4357, 0.4572] | 0.0907 |
| repeat 2 / m3_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 3,3 | 0.4991 | 0.4917 [0.4785, 0.5049] | 0.1285 [0.1215, 0.1360] | 0.0155 |
| repeat 2 / m2_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 2,3 | 0.5402 | 0.4995 [0.4863, 0.5127] | 0.1797 [0.1715, 0.1882] | 0.0948 |
| 4d34aec3527ddb3d88d9dcff / θ0 | ibm_marrakesh / 3 / 4096 | 2,2 | 0.6599 | 0.6130 [0.5959, 0.6299] | 0.4922 [0.4769, 0.5075] | 0.0938 |
| 543ec95c4cc789df373e4844 / θ0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8474 | 0.8350 [0.8216, 0.8475] | 0.7473 [0.7338, 0.7604] | 0.0249 |
| repeat 0 / m1_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8510 | 0.8169 [0.8071, 0.8263] | 0.7537 [0.7442, 0.7629] | 0.0681 |
| 65b5b2a16ea8a1d85a8ad993 / θ0 | ibm_fez / 3 / 4096 | 2,4 | 0.5009 | 0.4990 [0.4795, 0.5185] | 0.0632 [0.0562, 0.0711] | 0.0039 |
| repeat 2 / m3_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 3,2 | 0.5020 | 0.5016 [0.4892, 0.5140] | 0.2562 [0.2469, 0.2658] | 0.0007 |
| repeat 2 / m2_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 2,1 | 0.9111 | 0.9111 [0.9048, 0.9171] | 0.9111 [0.9048, 0.9171] | 0.0000 |
| repeat 1 / m1_n2 / θ0 | ibm_kingston / 3 / 10000 | 1,2 | 0.8739 | 0.8482 [0.8400, 0.8561] | 0.7782 [0.7700, 0.7862] | 0.0513 |
| repeat 1 / m1_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 1,3 | 0.8619 | 0.8231 [0.8128, 0.8330] | 0.7157 [0.7058, 0.7254] | 0.0654 |
| repeat 2 / m1_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8765 | 0.8442 [0.8350, 0.8530] | 0.7888 [0.7798, 0.7975] | 0.0646 |
| 7f4106c6a7d604ef0a1f4eae / θ0 | ibm_kingston / 3 / 4096 | 1,2 | 0.9368 | 0.9329 [0.9236, 0.9411] | 0.8899 [0.8799, 0.8991] | 0.0078 |
| repeat 2 / m1_n2 / θ0 | ibm_kingston / 3 / 10000 | 1,2 | 0.8632 | 0.8432 [0.8349, 0.8512] | 0.7640 [0.7556, 0.7722] | 0.0400 |
| repeat 1 / m3_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 3,1 | 0.8862 | 0.8862 [0.8792, 0.8929] | 0.8862 [0.8792, 0.8929] | 0.0000 |
| repeat 1 / m2_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 2,3 | 0.5528 | 0.5161 [0.5029, 0.5293] | 0.1947 [0.1863, 0.2034] | 0.0875 |
| 974670afccc7483c79bca571 / θ0 | ibm_marrakesh / 3 / 4096 | 2,3 | 0.5500 | 0.4995 [0.4808, 0.5182] | 0.1709 [0.1597, 0.1827] | 0.0769 |
| a39c3727abe65d9cc50d294b / θ0 | ibm_marrakesh / 3 / 4096 | 3,2 | 0.5042 | 0.5017 [0.4842, 0.5192] | 0.2317 [0.2190, 0.2449] | 0.0049 |
| repeat 1 / m3_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 3,2 | 0.4976 | 0.4873 [0.4749, 0.4997] | 0.2476 [0.2383, 0.2570] | 0.0205 |
| repeat 1 / m1_n2 / θ0 | ibm_marrakesh / 3 / 10000 | 1,2 | 0.8964 | 0.8687 [0.8609, 0.8761] | 0.8168 [0.8091, 0.8243] | 0.0555 |
| repeat 2 / m2_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 2,4 | 0.5057 | 0.4938 [0.4800, 0.5076] | 0.0641 [0.0590, 0.0696] | 0.0201 |
| ba15591d96b69402dac7d118 / θ0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8470 | 0.7676 [0.7570, 0.7779] | 0.7217 [0.7119, 0.7313] | 0.1588 |
| c07774de7a0920cbd0535e08 / θ0 | ibm_fez / 3 / 8192 | 1,2 | 0.8542 | 0.8234 [0.8137, 0.8326] | 0.7582 [0.7488, 0.7673] | 0.0618 |
| repeat 0 / m3_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 3,3 | 0.4960 | 0.4938 [0.4806, 0.5070] | 0.1304 [0.1233, 0.1378] | 0.0046 |
| repeat 1 / m2_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 2,1 | 0.9042 | 0.9042 [0.8976, 0.9104] | 0.9042 [0.8976, 0.9104] | 0.0000 |
| repeat 1 / m3_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 3,3 | 0.4941 | 0.4913 [0.4781, 0.5046] | 0.1276 [0.1205, 0.1350] | 0.0050 |
| c4ba9ede78845082431371a0 / θ0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8843 | 0.8695 [0.8609, 0.8776] | 0.8088 [0.8002, 0.8172] | 0.0295 |
| c529a7490b5bf79ddaf55820 / θ0 | ibm_fez / 3 / 8192 | 1,2 | 0.9222 | 0.9053 [0.8978, 0.9123] | 0.8711 [0.8637, 0.8782] | 0.0338 |
| c529a7490b5bf79ddaf55820 / θ1 | ibm_fez / 3 / 8192 | 1,2 | 0.9155 | 0.9056 [0.8981, 0.9126] | 0.8583 [0.8506, 0.8657] | 0.0197 |
| repeat 0 / m3_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 3,4 | 0.5109 | 0.5022 [0.4884, 0.5160] | 0.0575 [0.0527, 0.0627] | 0.0183 |
| repeat 1 / m3_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 3,4 | 0.5123 | 0.5029 [0.4891, 0.5167] | 0.0544 [0.0497, 0.0596] | 0.0170 |
| da461d64d8ee22a3c723c96c / θ0 | ibm_marrakesh / 3 / 4096 | 1,2 | 0.8655 | 0.8215 [0.8077, 0.8345] | 0.7625 [0.7492, 0.7752] | 0.0879 |
| repeat 1 / m2_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 2,4 | 0.5027 | 0.4956 [0.4818, 0.5094] | 0.0586 [0.0537, 0.0639] | 0.0151 |
| repeat 0 / m1_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 1,4 | 0.5538 | 0.4344 [0.4208, 0.4482] | 0.0905 [0.0844, 0.0969] | 0.2018 |
| de371f1284d64792dbec0f3f / θ0 | ibm_marrakesh / 3 / 4096 | 1,3 | 0.8477 | 0.7031 [0.6858, 0.7199] | 0.6189 [0.6039, 0.6337] | 0.2261 |
| repeat 2 / m1_n2 / θ0 | ibm_marrakesh / 3 / 10000 | 1,2 | 0.9086 | 0.8998 [0.8929, 0.9063] | 0.8446 [0.8374, 0.8516] | 0.0177 |
| repeat 2 / m2_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 2,2 | 0.6196 | 0.6014 [0.5893, 0.6135] | 0.4154 [0.4048, 0.4261] | 0.0363 |
| repeat 2 / m1_n3 / θ0 | ibm_marrakesh / 3 / 8192 | 1,3 | 0.8543 | 0.8073 [0.7966, 0.8175] | 0.7032 [0.6933, 0.7130] | 0.0786 |
| repeat 2 / m1_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 1,4 | 0.5597 | 0.4290 [0.4154, 0.4427] | 0.0977 [0.0914, 0.1043] | 0.2191 |
| repeat 2 / m3_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 3,4 | 0.5093 | 0.4954 [0.4816, 0.5092] | 0.0544 [0.0497, 0.0596] | 0.0320 |
| repeat 0 / m2_n4 / θ0 | ibm_marrakesh / 3 / 8192 | 2,4 | 0.5025 | 0.4912 [0.4774, 0.5050] | 0.0610 [0.0561, 0.0664] | 0.0231 |
| repeat 0 / m1_n2 / θ0 | ibm_marrakesh / 3 / 10000 | 1,2 | 0.9023 | 0.8760 [0.8684, 0.8832] | 0.8323 [0.8249, 0.8395] | 0.0526 |
| repeat 1 / m1_n2 / θ0 | ibm_marrakesh / 3 / 8192 | 1,2 | 0.8692 | 0.8375 [0.8282, 0.8465] | 0.7775 [0.7683, 0.7863] | 0.0634 |
| repeat 2 / m1_n1 / θ0 | ibm_marrakesh / 3 / 8192 | 1,1 | 0.9680 | 0.9680 [0.9640, 0.9716] | 0.9680 [0.9640, 0.9716] | 0.0000 |

## Pair covariance and receiver asymmetry

Every two-receiver tau-zero pair is shown as estimate ± asymptotic SE. All other pairs and delays are in `points.json`. No multiplicity-adjusted significance claim is made.

| Run or repeat/case / theta | Cov(success 0, success 1) | F0 − F1 |
|---|---:|---:|
| repeat 0 / m3_n2 / θ0 | 0.00236 ± 0.00276 | 0.00769 ± 0.00777 |
| repeat 0 / m1_n2 / θ0 | 0.01614 ± 0.00150 | 0.07660 ± 0.00466 |
| 1ae607ae77f87dc162ba8f01 / θ0 | 0.02163 ± 0.00143 | -0.03160 ± 0.00347 |
| 33f32cfedb0f423158c6e25d / θ0 | 0.02468 ± 0.00263 | 0.07861 ± 0.00742 |
| 38cff65a6e2f2859f7eb55bd / θ0 | 0.01984 ± 0.00173 | 0.08300 ± 0.00517 |
| repeat 1 / m2_n2 / θ0 | 0.02450 ± 0.00257 | 0.05688 ± 0.00709 |
| repeat 0 / m2_n2 / θ0 | 0.03485 ± 0.00254 | 0.09070 ± 0.00686 |
| 4d34aec3527ddb3d88d9dcff / θ0 | 0.05890 ± 0.00354 | 0.09375 ± 0.00893 |
| 543ec95c4cc789df373e4844 / θ0 | 0.02936 ± 0.00270 | 0.02490 ± 0.00698 |
| repeat 0 / m1_n2 / θ0 | 0.03070 ± 0.00189 | 0.06812 ± 0.00482 |
| repeat 2 / m3_n2 / θ0 | 0.00427 ± 0.00276 | 0.00073 ± 0.00775 |
| repeat 1 / m1_n2 / θ0 | 0.01524 ± 0.00141 | 0.05130 ± 0.00434 |
| repeat 2 / m1_n2 / θ0 | 0.02156 ± 0.00166 | 0.06458 ± 0.00457 |
| 7f4106c6a7d604ef0a1f4eae / θ0 | 0.01237 ± 0.00177 | 0.00781 ± 0.00478 |
| repeat 2 / m1_n2 / θ0 | 0.01929 ± 0.00153 | 0.04000 ± 0.00444 |
| a39c3727abe65d9cc50d294b / θ0 | -0.02247 ± 0.00389 | -0.00488 ± 0.01153 |
| repeat 1 / m3_n2 / θ0 | 0.00010 ± 0.00276 | 0.02051 ± 0.00781 |
| repeat 1 / m1_n2 / θ0 | 0.01395 ± 0.00129 | -0.05550 ± 0.00395 |
| ba15591d96b69402dac7d118 / θ0 | 0.01060 ± 0.00144 | 0.15881 ± 0.00525 |
| c07774de7a0920cbd0535e08 / θ0 | 0.02939 ± 0.00187 | -0.06177 ± 0.00479 |
| c4ba9ede78845082431371a0 / θ0 | 0.02711 ± 0.00177 | 0.02954 ± 0.00428 |
| c529a7490b5bf79ddaf55820 / θ0 | 0.02096 ± 0.00154 | 0.03381 ± 0.00351 |
| c529a7490b5bf79ddaf55820 / θ1 | 0.02029 ± 0.00154 | -0.01965 ± 0.00373 |
| da461d64d8ee22a3c723c96c / θ0 | 0.01533 ± 0.00220 | 0.08789 ± 0.00696 |
| repeat 2 / m1_n2 / θ0 | 0.01903 ± 0.00138 | -0.01770 ± 0.00357 |
| repeat 2 / m2_n2 / θ0 | 0.03187 ± 0.00262 | 0.03625 ± 0.00705 |
| repeat 0 / m1_n2 / θ0 | 0.01885 ± 0.00138 | -0.05260 ± 0.00370 |
| repeat 1 / m1_n2 / θ0 | 0.02296 ± 0.00171 | 0.06335 ± 0.00468 |

## Invalid sender outcomes

Saved invalid-outcome rates are retained for each histogram in `points.json`. The range below spans recorded settings within a run; it is not an uncertainty interval. Unrecorded diagnostics remain unknown. No shots are postselected, and sender--receiver conditional analysis requires the saved aligned readouts.

| Run | Histograms with recorded rates | Minimum rate | Maximum rate |
|---|---:|---:|---:|
| repeat 0 / m3_n2 | 1 | 0.260376 | 0.260376 |
| repeat 0 / m1_n2 | 121 | 0.017700 | 0.297000 |
| 1ae607ae77f87dc162ba8f01 | 0 | unrecorded | unrecorded |
| repeat 1 / m1_n4 | 1 | 0.102783 | 0.102783 |
| repeat 0 / m1_n1 | 1 | 0.000000 | 0.000000 |
| repeat 0 / m2_n1 | 1 | 0.000000 | 0.000000 |
| 33f32cfedb0f423158c6e25d | 0 | unrecorded | unrecorded |
| repeat 0 / m1_n3 | 1 | 0.000000 | 0.000000 |
| repeat 2 / m3_n1 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m1_n1 | 1 | 0.000000 | 0.000000 |
| repeat 0 / m2_n3 | 1 | 0.000000 | 0.000000 |
| 38cff65a6e2f2859f7eb55bd | 0 | unrecorded | unrecorded |
| repeat 0 / m3_n1 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m2_n2 | 1 | 0.056519 | 0.056519 |
| 4376189d8a394b68adef32da | 0 | unrecorded | unrecorded |
| repeat 0 / m2_n2 | 1 | 0.065063 | 0.065063 |
| repeat 2 / m3_n3 | 1 | 0.000000 | 0.000000 |
| repeat 2 / m2_n3 | 1 | 0.000000 | 0.000000 |
| 4d34aec3527ddb3d88d9dcff | 0 | unrecorded | unrecorded |
| 543ec95c4cc789df373e4844 | 0 | unrecorded | unrecorded |
| repeat 0 / m1_n2 | 1 | 0.017578 | 0.017578 |
| 65b5b2a16ea8a1d85a8ad993 | 0 | unrecorded | unrecorded |
| repeat 2 / m3_n2 | 1 | 0.239990 | 0.239990 |
| repeat 2 / m2_n1 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m1_n2 | 121 | 0.016700 | 0.278400 |
| repeat 1 / m1_n3 | 1 | 0.000000 | 0.000000 |
| repeat 2 / m1_n2 | 1 | 0.013184 | 0.013184 |
| 7f4106c6a7d604ef0a1f4eae | 0 | unrecorded | unrecorded |
| repeat 2 / m1_n2 | 121 | 0.018400 | 0.290400 |
| repeat 1 / m3_n1 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m2_n3 | 1 | 0.000000 | 0.000000 |
| 974670afccc7483c79bca571 | 0 | unrecorded | unrecorded |
| a39c3727abe65d9cc50d294b | 0 | unrecorded | unrecorded |
| repeat 1 / m3_n2 | 1 | 0.260010 | 0.260010 |
| repeat 1 / m1_n2 | 121 | 0.013500 | 0.203300 |
| repeat 2 / m2_n4 | 1 | 0.387451 | 0.387451 |
| ba15591d96b69402dac7d118 | 0 | unrecorded | unrecorded |
| c07774de7a0920cbd0535e08 | 0 | unrecorded | unrecorded |
| repeat 0 / m3_n3 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m2_n1 | 1 | 0.000000 | 0.000000 |
| repeat 1 / m3_n3 | 1 | 0.000000 | 0.000000 |
| c4ba9ede78845082431371a0 | 0 | unrecorded | unrecorded |
| c529a7490b5bf79ddaf55820 | 0 | unrecorded | unrecorded |
| repeat 0 / m3_n4 | 1 | 0.622437 | 0.622437 |
| repeat 1 / m3_n4 | 1 | 0.594727 | 0.594727 |
| da461d64d8ee22a3c723c96c | 0 | unrecorded | unrecorded |
| repeat 1 / m2_n4 | 1 | 0.375366 | 0.375366 |
| repeat 0 / m1_n4 | 1 | 0.105469 | 0.105469 |
| de371f1284d64792dbec0f3f | 0 | unrecorded | unrecorded |
| repeat 2 / m1_n2 | 121 | 0.013200 | 0.197600 |
| repeat 2 / m2_n2 | 1 | 0.058472 | 0.058472 |
| repeat 2 / m1_n3 | 1 | 0.000000 | 0.000000 |
| repeat 2 / m1_n4 | 1 | 0.102173 | 0.102173 |
| repeat 2 / m3_n4 | 1 | 0.592041 | 0.592041 |
| repeat 0 / m2_n4 | 1 | 0.389648 | 0.389648 |
| repeat 0 / m1_n2 | 121 | 0.017200 | 0.206700 |
| repeat 1 / m1_n2 | 1 | 0.016357 | 0.016357 |
| repeat 2 / m1_n1 | 1 | 0.000000 | 0.000000 |

## Delay periodicity

Each receiver and receiver-mean trace is analyzed separately for each job/case/theta. Uniform sweeps with at least eight points use a linearly detrended Hann periodogram. Saved summaries include the dominant nonzero frequency, Fourier-bin resolution, cycles observed, selected-frequency sinusoid amplitude, and first positive autocorrelation peak. A peak selected from the same trace is exploratory, with no post-selection significance or physical-cause inference. Fewer than three observed cycles are poorly resolved against drift; fewer than four samples per cycle are near Nyquist and limited by sampling/aliasing. Independent repetitions are needed for frequency uncertainty.

The table reports receiver-mean peaks. Recorded or evidence-attributed dt converts time to microseconds; otherwise native dt is retained. Frequency resolution is in cycles per displayed unit.

| Run or repeat/case / theta | Dominant period | Frequency resolution | Cycles in span | Trend-residual variance explained |
|---|---:|---:|---:|---:|
| repeat 0 / m3_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.917 |
| 1ae607ae77f87dc162ba8f01 / θ0 | 0.504 us | 0.041322 | 47.60 (near Nyquist) | 0.066 |
| repeat 1 / m1_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m1_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m2_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 33f32cfedb0f423158c6e25d / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m1_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m3_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m1_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m2_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 38cff65a6e2f2859f7eb55bd / θ0 | 0.440 us | 0.041322 | 54.55 (near Nyquist) | 0.049 |
| repeat 0 / m3_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m2_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 4376189d8a394b68adef32da / θ0 | 615.000 dt | 0.000163 | 9.76 | 0.199 |
| repeat 0 / m2_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m3_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m2_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 4d34aec3527ddb3d88d9dcff / θ0 | 410.000 dt | 0.000163 | 14.63 (near Nyquist) | 0.176 |
| 543ec95c4cc789df373e4844 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.984 |
| repeat 0 / m1_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 65b5b2a16ea8a1d85a8ad993 / θ0 | 361.765 dt | 0.000163 | 16.59 (near Nyquist) | 0.256 |
| repeat 2 / m3_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m2_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.956 |
| repeat 1 / m1_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m1_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 7f4106c6a7d604ef0a1f4eae / θ0 | 273.333 dt | 0.000244 | 14.63 (near Nyquist) | 0.114 |
| repeat 2 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.909 |
| repeat 1 / m3_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m2_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| 974670afccc7483c79bca571 / θ0 | 307.500 dt | 0.000163 | 19.51 (near Nyquist) | 0.071 |
| a39c3727abe65d9cc50d294b / θ0 | 307.500 dt | 0.000163 | 19.51 (near Nyquist) | 0.181 |
| repeat 1 / m3_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.929 |
| repeat 2 / m2_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| ba15591d96b69402dac7d118 / θ0 | 361.765 dt | 0.000163 | 16.59 (near Nyquist) | 0.135 |
| c07774de7a0920cbd0535e08 / θ0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.784 |
| repeat 0 / m3_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m2_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m3_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| c4ba9ede78845082431371a0 / θ0 | Unavailable: Fewer than eight delay points. | — | — | — |
| c529a7490b5bf79ddaf55820 / θ0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.839 |
| c529a7490b5bf79ddaf55820 / θ1 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.858 |
| repeat 0 / m3_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m3_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| da461d64d8ee22a3c723c96c / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 1 / m2_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m1_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| de371f1284d64792dbec0f3f / θ0 | 6150.000 dt | 0.000163 | 0.98 (few cycles) | 0.663 |
| repeat 2 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.963 |
| repeat 2 / m2_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m1_n3 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m1_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m3_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m2_n4 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 0 / m1_n2 / θ0 | 24.200 us | 0.041322 | 0.99 (few cycles) | 0.964 |
| repeat 1 / m1_n2 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |
| repeat 2 / m1_n1 / θ0 | Unavailable: Need at least two tau points for periodicity analysis. | — | — | — |

## Standalone memory records

Duplicate job saves are excluded. One recovered-qubit readout is available, so receiver-pair quantities are undefined. Encoding is reported as unknown unless recorded or attributed with evidence in the record provenance.

| File | Backend / opt / encoding | Shots | F(first delay), 95% Wilson | F(final delay), 95% Wilson |
|---|---|---:|---|---|
| run_025ae13e0183f58f80e31d03.json | ibm_kingston / 3 / bare | 8192 | 0.9971 [0.9956, 0.9980] | 0.6670 [0.6567, 0.6771] |
| run_2c91bf3308b84e88c880b308.json | ibm_kingston / 0 / bare | 8192 | 0.9323 [0.9266, 0.9375] | 0.8661 [0.8585, 0.8733] |
| run_48c5255eac91a1784c73944f.json | ibm_kingston / 3 / encoded | 8192 | 0.4775 [0.4667, 0.4884] | 0.4709 [0.4602, 0.4818] |
| run_885e2eb2a61644d5bb36cf17.json | ibm_fez / 0 / encoded | 8192 | 0.4662 [0.4554, 0.4770] | 0.4769 [0.4661, 0.4878] |
| run_c9961cc71daa5d823a57cd68.json | ibm_kingston / 0 / encoded | 8192 | 0.4906 [0.4798, 0.5014] | 0.4846 [0.4738, 0.4954] |
