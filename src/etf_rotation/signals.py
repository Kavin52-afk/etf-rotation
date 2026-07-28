"""Buy/sell signal generation for ETF indicator tables."""

from __future__ import annotations

import pandas as pd

from .indicators import DOWN, FLAT, STAR, UP, WEAK


def signal_label(date_value: pd.Timestamp, suffix: str) -> str:
    """Return a signal label such as ``0626_B`` or ``0626_S``."""
    return f"{pd.Timestamp(date_value).strftime('%m%d')}_{suffix}"


def buy_signal(previous_trend: object, trend: object, ret20_pct: object, date_value: pd.Timestamp) -> str:
    """Return a buy signal when trend flips into uptrend with positive momentum."""
    try:
        ret_value = float(ret20_pct)
    except (TypeError, ValueError):
        return FLAT
    if previous_trend != UP and trend == UP and ret_value > 0:
        return signal_label(date_value, "B")
    return FLAT


def sell_signal(
    previous_trend: object,
    trend: object,
    close: object,
    ma20: object,
    ret20_pct: object,
    date_value: pd.Timestamp,
) -> str:
    """Return a sell signal on downtrend flip or weak close below MA20."""
    try:
        close_value = float(close)
        ma_value = float(ma20)
        ret_value = float(ret20_pct)
    except (TypeError, ValueError):
        close_value = ma_value = ret_value = float("nan")
    trend_flip = previous_trend != DOWN and trend == DOWN
    weak_break = pd.notna(close_value) and pd.notna(ma_value) and close_value < ma_value and ret_value < 0
    if trend_flip or weak_break:
        return signal_label(date_value, "S")
    return FLAT


def _as_float(value: object) -> float | None:
    """Return a parsed float, or None when the value is unavailable."""
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _reentry_buy_signal(
    row: object,
    active_signal: str,
    active_signal_idx: int | None,
    idx: int,
    signal_cfg: dict,
) -> str:
    """Return a buy signal when an ETF recovers after an active sell state."""
    if not bool(signal_cfg.get("buy_reentry_on_market_recovery_after_sell", False)):
        return FLAT
    if not active_signal.endswith("_S") or active_signal_idx is None or idx <= active_signal_idx:
        return FLAT

    ret_value = _as_float(getattr(row, "ret20_pct", None))
    if ret_value is None or ret_value <= 0:
        return FLAT
    if getattr(row, "trend", FLAT) != UP:
        return FLAT
    if getattr(row, "market_signal", FLAT) != STAR:
        return FLAT
    if bool(signal_cfg.get("buy_reentry_requires_convex_up", False)) and getattr(row, "convex", FLAT) != UP:
        return FLAT
    return signal_label(getattr(row, "date"), "B")


def _signals_one_group(group: pd.DataFrame, strategy: dict | None = None) -> pd.DataFrame:
    """Generate current and last signal fields for one ETF."""
    df = group.sort_values("date").copy()
    signal_cfg = (strategy or {}).get("signals", {})
    buy_confirmation_days = int(signal_cfg.get("buy_confirmation_days", 0))
    sell_confirmation_days = int(signal_cfg.get("sell_confirmation_days", 0))
    profit_execution_delay_days = int(signal_cfg.get("profit_execution_delay_days", 0))
    sell_active_buy_on_market_weak = bool(signal_cfg.get("sell_active_buy_on_market_weak", False))
    previous_trend = df["trend"].shift(1).fillna(FLAT)
    raw_signals: list[str] = []
    latest_signal: list[str] = [FLAT] * len(df)
    last_signal: list[str] = []
    profit_values: list[float | str] = []

    for row, prev in zip(df.itertuples(index=False), previous_trend, strict=False):
        b_sig = buy_signal(prev, row.trend, row.ret20_pct, row.date)
        s_sig = sell_signal(prev, row.trend, row.close, row.ma20, row.ret20_pct, row.date)
        raw_signals.append(b_sig if b_sig != FLAT else s_sig)

    pending_buy_idx: int | None = None
    pending_sell_idx: int | None = None
    for idx, row in enumerate(df.itertuples(index=False)):
        raw = raw_signals[idx]
        current = FLAT
        if raw.endswith("_B"):
            pending_buy_idx = idx
            pending_sell_idx = None
            if buy_confirmation_days <= 0:
                current = raw
                pending_buy_idx = None
        elif raw.endswith("_S"):
            pending_sell_idx = idx
            pending_buy_idx = None
            if sell_confirmation_days <= 0:
                current = raw
                pending_sell_idx = None

        if current == FLAT and pending_buy_idx is not None and idx - pending_buy_idx >= buy_confirmation_days:
            if row.trend == "↗" and float(row.ret20_pct) > 0:
                current = signal_label(row.date, "B")
            pending_buy_idx = None
        if current == FLAT and pending_sell_idx is not None and idx - pending_sell_idx >= sell_confirmation_days:
            if row.trend == "↘" or float(row.close) < float(row.ma20):
                current = signal_label(row.date, "S")
            pending_sell_idx = None

        latest_signal[idx] = current

    active_signal = FLAT
    active_signal_idx: int | None = None
    close_values = pd.to_numeric(df["close"], errors="coerce").tolist()
    market_values = df["market_signal"].tolist() if "market_signal" in df.columns else [FLAT] * len(df)
    date_values = pd.to_datetime(df["date"]).tolist()
    for idx, current in enumerate(latest_signal):
        if (
            current == FLAT
            and sell_active_buy_on_market_weak
            and active_signal.endswith("_B")
            and active_signal_idx is not None
            and idx > active_signal_idx
            and market_values[idx] == WEAK
        ):
            current = signal_label(pd.Timestamp(date_values[idx]), "S")
            latest_signal[idx] = current

        if current == FLAT:
            row = df.iloc[idx]
            current = _reentry_buy_signal(row, active_signal, active_signal_idx, idx, signal_cfg)
            latest_signal[idx] = current

        if current != FLAT and active_signal.endswith(current[-1]):
            current = FLAT
            latest_signal[idx] = FLAT

        last_signal.append(active_signal)
        if active_signal.endswith("_B") and active_signal_idx is not None:
            basis_idx = min(active_signal_idx + profit_execution_delay_days, len(close_values) - 1)
            if idx <= active_signal_idx:
                basis_idx = active_signal_idx
            active_signal_price = float(close_values[basis_idx])
            profit_values.append((float(close_values[idx]) / active_signal_price - 1) * 100)
        else:
            profit_values.append("-")

        if current != FLAT:
            active_signal = current
            active_signal_idx = idx

    df["latest_signal"] = latest_signal
    df["last_signal"] = last_signal
    df["profit_since_last_signal"] = profit_values
    return df


def add_signals(features: pd.DataFrame, strategy: dict | None = None) -> pd.DataFrame:
    """Add buy/sell signal fields to an indicator table."""
    required = {"date", "code", "trend", "ret20_pct", "close", "ma20"}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"Feature data missing columns: {sorted(missing)}")
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    signaled = pd.concat(
        [_signals_one_group(group, strategy=strategy) for _, group in df.groupby("code", sort=False)],
        ignore_index=True,
    )
    return signaled.reset_index(drop=True)
