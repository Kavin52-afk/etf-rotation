from __future__ import annotations

import pandas as pd

from etf_rotation.metrics import (
    execution_reliability_score,
    real_world_fidelity_score,
    strategy_stability_score,
)


def test_strategy_stability_score_rewards_unchanged_holdings() -> None:
    stable = strategy_stability_score([["A", "B"], ["A", "B"], ["A", "B"]], max_hold=2)
    unstable = strategy_stability_score([["A", "B"], ["C", "D"], ["A", "B"]], max_hold=2)

    assert stable == 100.0
    assert unstable < stable


def test_execution_reliability_penalizes_same_day_execution_and_mismatch() -> None:
    records = pd.DataFrame(
        [
            {
                "signal_date": "2026-06-26",
                "execution_date": "2026-06-26",
                "signal_target": "A|B",
                "executed_target": "A|C",
            }
        ]
    )

    assert execution_reliability_score(records) == 0.0


def test_real_world_fidelity_score_uses_required_guards() -> None:
    records = pd.DataFrame(
        [
            {"t_plus_one": True, "risk_priority": True, "hold_inertia": True},
            {"t_plus_one": False, "risk_priority": True, "hold_inertia": True},
        ]
    )

    assert real_world_fidelity_score(records) == 80.0
