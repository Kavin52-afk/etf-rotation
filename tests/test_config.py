from __future__ import annotations

from pathlib import Path

from etf_rotation.config import load_project_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_momentum_lookback_matches_source_label_alignment() -> None:
    cfg = load_project_config(PROJECT_ROOT)

    assert cfg.strategy["lookback_momentum"] == 23
