"""ETF universe loading and symbol normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


NAME_ALIASES = {
    "日经 225": "日经225",
    "科创 50": "科创50",
    "创业板 50": "创业板50",
    "中证 A500": "中证A500",
    "中证A500": "中证A500",
    "中证 2000": "中证2000",
}


@dataclass(frozen=True)
class ETF:
    """Single ETF definition from ``configs/universe.yaml``."""

    name: str
    code: str
    asset: str = ""
    qdii: bool = False
    pool: str = ""
    kind: str = "etf"
    secid: str = ""


def normalize_name(name: object) -> str:
    """Normalize Chinese ETF display names parsed from documents."""
    text = str(name or "").strip()
    text = text.replace("\u3000", " ").replace("↑", "").replace("↓", "")
    text = re.sub(r"\s+", " ", text)
    text = NAME_ALIASES.get(text, text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[0-9\u4e00-\u9fff])", "", text)
    return NAME_ALIASES.get(text, text)


def code_to_ak_symbol(code: str) -> str:
    """Convert a suffixed exchange code such as ``513520.SH`` to ``513520``."""
    return str(code).split(".")[0]


def load_pool(universe_config: dict, pool: str) -> list[ETF]:
    """Load one ETF pool from universe config."""
    pool_cfg = universe_config.get(pool, {})
    items = []
    for item in pool_cfg.get("symbols", []):
        items.append(
            ETF(
                name=normalize_name(item.get("name")),
                code=str(item.get("code")),
                asset=str(item.get("asset", "")),
                qdii=bool(item.get("qdii", False)),
                pool=pool,
                kind=str(item.get("kind", "etf")),
                secid=str(item.get("secid", "")),
            )
        )
    return items


def load_universe(universe_config: dict, pools: Iterable[str] | None = None) -> list[ETF]:
    """Load all requested ETF pools from universe config."""
    selected_pools = list(pools or universe_config.keys())
    symbols: list[ETF] = []
    for pool in selected_pools:
        if pool in universe_config:
            symbols.extend(load_pool(universe_config, pool))
    return symbols


def etf_maps(symbols: Iterable[ETF]) -> tuple[dict[str, ETF], dict[str, ETF]]:
    """Return code and normalized-name lookup maps for ETF metadata."""
    symbol_list = list(symbols)
    return {item.code: item for item in symbol_list}, {normalize_name(item.name): item for item in symbol_list}


def names_for_codes(codes: Iterable[str], code_map: dict[str, ETF]) -> list[str]:
    """Convert ETF codes to display names."""
    return [code_map[code].name if code in code_map else str(code) for code in codes]


def codes_for_names(names: Iterable[str], name_map: dict[str, ETF]) -> list[str]:
    """Convert display names to ETF codes when possible."""
    codes: list[str] = []
    for name in names:
        normalized = normalize_name(name)
        if normalized in name_map:
            codes.append(name_map[normalized].code)
    return codes
