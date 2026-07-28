from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.indicators import DOWN, FLAT, STAR, UP, compute_indicators
from etf_rotation.universe import ETF


def _prices(close: np.ndarray) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(close), freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "code": "TEST.SH",
            "name": "测试",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000,
            "amount": close * 1000,
        }
    )


def _strategy() -> dict:
    return {
        "lookback_momentum": 20,
        "bias_ma": 20,
        "trend_ma": 20,
        "long_ma": 60,
        "trend_slope_window": 5,
        "convex_slope_window": 5,
    }


def test_uptrend_ret20_and_trend() -> None:
    close = np.linspace(1.0, 2.0, 90)
    features = compute_indicators(_prices(close), _strategy(), [ETF("测试", "TEST.SH")])
    last = features.iloc[-1]
    assert last["ret20_pct"] > 0
    assert last["trend"] == UP


def test_downtrend() -> None:
    close = np.linspace(2.0, 1.0, 90)
    features = compute_indicators(_prices(close), _strategy(), [ETF("测试", "TEST.SH")])
    assert features.iloc[-1]["trend"] == DOWN


def test_bias_pct_calculation() -> None:
    close = np.linspace(1.0, 2.0, 90)
    features = compute_indicators(_prices(close), _strategy(), [ETF("测试", "TEST.SH")])
    last = features.iloc[-1]
    expected = (last["close"] / features["close"].rolling(20).mean().iloc[-1] - 1) * 100
    assert abs(last["bias_pct"] - expected) < 1e-10


def test_qdii_up_signal_can_be_neutralized() -> None:
    close = np.linspace(1.0, 2.0, 90)
    strategy = _strategy() | {"signals": {"qdii_up_signal": "neutral"}}

    features = compute_indicators(_prices(close), strategy, [ETF("测试", "TEST.SH", qdii=True)])

    assert features.iloc[-1]["trend"] == UP
    assert features.iloc[-1]["market_signal"] == FLAT


def test_non_qdii_up_signal_remains_star() -> None:
    close = np.linspace(1.0, 2.0, 90)
    strategy = _strategy() | {"signals": {"qdii_up_signal": "neutral"}}

    features = compute_indicators(_prices(close), strategy, [ETF("测试", "TEST.SH", qdii=False)])

    assert features.iloc[-1]["market_signal"] == STAR
