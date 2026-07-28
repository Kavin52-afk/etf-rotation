from __future__ import annotations

import pandas as pd

from etf_rotation.indicators import FLAT, UP
from etf_rotation.position import determine_control_position


def _strategy() -> dict:
    return {
        "position_control": {
            "default_position": 0.5,
            "full_position": 1.0,
            "add_when_drawdown_below": -4.0,
            "reduce_when_drawdown_below": -12.0,
            "half_when_new_high": True,
        }
    }


def test_deep_drawdown_with_one_up_target_adds_to_full_position() -> None:
    target_features = pd.DataFrame({"trend": [FLAT, UP]})

    scale, label = determine_control_position(
        drawdown_pct=-23.0,
        target_features=target_features,
        previous_scale=0.5,
        is_new_high=False,
        strategy=_strategy(),
    )

    assert scale == 1.0
    assert label == "现在满仓"


def test_deep_drawdown_without_up_targets_stays_half_position() -> None:
    target_features = pd.DataFrame({"trend": [FLAT, FLAT]})

    scale, label = determine_control_position(
        drawdown_pct=-23.0,
        target_features=target_features,
        previous_scale=1.0,
        is_new_high=False,
        strategy=_strategy(),
    )

    assert scale == 0.5
    assert label == "现在半仓"
