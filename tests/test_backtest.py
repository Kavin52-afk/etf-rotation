from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_rotation.backtest import run_backtest
from etf_rotation.config import load_project_config
from etf_rotation.data_provider import generate_sample_prices
from etf_rotation.universe import load_universe


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sample_prices() -> pd.DataFrame:
    cfg = load_project_config(PROJECT_ROOT)
    symbols = load_universe(cfg.universe, pools=["broad_etf"])
    return generate_sample_prices(symbols, start="2021-01-01", end="2021-09-30", seed=7)


def test_sample_backtest_outputs_nav_without_nan() -> None:
    cfg = load_project_config(PROJECT_ROOT)
    result = run_backtest(_sample_prices(), cfg, start="2021-03-01", end="2021-09-30", write_reports=False)
    assert not result.nav.empty
    assert result.nav["nav"].notna().all()
    assert result.nav["control_nav"].notna().all()


def test_position_weights_do_not_exceed_scale() -> None:
    cfg = load_project_config(PROJECT_ROOT)
    result = run_backtest(_sample_prices(), cfg, start="2021-03-01", end="2021-09-30", write_reports=False)
    if result.positions.empty:
        raise AssertionError("Expected at least one position row")
    grouped = result.positions.groupby("date").agg(weight=("weight", "sum"), scale=("position_scale", "first"))
    assert (grouped["weight"] <= grouped["scale"] + 1e-12).all()


def test_rebalance_uses_next_open_price_not_signal_day_close() -> None:
    cfg = load_project_config(PROJECT_ROOT)
    prices = _sample_prices()
    result = run_backtest(prices, cfg, start="2021-03-01", end="2021-09-30", write_reports=False)
    trades = result.trades.dropna(subset=["signal_date"])
    assert not trades.empty
    assert (pd.to_datetime(trades["date"]) > pd.to_datetime(trades["signal_date"])).all()
    for trade in trades.itertuples(index=False):
        open_price = prices.loc[
            prices["date"].eq(pd.Timestamp(trade.date)) & prices["code"].eq(trade.code),
            "open",
        ].iloc[0]
        assert abs(float(trade.price) - float(open_price)) < 1e-12
