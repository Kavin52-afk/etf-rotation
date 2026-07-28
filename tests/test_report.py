from __future__ import annotations

import pandas as pd

from etf_rotation.config import ProjectConfig
from etf_rotation.metrics import PerformanceSummary
from etf_rotation.report import (
    build_market_index_ranking,
    is_stale_report_context,
    load_yesterday_holding_override,
    relabel_current_signals_for_report,
    render_daily_markdown,
    resolve_report_dates,
    sort_report_ranking,
)


def test_resolve_report_dates_uses_data_through_yesterday() -> None:
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-06-29", "2026-06-30", "2026-07-01"])})

    display_date, signal_date = resolve_report_dates(prices, "2026-07-01")

    assert display_date == pd.Timestamp("2026-07-01")
    assert signal_date == pd.Timestamp("2026-06-30")


def test_load_yesterday_holding_override(tmp_path) -> None:
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "holding_overrides.csv").write_text(
        "signal_date,yesterday_holdings\n2026-06-30,588000.SH|513520.SH\n",
        encoding="utf-8",
    )

    class Config:
        project_root = tmp_path

    assert load_yesterday_holding_override(Config(), pd.Timestamp("2026-06-30")) == [
        "588000.SH",
        "513520.SH",
    ]


def test_sort_report_ranking_uses_momentum_order() -> None:
    ranking = pd.DataFrame(
        {
            "code": ["B", "A", "C"],
            "ret20_pct": [2.0, 5.0, 5.0],
            "score": [100.0, 1.0, 2.0],
        }
    )

    ordered = sort_report_ranking(ranking)

    assert ordered["code"].tolist() == ["A", "C", "B"]


def test_relabel_current_signals_for_report_date() -> None:
    ranking = pd.DataFrame(
        {
            "latest_signal": ["0702_B", "0701_S", "-"],
            "last_signal": ["0701_S", "0617_B", "-"],
        }
    )

    rendered = relabel_current_signals_for_report(
        ranking,
        signal_date=pd.Timestamp("2026-07-02"),
        report_date=pd.Timestamp("2026-07-03"),
    )

    assert rendered["latest_signal"].tolist() == ["0703_B", "0701_S", "-"]
    assert rendered["last_signal"].tolist() == ["0702_S", "0618_B", "-"]


def test_relabel_current_signals_keeps_source_date_when_report_context_is_stale() -> None:
    ranking = pd.DataFrame({"latest_signal": ["0702_B", "0701_S", "-"]})

    rendered = relabel_current_signals_for_report(
        ranking,
        signal_date=pd.Timestamp("2026-07-02"),
        report_date=pd.Timestamp("2026-07-08"),
    )

    assert rendered["latest_signal"].tolist() == ["0702_B", "0701_S", "-"]
    assert is_stale_report_context(pd.Timestamp("2026-07-02"), pd.Timestamp("2026-07-08"))


def test_build_market_index_ranking_uses_latest_available_snapshot(tmp_path) -> None:
    cfg = ProjectConfig(
        project_root=tmp_path,
        universe={
            "market_index": {
                "symbols": [
                    {
                        "name": "科创50",
                        "code": "000688.SH",
                        "asset": "market_index",
                        "kind": "index",
                    }
                ]
            }
        },
        strategy={
            "lookback_momentum": 1,
            "bias_ma": 1,
            "trend_ma": 1,
            "long_ma": 1,
            "trend_slope_window": 1,
            "convex_slope_window": 1,
        },
        data={},
    )
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-08", "2026-07-09"]),
            "code": ["000688.SH", "000688.SH"],
            "name": ["科创50", "科创50"],
            "open": [100.0, 101.0],
            "high": [100.0, 101.0],
            "low": [100.0, 101.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 1.0],
            "amount": [100.0, 101.0],
        }
    )

    ranking = build_market_index_ranking(prices, cfg, pd.Timestamp("2026-07-10"))

    assert ranking["date"].dt.normalize().tolist() == [pd.Timestamp("2026-07-09")]
    assert ranking["name"].tolist() == ["科创50"]


def test_render_daily_markdown_does_not_use_etf_rows_as_market_fallback() -> None:
    ranking = pd.DataFrame(
        {
            "name": ["科创50"],
            "code": ["588000.SH"],
            "asset": ["china_equity"],
            "status_mark": ["√√√"],
            "premium_pb": [1.0],
            "ret20_pct": [10.0],
            "bias_pct": [1.0],
            "trend": ["↗"],
            "market_signal": ["★"],
            "convex": ["↗"],
            "nav_like": [1.2],
            "last_signal": ["0618_B"],
            "profit_since_last_signal": [5.0],
            "latest_signal": ["-"],
        }
    )
    summary = PerformanceSummary(
        nav=1.0,
        control_nav=1.0,
        annual_return=0.0,
        control_annual_return=0.0,
        max_drawdown=0.0,
        control_max_drawdown=0.0,
        current_drawdown=0.0,
        control_current_drawdown=0.0,
        sharpe=0.0,
        control_sharpe=0.0,
        trade_count=0,
        observation_days=1,
        yearly_returns={},
        control_yearly_returns={},
    )

    markdown = render_daily_markdown(
        report_date=pd.Timestamp("2026-07-13"),
        signal_date=pd.Timestamp("2026-07-10"),
        ranking=ranking,
        market_index_ranking=pd.DataFrame(),
        sector_ranking=pd.DataFrame(),
        yesterday_display=[],
        today_display=[],
        summary=summary,
        sample=False,
        annual_days=244,
        position_label="现在半仓",
        realworld_context={"mode": "direct"},
    )

    market_block = markdown.split("大类 ETF 截至昨日强弱排序：", maxsplit=1)[0]
    assert "A股大盘数据暂不可用。" in market_block
    assert "科创50_:" not in market_block
