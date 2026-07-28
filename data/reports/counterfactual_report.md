# Counterfactual Strategy Uniqueness Report

本报告只做结构消融实验，不优化收益、不调整参数、不改默认回测逻辑。

## Experiment Setup

- Label file: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/labels/doc_labels.csv`
- Valid broad labels: 34
- Noise injection: ret20_pct multiplied by deterministic row-level noise in +/-5%
- stability_index: average Jaccard similarity versus baseline same-date holdings
- turnover: average daily target-holding change count on covered label dates

## Baseline (Current System)

- exact_match: 52.94%
- hit_ratio: 76.47%
- turnover: 0.06
- stability_index: 100.00%

## No Risk Overlay

Risk overlay disabled: OVERHEAT, PB block, and market_signal=● suppression are bypassed.

- exact_match: 52.94%
- hit_ratio: 76.47%
- turnover: 0.06
- stability_index: 100.00%

## No Execution Policy

Execution policy disabled: no holding inertia, no replacement threshold, pure risk-filtered top-k.

- exact_match: 50.00%
- hit_ratio: 75.00%
- turnover: 0.41
- stability_index: 62.75%

## Noisy Scoring

Ret20 score input receives deterministic row-level +/-5% noise before ranking.

- exact_match: 52.94%
- hit_ratio: 76.47%
- turnover: 0.06
- stability_index: 100.00%

## Full Ablation Table

| scenario                  |   exact_match |   hit_ratio |   turnover |   stability_index |   exact_delta_vs_baseline |   hit_delta_vs_baseline |
|:--------------------------|--------------:|------------:|-----------:|------------------:|--------------------------:|------------------------:|
| baseline (current system) |         52.94 |       76.47 |       0.06 |            100    |                      0    |                    0    |
| no risk overlay           |         52.94 |       76.47 |       0.06 |            100    |                      0    |                    0    |
| no execution policy       |         50    |       75    |       0.41 |             62.75 |                     -2.94 |                   -1.47 |
| noisy scoring             |         52.94 |       76.47 |       0.06 |            100    |                      0    |                    0    |

## Strategy Identifiability

Interpretation rule: if small perturbation causes large label-match collapse and output instability, the system is treated as a deterministic rule-based strategy; otherwise it is treated as fuzzy or hybrid.

- strategy_identifiability_score: 13.24
- small_perturbation_impact: 0.00
- structural_impact: 13.24
- conclusion: C. non-deterministic / manual-like system
- confidence: 65%

## Date-Level Ablation Detail

| scenario                  | date       | expected           | actual             |   exact |   hit_ratio |   turnover |   stability |
|:--------------------------|:-----------|:-------------------|:-------------------|--------:|------------:|-----------:|------------:|
| baseline (current system) | 2026-05-06 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-07 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-08 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-11 | ['纳指', '创业板50']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-12 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-13 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-14 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-15 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-18 | ['创业板50', '科创50']  | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-19 | ['创业板50', '科创50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-20 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-21 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-22 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-25 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-26 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-27 | ['纳指', '创业板50']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-05-28 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-05-29 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-01 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-02 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-03 | ['纳指', '日经225']    | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-04 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-05 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-08 | ['纳指', '日经225']    | ['纳指', '日经225']    |       1 |         1   |          1 |        1    |
| baseline (current system) | 2026-06-09 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-11 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-12 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-15 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-16 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-17 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-18 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| baseline (current system) | 2026-06-22 | ['日经225', '科创50']  | ['日经225', '纳指']    |       0 |         0.5 |          0 |        1    |
| baseline (current system) | 2026-06-23 | ['日经225', '创业板50'] | ['日经225', '创业板50'] |       1 |         1   |          1 |        1    |
| baseline (current system) | 2026-06-26 | ['日经225', '科创50']  | ['日经225', '创业板50'] |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-06 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-07 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-08 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-11 | ['纳指', '创业板50']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-12 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-13 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-14 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-15 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-18 | ['创业板50', '科创50']  | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-19 | ['创业板50', '科创50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-20 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-21 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-22 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-25 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-26 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-27 | ['纳指', '创业板50']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-05-28 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-05-29 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-01 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-02 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-03 | ['纳指', '日经225']    | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-04 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-05 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-08 | ['纳指', '日经225']    | ['纳指', '日经225']    |       1 |         1   |          1 |        1    |
| no risk overlay           | 2026-06-09 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-11 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-12 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-15 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-16 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-17 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-18 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no risk overlay           | 2026-06-22 | ['日经225', '科创50']  | ['日经225', '纳指']    |       0 |         0.5 |          0 |        1    |
| no risk overlay           | 2026-06-23 | ['日经225', '创业板50'] | ['日经225', '创业板50'] |       1 |         1   |          1 |        1    |
| no risk overlay           | 2026-06-26 | ['日经225', '科创50']  | ['日经225', '创业板50'] |       0 |         0.5 |          0 |        1    |
| no execution policy       | 2026-05-06 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          1 |        1    |
| no execution policy       | 2026-05-07 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| no execution policy       | 2026-05-08 | ['创业板50', '纳指']    | ['科创50', '纳指']     |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-11 | ['纳指', '创业板50']    | ['创业板50', '纳指']    |       1 |         1   |          1 |        1    |
| no execution policy       | 2026-05-12 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-05-13 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-05-14 | ['创业板50', '纳指']    | ['科创50', '创业板50']  |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-15 | ['创业板50', '纳指']    | ['科创50', '创业板50']  |       0 |         0.5 |          0 |        0.33 |
| no execution policy       | 2026-05-18 | ['创业板50', '科创50']  | ['科创50', '创业板50']  |       1 |         1   |          0 |        0.33 |
| no execution policy       | 2026-05-19 | ['创业板50', '科创50']  | ['科创50', '纳指']     |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-20 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          1 |        1    |
| no execution policy       | 2026-05-21 | ['创业板50', '纳指']    | ['科创50', '纳指']     |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-22 | ['纳指', '科创50']     | ['科创50', '纳指']     |       1 |         1   |          0 |        0.33 |
| no execution policy       | 2026-05-25 | ['纳指', '科创50']     | ['纳指', '日经225']    |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-26 | ['纳指', '日经225']    | ['科创50', '纳指']     |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-05-27 | ['纳指', '创业板50']    | ['科创50', '纳指']     |       0 |         0.5 |          0 |        0.33 |
| no execution policy       | 2026-05-28 | ['纳指', '科创50']     | ['科创50', '纳指']     |       1 |         1   |          0 |        0.33 |
| no execution policy       | 2026-05-29 | ['纳指', '科创50']     | ['科创50', '纳指']     |       1 |         1   |          0 |        0.33 |
| no execution policy       | 2026-06-01 | ['纳指', '科创50']     | ['纳指', '日经225']    |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-06-02 | ['纳指', '科创50']     | ['纳指', '日经225']    |       0 |         0.5 |          0 |        0.33 |
| no execution policy       | 2026-06-03 | ['纳指', '日经225']    | ['创业板50', '纳指']    |       0 |         0.5 |          1 |        1    |
| no execution policy       | 2026-06-04 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          1 |        0.33 |
| no execution policy       | 2026-06-05 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        0.33 |
| no execution policy       | 2026-06-08 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-09 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-11 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-12 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-15 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-16 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-17 | ['纳指', '日经225']    | ['日经225', '科创50']  |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-06-18 | ['纳指', '日经225']    | ['日经225', '科创50']  |       0 |         0.5 |          0 |        0.33 |
| no execution policy       | 2026-06-22 | ['日经225', '科创50']  | ['日经225', '创业板50'] |       0 |         0.5 |          1 |        0.33 |
| no execution policy       | 2026-06-23 | ['日经225', '创业板50'] | ['日经225', '创业板50'] |       1 |         1   |          0 |        1    |
| no execution policy       | 2026-06-26 | ['日经225', '科创50']  | ['日经225', '创业板50'] |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-06 | ['科创50', '创业板50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-07 | ['科创50', '创业板50']  | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-08 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-11 | ['纳指', '创业板50']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-12 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-13 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-14 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-15 | ['创业板50', '纳指']    | ['创业板50', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-18 | ['创业板50', '科创50']  | ['创业板50', '纳指']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-19 | ['创业板50', '科创50']  | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-20 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-21 | ['创业板50', '纳指']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-22 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-25 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-26 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-27 | ['纳指', '创业板50']    | ['纳指', '创业板50']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-05-28 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-05-29 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-01 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-02 | ['纳指', '科创50']     | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-03 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-04 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-05 | ['纳指', '日经225']    | ['纳指', '创业板50']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-08 | ['纳指', '日经225']    | ['纳指', '日经225']    |       1 |         1   |          1 |        1    |
| noisy scoring             | 2026-06-09 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-11 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-12 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-15 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-16 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-17 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-18 | ['纳指', '日经225']    | ['日经225', '纳指']    |       1 |         1   |          0 |        1    |
| noisy scoring             | 2026-06-22 | ['日经225', '科创50']  | ['日经225', '纳指']    |       0 |         0.5 |          0 |        1    |
| noisy scoring             | 2026-06-23 | ['日经225', '创业板50'] | ['日经225', '创业板50'] |       1 |         1   |          1 |        1    |
| noisy scoring             | 2026-06-26 | ['日经225', '科创50']  | ['日经225', '创业板50'] |       0 |         0.5 |          0 |        1    |

