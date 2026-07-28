from __future__ import annotations

import pandas as pd

from etf_rotation.execution_policy import apply_execution_policy
from etf_rotation.risk_overlay import evaluate_risk_state


def _strategy() -> dict:
    return {
        "score": {
            "overheat_bias_threshold": 12.0,
            "extreme_overheat_bias_threshold": 18.0,
            "qdii_premium_block": 8.0,
        },
        "rebalance": {
            "keep_if_rank_le": 4,
            "replace_only_if_new_score_better_by": 3.0,
        },
    }


def test_moderate_overheat_blocks_new_entry_but_allows_existing_hold() -> None:
    state = evaluate_risk_state(
        pd.Series(
            {
                "bias_pct": 13.0,
                "premium_pb": 1.0,
                "qdii": False,
                "market_signal": "",
                "trend": "",
            }
        ),
        _strategy(),
    )

    assert state.allow_new_entry is False
    assert state.allow_hold is True
    assert state.reason == "OVERHEAT"


def test_configured_overheat_take_profit_blocks_existing_hold() -> None:
    strategy = _strategy()
    strategy["signals"] = {
        "profit_take_on_overheat_for_existing": True,
        "profit_take_bias_threshold": 12.0,
        "profit_take_min_profit_pct": 0.0,
    }
    state = evaluate_risk_state(
        pd.Series(
            {
                "bias_pct": 13.0,
                "profit_since_last_signal": 5.0,
                "premium_pb": 1.0,
                "qdii": False,
                "market_signal": "",
                "trend": "",
            }
        ),
        strategy,
    )

    assert state.allow_new_entry is False
    assert state.allow_hold is False
    assert state.reason == "OVERHEAT|TAKE_PROFIT_OVERHEAT"


def test_extreme_overheat_blocks_existing_hold() -> None:
    state = evaluate_risk_state(
        pd.Series(
            {
                "bias_pct": 19.0,
                "premium_pb": 1.0,
                "qdii": False,
                "market_signal": "",
                "trend": "",
            }
        ),
        _strategy(),
    )

    assert state.allow_new_entry is False
    assert state.allow_hold is False
    assert state.reason == "OVERHEAT|EXTREME_OVERHEAT"


def test_risk_exit_can_be_replaced_without_score_margin() -> None:
    risk_table = pd.DataFrame(
        [
            {
                "code": "OLD",
                "score": 40.0,
                "momentum_rank": 1,
                "latest_signal": "-",
                "last_signal": "0101_B",
                "allow_new_entry": False,
                "allow_hold": False,
            },
            {
                "code": "KEEP",
                "score": 30.0,
                "momentum_rank": 2,
                "latest_signal": "-",
                "last_signal": "0101_B",
                "allow_new_entry": True,
                "allow_hold": True,
            },
            {
                "code": "NEW",
                "score": 20.0,
                "momentum_rank": 3,
                "latest_signal": "-",
                "last_signal": "0101_B",
                "allow_new_entry": True,
                "allow_hold": True,
            },
        ]
    )

    decision = apply_execution_policy(risk_table, ["OLD", "KEEP"], _strategy(), max_hold=2)

    assert decision.target_holdings == ["KEEP", "NEW"]
    assert decision.added_positions == ["NEW"]
    assert decision.removed_positions == ["OLD"]
