# Lookback 20 vs 23 Fit Comparison

Scope: kept all existing strategy parameters unchanged and varied only `lookback_momentum` in memory. `strategy.yaml` was not modified by this comparison run.

## Holding / Signal Fit

|   lookback |   case_count |   docx_count |   manual_count |   overall_exact_rate |   overall_hit_rate |   docx_exact_rate |   docx_hit_rate |   manual_exact_rate |   manual_hit_rate |   manual_signal_hit_rate |   manual_action_hit_rate |
|-----------:|-------------:|-------------:|---------------:|---------------------:|-------------------:|------------------:|----------------:|--------------------:|------------------:|-------------------------:|-------------------------:|
|    20.0000 |      42.0000 |      34.0000 |         8.0000 |               0.4286 |             0.7024 |            0.4412 |          0.7206 |              0.3750 |            0.6250 |                   0.4444 |                   0.3333 |
|    23.0000 |      42.0000 |      34.0000 |         8.0000 |               0.5476 |             0.7738 |            0.4706 |          0.7353 |              0.8750 |            0.9375 |                   0.4444 |                   0.2222 |

## 2026-07-15 Key Case

|   lookback | expected_names   | target_names   | exact   | expected_buy_codes   | expected_sell_codes   | actual_buy_signal_codes   | actual_sell_signal_codes   | action_buy_codes   | action_sell_codes   | watch_ret_trend_signal                                                 |
|-----------:|:-----------------|:---------------|:--------|:---------------------|:----------------------|:--------------------------|:---------------------------|:-------------------|:--------------------|:-----------------------------------------------------------------------|
|         20 | 科创50|华宝油气        | 科创50|华宝油气      | True    | 162411.SZ            | 164824.SZ             | 162411.SZ                 | 164824.SZ                  | 162411.SZ          | 164824.SZ           | 科创50:13.07/-/-; 华宝油气:4.62/↗/0714_B; 印度:-0.69/↘/0714_S; 日经225:-6.53/↘/- |
|         23 | 科创50|华宝油气        | 科创50|华宝油气      | True    | 162411.SZ            | 164824.SZ             | 162411.SZ                 | 164824.SZ                  | 162411.SZ          | 164824.SZ           | 科创50:19.55/-/-; 华宝油气:2.91/↗/0714_B; 印度:1.26/↘/0714_S; 日经225:1.73/↘/-   |

## ret20 Numeric Fit

|   lookback | source                 |   count |    mae |   rmse |   median_abs_error |
|-----------:|:-----------------------|--------:|-------:|-------:|-------------------:|
|         20 | doc_rows               |     510 | 1.9008 | 2.5741 |             1.3789 |
|         20 | manual_ret20           |      46 | 2.0334 | 2.9710 |             1.1624 |
|         20 | manual_user_0715_ret20 |       5 | 3.7196 | 4.1918 |             2.2209 |
|         23 | doc_rows               |     510 | 1.0935 | 1.5217 |             0.8137 |
|         23 | manual_ret20           |      46 | 1.5964 | 2.0083 |             1.1600 |
|         23 | manual_user_0715_ret20 |       5 | 0.8075 | 1.1471 |             0.5138 |

## 2026-07-15 ret20 Rows

|   lookback | name   |   target_ret20_pct |   predicted_ret20_pct |   abs_error |
|-----------:|:-------|-------------------:|----------------------:|------------:|
|         20 | 中证A500 |             -0.100 |                -2.318 |       2.218 |
|         23 | 中证A500 |             -0.100 |                 0.797 |       0.897 |
|         20 | 华宝油气   |              2.400 |                 4.621 |       2.221 |
|         23 | 华宝油气   |              2.400 |                 2.914 |       0.514 |
|         20 | 印度     |              1.300 |                -0.695 |       1.995 |
|         23 | 印度     |              1.300 |                 1.260 |       0.040 |
|         20 | 日经225  |             -0.600 |                -6.533 |       5.933 |
|         23 | 日经225  |             -0.600 |                 1.733 |       2.333 |
|         20 | 科创50   |             19.300 |                13.069 |       6.231 |
|         23 | 科创50   |             19.300 |                19.553 |       0.253 |

## Backtest Snapshot

|   lookback |    nav |   control_nav |   annual_return |   control_annual_return |   current_drawdown |   max_drawdown |   sharpe |   trade_count |
|-----------:|-------:|--------------:|----------------:|------------------------:|-------------------:|---------------:|---------:|--------------:|
|    20.0000 | 1.4837 |        1.3293 |          7.4597 |                  5.3274 |           -12.8315 |       -39.4478 |   0.4712 |      780.0000 |
|    23.0000 | 1.2938 |        1.1592 |          4.8092 |                  2.7308 |           -23.1665 |       -31.9503 |   0.3552 |      752.0000 |

## Output Files

- summary: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/reports/lookback_20_vs_23_summary.csv`
- detail: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/reports/lookback_20_vs_23_detail.csv`
- ret20_detail: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/reports/lookback_20_vs_23_ret20_detail.csv`
