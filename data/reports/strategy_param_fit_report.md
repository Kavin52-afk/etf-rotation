# Strategy Parameter Fit Report

Offline supervised fit against parsed DOCX labels plus scoreable manual object labels.

## Baseline

- objective: 884.0808
- doc_exact_rate: 61.76%
- doc_hit_rate: 80.88%
- manual_target_rate: 85.71%
- manual_signal_rate: 28.57%
- avg_turnover: 0.20

## Best

- objective: 884.0808
- doc_exact_rate: 61.76%
- doc_hit_rate: 80.88%
- manual_target_rate: 85.71%
- manual_signal_rate: 28.57%
- avg_turnover: 0.20

Best parameters:

```yaml
lookback_momentum: 25
signals.buy_confirmation_days: 0
signals.sell_confirmation_days: 0
score.holding_bonus: 4.0
score.qdii_premium_block: 8.0
score.overheat_bias_threshold: 12.0
rebalance.keep_if_rank_le: 4
rebalance.replace_only_if_new_score_better_by: 3.0
```

## Manual Labels Not Scored

- none

## Output Files

- candidates: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/reports/strategy_param_fit_candidates.csv`
- best_detail: `/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild/data/reports/strategy_param_fit_best_detail.csv`
