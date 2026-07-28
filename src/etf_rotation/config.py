"""Project configuration loading and path management."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .utils import ensure_dir


def find_project_root(start: Path | None = None) -> Path:
    """Find the project root by walking upward to ``pyproject.toml``."""
    env_root = os.getenv("ETF_ROTATION_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    current = (start or Path(__file__)).resolve()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "configs").exists():
            return parent
    return Path.cwd().resolve()


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return an empty dict for empty files."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved project paths and YAML configuration bundles."""

    project_root: Path
    universe: dict[str, Any]
    strategy: dict[str, Any]
    data: dict[str, Any]

    @property
    def reports_dir(self) -> Path:
        """Return the reports directory."""
        return self.project_root / self.data.get("reports_dir", "data/reports")

    @property
    def labels_dir(self) -> Path:
        """Return the labels directory."""
        return self.project_root / self.data.get("labels_dir", "data/labels")

    @property
    def raw_dir(self) -> Path:
        """Return the raw data directory."""
        return self.project_root / self.data.get("raw_dir", "data/raw")

    @property
    def cache_dir(self) -> Path:
        """Return the cache directory."""
        return self.project_root / "data" / "cache"

    @property
    def price_cache(self) -> Path:
        """Return the real-data price cache path."""
        return self.project_root / self.data.get("price_cache", "data/cache/prices.parquet")

    @property
    def sample_price_cache(self) -> Path:
        """Return the synthetic sample-data price cache path."""
        return self.project_root / self.data.get("sample_price_cache", "data/cache/sample_prices.parquet")

    @property
    def premium_cache(self) -> Path:
        """Return the premium/PB cache path."""
        return self.project_root / self.data.get("premium_cache", "data/cache/premium.csv")


def load_project_config(project_root: Path | None = None) -> ProjectConfig:
    """Load all YAML configuration files under ``configs``."""
    root = (project_root or find_project_root()).resolve()
    cfg = ProjectConfig(
        project_root=root,
        universe=load_yaml(root / "configs" / "universe.yaml"),
        strategy=load_yaml(root / "configs" / "strategy.yaml"),
        data=load_yaml(root / "configs" / "data.yaml"),
    )
    ensure_project_dirs(cfg)
    return cfg


def ensure_project_dirs(cfg: ProjectConfig) -> None:
    """Create all runtime output directories declared by the project."""
    for path in [cfg.reports_dir, cfg.labels_dir, cfg.raw_dir, cfg.cache_dir, cfg.project_root / "data" / "processed"]:
        ensure_dir(path)
