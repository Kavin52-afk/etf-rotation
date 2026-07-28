from __future__ import annotations

from etf_rotation.config import load_project_config
from etf_rotation.source_attribution import extract_source_features, score_templates


def test_extract_source_features_detects_required_structure() -> None:
    cfg = load_project_config()
    features = extract_source_features(cfg)
    present = {item.key for item in features if item.present}

    assert "lookback_near_20" in present
    assert "top_k_2" in present
    assert "overheat_threshold_filter" in present
    assert "holding_inertia" in present
    assert "status_mark_encoding" in present
    assert "bs_signal_system" in present


def test_template_similarity_prefers_blog_or_hybrid_style() -> None:
    cfg = load_project_config()
    features = extract_source_features(cfg)
    scores = {item.template: item.similarity for item in score_templates(features)}

    assert scores["C"] > scores["B"] > scores["A"]
