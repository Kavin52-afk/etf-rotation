from __future__ import annotations

import pandas as pd

from etf_rotation.indicators import DOWN, FLAT, STAR, UP, WEAK
from etf_rotation.signals import add_signals


def test_buy_signal_on_trend_flip_to_up() -> None:
    dates = pd.date_range("2024-06-24", periods=3, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "A.SH",
            "name": "A",
            "trend": [FLAT, UP, UP],
            "ret20_pct": [0.0, 3.0, 4.0],
            "close": [1.0, 1.1, 1.2],
            "ma20": [1.0, 1.0, 1.1],
        }
    )
    result = add_signals(features)
    assert result.loc[1, "latest_signal"].endswith("_B")
    assert result.loc[1, "latest_signal"] == f"{dates[1].strftime('%m%d')}_B"


def test_sell_signal_on_trend_flip_to_down() -> None:
    dates = pd.date_range("2024-06-24", periods=3, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "A.SH",
            "name": "A",
            "trend": [UP, DOWN, DOWN],
            "ret20_pct": [2.0, -1.0, -2.0],
            "close": [1.2, 0.9, 0.8],
            "ma20": [1.1, 1.0, 0.95],
        }
    )
    result = add_signals(features)
    assert result.loc[1, "latest_signal"].endswith("_S")
    assert result.loc[1, "latest_signal"] == f"{dates[1].strftime('%m%d')}_S"


def test_repeated_same_side_signal_is_suppressed() -> None:
    dates = pd.date_range("2024-06-24", periods=4, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "A.SH",
            "name": "A",
            "trend": [UP, DOWN, FLAT, DOWN],
            "ret20_pct": [2.0, -1.0, -2.0, -3.0],
            "close": [1.2, 0.9, 0.85, 0.8],
            "ma20": [1.1, 1.0, 0.95, 0.9],
        }
    )

    result = add_signals(features)

    assert result.loc[1, "latest_signal"].endswith("_S")
    assert result.loc[3, "latest_signal"] == FLAT
    assert result.loc[3, "last_signal"] == result.loc[1, "latest_signal"]


def test_last_signal_keeps_previous_when_latest_signal_occurs() -> None:
    dates = pd.date_range("2024-06-24", periods=4, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "A.SH",
            "name": "A",
            "trend": [FLAT, UP, UP, DOWN],
            "ret20_pct": [0.0, 3.0, 4.0, -1.0],
            "close": [1.0, 1.1, 1.2, 1.0],
            "ma20": [1.0, 1.0, 1.1, 1.1],
        }
    )

    result = add_signals(features)

    assert result.loc[1, "latest_signal"].endswith("_B")
    assert result.loc[3, "latest_signal"].endswith("_S")
    assert result.loc[3, "last_signal"] == result.loc[1, "latest_signal"]


def test_buy_signal_confirmation_and_t_plus_one_profit_price() -> None:
    dates = pd.date_range("2024-06-24", periods=5, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "A.SH",
            "name": "A",
            "trend": [FLAT, UP, UP, UP, UP],
            "ret20_pct": [0.0, 3.0, 4.0, 5.0, 6.0],
            "close": [1.0, 1.1, 1.2, 1.5, 1.8],
            "ma20": [1.0, 1.0, 1.1, 1.2, 1.3],
        }
    )

    result = add_signals(
        features,
        {"signals": {"buy_confirmation_days": 1, "profit_execution_delay_days": 1}},
    )

    assert result.loc[1, "latest_signal"] == FLAT
    assert result.loc[2, "latest_signal"] == f"{dates[2].strftime('%m%d')}_B"
    assert round(float(result.loc[4, "profit_since_last_signal"]), 6) == 20.0


def test_active_buy_can_sell_when_market_signal_turns_weak() -> None:
    dates = pd.date_range("2026-07-13", periods=4, freq="B")
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "162411.SZ",
            "name": "华宝油气",
            "trend": [FLAT, UP, UP, UP],
            "market_signal": [FLAT, STAR, WEAK, WEAK],
            "ret20_pct": [0.0, 2.0, -0.2, -0.5],
            "close": [0.86, 0.883, 0.88, 0.875],
            "ma20": [0.84, 0.82, 0.827, 0.83],
        }
    )

    result = add_signals(features, {"signals": {"sell_active_buy_on_market_weak": True}})

    assert result.loc[1, "latest_signal"] == f"{dates[1].strftime('%m%d')}_B"
    assert result.loc[2, "latest_signal"] == f"{dates[2].strftime('%m%d')}_S"


def test_reentry_buy_after_sell_requires_convex_recovery() -> None:
    dates = pd.to_datetime(["2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"])
    features = pd.DataFrame(
        {
            "date": dates,
            "code": "162411.SZ",
            "name": "华宝油气",
            "trend": [UP, UP, UP, UP],
            "market_signal": [STAR, WEAK, STAR, STAR],
            "convex": [UP, UP, DOWN, UP],
            "ret20_pct": [4.0, -0.2, 0.2, 3.9],
            "close": [0.894, 0.88, 0.863, 0.877],
            "ma20": [0.825, 0.827, 0.830, 0.833],
        }
    )

    result = add_signals(
        features,
        {
            "signals": {
                "sell_active_buy_on_market_weak": True,
                "buy_reentry_on_market_recovery_after_sell": True,
                "buy_reentry_requires_convex_up": True,
            }
        },
    )

    assert result.loc[0, "latest_signal"] == "0714_B"
    assert result.loc[1, "latest_signal"] == "0715_S"
    assert result.loc[2, "latest_signal"] == FLAT
    assert result.loc[3, "latest_signal"] == "0717_B"
    assert result.loc[3, "last_signal"] == "0715_S"
