"""Technical indicators for ETF rotation signals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .universe import ETF

UP = "↗"
DOWN = "↘"
FLAT = "-"
STAR = "★"
WEAK = "●"


def ret_pct(close: pd.Series, window: int) -> pd.Series:
    """Return percentage return over ``window`` trading days."""
    return (close / close.shift(window) - 1) * 100


def moving_average(close: pd.Series, window: int) -> pd.Series:
    """Return a simple moving average."""
    return close.rolling(window, min_periods=window).mean()


def bias_pct(close: pd.Series, ma: pd.Series) -> pd.Series:
    """Return percentage deviation from a moving average."""
    return (close / ma - 1) * 100


def classify_trend(close: pd.Series, ma: pd.Series, slope_window: int) -> pd.Series:
    """Classify trend from close/MA relation and MA slope."""
    slope = ma - ma.shift(slope_window)
    trend = pd.Series(FLAT, index=close.index, dtype=object)
    trend[(close > ma) & (slope > 0)] = UP
    trend[(close < ma) & (slope < 0)] = DOWN
    return trend


def classify_market_signal(trend: object, ret20_pct: object, allow_unknown: bool = False) -> str:
    """Classify the broad long/short signal used by reports and scores."""
    if allow_unknown and (pd.isna(ret20_pct) or trend not in {UP, DOWN, FLAT}):
        return FLAT
    try:
        ret_value = float(ret20_pct)
    except (TypeError, ValueError):
        return FLAT
    if trend == UP and ret_value > 0:
        return STAR
    if trend == DOWN or ret_value <= 0:
        return WEAK
    return FLAT


def classify_convex(ma: pd.Series, slope_window: int) -> pd.Series:
    """Classify trend convexity by the change in MA slope."""
    slope = ma - ma.shift(slope_window)
    convex = pd.Series(FLAT, index=ma.index, dtype=object)
    valid = slope.notna() & slope.shift(1).notna()
    convex[valid & (slope > slope.shift(1))] = UP
    convex[valid & (slope <= slope.shift(1))] = DOWN
    return convex


def _compute_one_group(group: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """Compute indicators for one ETF code."""
    df = group.sort_values("date").copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    lookback = int(strategy.get("lookback_momentum", 20))
    bias_window = int(strategy.get("bias_ma", 20))
    trend_window = int(strategy.get("trend_ma", 20))
    long_window = int(strategy.get("long_ma", 60))
    trend_slope_window = int(strategy.get("trend_slope_window", 5))
    convex_slope_window = int(strategy.get("convex_slope_window", 5))

    df["ret20_pct"] = ret_pct(close, lookback)
    df["ma20"] = moving_average(close, bias_window)
    df["ma60"] = moving_average(close, long_window)
    trend_ma = moving_average(close, trend_window)
    df["bias_pct"] = bias_pct(close, df["ma20"])
    df["trend"] = classify_trend(close, trend_ma, trend_slope_window)
    df["market_signal"] = [
        classify_market_signal(trend, ret) for trend, ret in zip(df["trend"], df["ret20_pct"], strict=False)
    ]
    df["convex"] = classify_convex(df["ma20"], convex_slope_window)
    first_close = close.dropna().iloc[0] if close.notna().any() else np.nan
    df["nav_like"] = close / first_close if first_close and not np.isnan(first_close) else np.nan
    return df


def attach_premium_pb(features: pd.DataFrame, premium: pd.DataFrame | None, symbols: list[ETF]) -> pd.DataFrame:
    """Attach QDII premium/PB estimates, defaulting to 1.0 when unavailable."""
    df = features.copy()
    qdii_map = {item.code: item.qdii for item in symbols}
    asset_map = {item.code: item.asset for item in symbols}
    df["qdii"] = df["code"].map(qdii_map).fillna(False).astype(bool)
    df["asset"] = df["code"].map(asset_map).fillna("")
    df["premium_pb"] = 1.0
    df["pb_is_default"] = True

    if premium is not None and not premium.empty:
        premium_df = premium.copy()
        if "date" in premium_df.columns:
            premium_df["date"] = pd.to_datetime(premium_df["date"]).dt.normalize()
            premium_df = premium_df.sort_values(["code", "date"])
            merged = pd.merge_asof(
                df.sort_values(["date", "code"]),
                premium_df[["date", "code", "premium_pb"]].sort_values(["date", "code"]),
                on="date",
                by="code",
                direction="backward",
                suffixes=("", "_premium"),
            )
            df = merged.sort_values(["date", "code"]).reset_index(drop=True)
            if "premium_pb_premium" in df.columns:
                df["premium_pb"] = df["premium_pb_premium"].fillna(df["premium_pb"])
                df = df.drop(columns=["premium_pb_premium"])
        elif {"code", "premium_pb"}.issubset(premium_df.columns):
            latest = premium_df.drop_duplicates("code", keep="last")[["code", "premium_pb"]]
            df = df.drop(columns=["premium_pb"]).merge(latest, on="code", how="left")
            df["premium_pb"] = df["premium_pb"].fillna(1.0)
        df["pb_is_default"] = df["premium_pb"].eq(1.0)
    return df


def compute_indicators(
    prices: pd.DataFrame,
    strategy: dict,
    symbols: list[ETF],
    premium: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute all rolling indicators for a long-form price table."""
    required = {"date", "code", "name", "open", "high", "low", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price data missing columns: {sorted(missing)}")
    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    features = pd.concat(
        [_compute_one_group(group, strategy) for _, group in df.groupby("code", sort=False)],
        ignore_index=True,
    )
    features = attach_premium_pb(features, premium, symbols)
    if str(strategy.get("signals", {}).get("qdii_up_signal", "")).lower() == "neutral":
        mask = features["qdii"].fillna(False) & features["market_signal"].eq(STAR)
        features.loc[mask, "market_signal"] = FLAT
    return features
