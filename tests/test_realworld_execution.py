from __future__ import annotations

import pandas as pd

from etf_rotation.realworld_execution import build_execution_plan, freeze_signal
from etf_rotation.stability_controller import apply_signal_debounce, enforce_churn_control


def _features(value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-26")],
            "code": ["A"],
            "ret20_pct": [value],
            "score": [value],
        }
    )


def test_freeze_signal_reuses_existing_state_and_rejects_intraday_change(tmp_path) -> None:
    first = freeze_signal(pd.Timestamp("2026-06-26"), ["A"], _features(1.0), tmp_path)
    second = freeze_signal(pd.Timestamp("2026-06-26"), ["B"], _features(2.0), tmp_path)

    assert first.is_new is True
    assert second.is_new is False
    assert second.hash_changed is True
    assert second.state.frozen_signal == ["A"]


def test_execution_plan_uses_next_trading_day_only() -> None:
    state = freeze_signal(pd.Timestamp("2026-06-26"), ["B"], _features(1.0), persist=False).state
    plan = build_execution_plan(
        state,
        ["A"],
        [pd.Timestamp("2026-06-26"), pd.Timestamp("2026-06-29")],
    )

    assert plan.execution_date == "2026-06-29"
    assert plan.allowed is True
    assert {item["action"] for item in plan.actions} == {"SELL", "BUY"}


def test_signal_debounce_ignores_fast_change() -> None:
    target, ignored = apply_signal_debounce(
        pd.Timestamp("2026-06-27"),
        ["B"],
        {pd.Timestamp("2026-06-26"): ["A"]},
    )

    assert target == ["A"]
    assert ignored


def test_churn_control_caps_multi_change_signal() -> None:
    target, ignored = enforce_churn_control(["A", "B"], ["C", "D"], max_changes=1)

    assert len(set(target) - {"A", "B"}) == 1
    assert ignored
