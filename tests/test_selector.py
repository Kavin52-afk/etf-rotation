from __future__ import annotations

import pandas as pd

from etf_rotation.indicators import FLAT, STAR, UP
from etf_rotation.selector import score_row, select_holdings


def _strategy() -> dict:
    return {
        "max_hold_broad": 2,
        "score": {
            "momentum_weight": 1.0,
            "trend_up_bonus": 5.0,
            "trend_flat_bonus": 0.0,
            "trend_down_penalty": -20.0,
            "star_bonus": 3.0,
            "convex_up_bonus": 2.0,
            "holding_bonus": 4.0,
            "buy_signal_bonus": 4.0,
            "sell_signal_penalty": -999.0,
            "overheat_bias_threshold": 12.0,
            "overheat_penalty": -6.0,
            "extreme_overheat_bias_threshold": 18.0,
            "extreme_overheat_penalty": -12.0,
            "qdii_premium_warn": 5.0,
            "qdii_premium_block": 8.0,
            "qdii_premium_penalty": -10.0,
        },
        "rebalance": {
            "keep_if_rank_le": 4,
            "replace_only_if_new_score_better_by": 3.0,
            "allow_flat_trend_for_existing": True,
            "allow_flat_trend_for_new": False,
            "require_positive_ret20_for_new": True,
        },
    }


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2024-06-28"),
            "code": ["A", "B", "C", "D", "E"],
            "name": ["A", "B", "C", "D", "E"],
            "ret20_pct": [10.0, 9.0, 8.0, 7.0, 6.0],
            "bias_pct": [1.0, 1.0, 1.0, 1.0, 1.0],
            "trend": [UP, UP, UP, UP, UP],
            "market_signal": [STAR, STAR, STAR, STAR, STAR],
            "convex": [UP, UP, UP, UP, UP],
            "latest_signal": [FLAT, FLAT, FLAT, FLAT, FLAT],
            "last_signal": ["0101_B"] * 5,
            "premium_pb": [1.0] * 5,
            "qdii": [False] * 5,
        }
    )


def test_selects_top2() -> None:
    result = select_holdings(_features(), [], {}, _strategy(), max_hold=2)
    assert result.target_holdings == ["A", "B"]


def test_existing_rank3_retained_without_sell_signal() -> None:
    result = select_holdings(_features(), ["C"], {}, _strategy(), max_hold=2)
    assert "C" in result.target_holdings


def test_existing_sell_signal_removed() -> None:
    features = _features()
    features.loc[features["code"].eq("C"), "latest_signal"] = "0628_S"
    result = select_holdings(features, ["C"], {}, _strategy(), max_hold=2)
    assert "C" not in result.target_holdings


def test_qdii_pb_block_prevents_new_position() -> None:
    features = _features()
    features.loc[0, "qdii"] = True
    features.loc[0, "premium_pb"] = 1.09
    result = select_holdings(features, [], {}, _strategy(), max_hold=2)
    assert "A" not in result.target_holdings


def test_qdii_premium_penalty_does_not_downgrade_existing_holding() -> None:
    features = _features()
    row = features.iloc[0].copy()
    row["qdii"] = True
    row["premium_pb"] = 1.09

    new_score = score_row(row, _strategy(), yesterday_holdings=set())
    existing_score = score_row(row, _strategy(), yesterday_holdings={"A"})

    assert existing_score > new_score


def test_configured_overheat_take_profit_exits_existing_and_does_not_readd_same_day() -> None:
    strategy = _strategy()
    strategy["signals"] = {
        "profit_take_on_overheat_for_existing": True,
        "profit_take_bias_threshold": 12.0,
        "profit_take_min_profit_pct": 0.0,
    }
    features = _features()
    features["profit_since_last_signal"] = [5.0] * len(features)
    features.loc[features["code"].eq("A"), "bias_pct"] = 13.0

    result = select_holdings(features, ["A", "B"], {}, strategy, max_hold=2)

    assert "A" not in result.target_holdings
    assert result.sell_list == ["A"]
