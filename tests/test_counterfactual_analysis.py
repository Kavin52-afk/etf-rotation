from __future__ import annotations

import pandas as pd

from etf_rotation.counterfactual_analysis import _holding_similarity, _stable_noise


def test_holding_similarity_uses_jaccard_overlap() -> None:
    assert _holding_similarity(["A", "B"], ["A", "B"]) == 1.0
    assert _holding_similarity(["A", "B"], ["B", "C"]) == 1 / 3
    assert _holding_similarity([], []) == 1.0


def test_stable_noise_is_deterministic_and_bounded() -> None:
    date_value = pd.Timestamp("2026-06-28")
    first = _stable_noise(date_value, "513100.SH")
    second = _stable_noise(date_value, "513100.SH")

    assert first == second
    assert -0.05 <= first <= 0.05
