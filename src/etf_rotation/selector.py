"""ETF ranking and target-holding selection logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .indicators import DOWN, FLAT, STAR, UP

CHECK = "√"
CROSS = "×"


@dataclass(frozen=True)
class SelectionResult:
    """Selection output for one as-of date."""

    ranking_table: pd.DataFrame
    target_holdings: list[str]
    buy_list: list[str]
    sell_list: list[str]
    status_marks: dict[str, str]


def _as_set(values: Iterable[str] | None) -> set[str]:
    """Convert holdings to a string set."""
    return {str(item) for item in values or [] if str(item)}


def _signal_text(row: pd.Series) -> str:
    """Return the most actionable signal text from a ranking row."""
    latest = str(row.get("latest_signal", FLAT))
    if latest != FLAT:
        return latest
    return str(row.get("last_signal", FLAT))


def has_sell_signal(row: pd.Series) -> bool:
    """Return whether a row has a current or last sell signal."""
    return _signal_text(row).endswith("_S")


def has_buy_signal(row: pd.Series) -> bool:
    """Return whether a row has a current or last buy signal."""
    return _signal_text(row).endswith("_B")


def qdii_blocked(row: pd.Series, strategy: dict) -> bool:
    """Return whether a QDII premium blocks a new position."""
    score_cfg = strategy.get("score", {})
    block = 1 + float(score_cfg.get("qdii_premium_block", 8.0)) / 100
    return bool(row.get("qdii", False)) and float(row.get("premium_pb", 1.0)) > block


def _numeric_value(value: object) -> float | None:
    """Return a float for scalar report values, or None when unavailable."""
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def overheat_take_profit(row: pd.Series, strategy: dict) -> bool:
    """Return whether an existing holding should be sold for overheat profit-taking."""
    signal_cfg = strategy.get("signals", {})
    if not bool(signal_cfg.get("profit_take_on_overheat_for_existing", False)):
        return False

    score_cfg = strategy.get("score", {})
    threshold = float(signal_cfg.get("profit_take_bias_threshold", score_cfg.get("overheat_bias_threshold", 12.0)))
    bias = _numeric_value(row.get("bias_pct"))
    if bias is None or bias <= threshold:
        return False

    min_profit = signal_cfg.get("profit_take_min_profit_pct")
    if min_profit is not None:
        profit = _numeric_value(row.get("profit_since_last_signal"))
        if profit is None or profit < float(min_profit):
            return False
    return True


def score_row(row: pd.Series, strategy: dict, yesterday_holdings: set[str]) -> float:
    """Compute the configurable composite ETF score for one row."""
    score_cfg = strategy.get("score", {})
    ret20 = row.get("ret20_pct", 0.0)
    ret20_value = 0.0 if pd.isna(ret20) else float(ret20)
    score = ret20_value * float(score_cfg.get("momentum_weight", 1.0))

    trend = row.get("trend", FLAT)
    if trend == UP:
        score += float(score_cfg.get("trend_up_bonus", 5.0))
    elif trend == DOWN:
        score += float(score_cfg.get("trend_down_penalty", -20.0))
    else:
        score += float(score_cfg.get("trend_flat_bonus", 0.0))

    if row.get("market_signal") == STAR:
        score += float(score_cfg.get("star_bonus", 3.0))
    if row.get("convex") == UP:
        score += float(score_cfg.get("convex_up_bonus", 2.0))
    if str(row.get("code")) in yesterday_holdings:
        score += float(score_cfg.get("holding_bonus", 4.0))
    if has_buy_signal(row):
        score += float(score_cfg.get("buy_signal_bonus", 4.0))
    if has_sell_signal(row):
        score += float(score_cfg.get("sell_signal_penalty", -999.0))

    bias = row.get("bias_pct", 0.0)
    bias_value = 0.0 if pd.isna(bias) else float(bias)
    if bias_value > float(score_cfg.get("overheat_bias_threshold", 12.0)):
        score += float(score_cfg.get("overheat_penalty", -6.0))
    if bias_value > float(score_cfg.get("extreme_overheat_bias_threshold", 18.0)):
        score += float(score_cfg.get("extreme_overheat_penalty", -12.0))

    warn = 1 + float(score_cfg.get("qdii_premium_warn", 5.0)) / 100
    is_existing = str(row.get("code")) in yesterday_holdings
    if bool(row.get("qdii", False)) and not is_existing and float(row.get("premium_pb", 1.0)) > warn:
        score += float(score_cfg.get("qdii_premium_penalty", -10.0))
    return float(score)


def rank_candidates(latest_features: pd.DataFrame, strategy: dict, yesterday_holdings: Iterable[str] | None) -> pd.DataFrame:
    """Create a ranking table sorted by momentum and annotated with scores."""
    if latest_features.empty:
        raise ValueError("Cannot rank an empty feature table.")
    yesterday = _as_set(yesterday_holdings)
    df = latest_features.copy()
    df["ret20_pct"] = pd.to_numeric(df["ret20_pct"], errors="coerce")
    df = df.sort_values(["ret20_pct", "code"], ascending=[False, True]).reset_index(drop=True)
    df["momentum_rank"] = range(1, len(df) + 1)
    df["score"] = [score_row(row, strategy, yesterday) for _, row in df.iterrows()]
    df["score_rank"] = df["score"].rank(method="first", ascending=False).astype(int)
    return df.sort_values(["score", "ret20_pct"], ascending=[False, False]).reset_index(drop=True)


def eligible_new_position(row: pd.Series, strategy: dict) -> bool:
    """Return whether a row can be opened as a new target holding."""
    rebalance = strategy.get("rebalance", {})
    if has_sell_signal(row) or row.get("trend") == DOWN:
        return False
    if row.get("trend") == FLAT and not bool(rebalance.get("allow_flat_trend_for_new", False)):
        return False
    if bool(rebalance.get("require_positive_ret20_for_new", True)):
        ret20 = row.get("ret20_pct", 0.0)
        if pd.isna(ret20) or float(ret20) <= 0:
            return False
    if qdii_blocked(row, strategy):
        return False
    return True


def retain_existing(row: pd.Series, strategy: dict) -> bool:
    """Return whether an existing holding should be retained by inertia."""
    rebalance = strategy.get("rebalance", {})
    if has_sell_signal(row) or row.get("trend") == DOWN:
        return False
    if overheat_take_profit(row, strategy):
        return False
    if row.get("trend") == FLAT and not bool(rebalance.get("allow_flat_trend_for_existing", True)):
        return False
    return int(row.get("momentum_rank", 9999)) <= int(rebalance.get("keep_if_rank_le", 4))


def select_holdings(
    latest_features: pd.DataFrame,
    yesterday_holdings: Iterable[str] | None,
    history_holdings: dict[pd.Timestamp, list[str]] | None,
    strategy: dict,
    max_hold: int | None = None,
) -> SelectionResult:
    """Select target ETF holdings for one date using score and inertia rules."""
    max_hold = int(max_hold or strategy.get("max_hold_broad", 2))
    yesterday = _as_set(yesterday_holdings)
    ranking = rank_candidates(latest_features, strategy, yesterday)
    row_by_code = {str(row.code): pd.Series(row._asdict()) for row in ranking.itertuples(index=False)}

    forced_exit_codes = {
        code for code in yesterday if code in row_by_code and overheat_take_profit(row_by_code[code], strategy)
    }
    selected: list[str] = []
    for code in yesterday:
        row = row_by_code.get(code)
        if row is not None and retain_existing(row, strategy):
            selected.append(code)

    selected = sorted(set(selected), key=lambda code: float(row_by_code[code].get("score", -9999)), reverse=True)

    for row in ranking.itertuples(index=False):
        code = str(row.code)
        if len(selected) >= max_hold:
            break
        if code in selected:
            continue
        if code in forced_exit_codes:
            continue
        row_series = pd.Series(row._asdict())
        if eligible_new_position(row_series, strategy):
            selected.append(code)

    margin = float(strategy.get("rebalance", {}).get("replace_only_if_new_score_better_by", 3.0))
    for row in ranking.itertuples(index=False):
        if len(selected) < max_hold:
            break
        code = str(row.code)
        if code in selected:
            continue
        if code in forced_exit_codes:
            continue
        row_series = pd.Series(row._asdict())
        if not eligible_new_position(row_series, strategy):
            continue
        replaceable = [old for old in selected if old in yesterday and retain_existing(row_by_code[old], strategy)]
        if not replaceable:
            continue
        worst_old = min(replaceable, key=lambda old: float(row_by_code[old].get("score", -9999)))
        if float(row.score) > float(row_by_code[worst_old].get("score", -9999)) + margin:
            selected.remove(worst_old)
            selected.append(code)
            break

    selected = selected[:max_hold]
    buy_list = [code for code in selected if code not in yesterday]
    sell_list = [code for code in yesterday if code not in selected]

    as_of = pd.Timestamp(ranking["date"].max()).normalize()
    history = dict(history_holdings or {})
    history[as_of] = selected
    status_marks = generate_status_marks(history, as_of, ranking["code"].astype(str).tolist())
    ranking["status_mark"] = ranking["code"].map(status_marks).fillna(CROSS * 3)
    return SelectionResult(ranking, selected, buy_list, sell_list, status_marks)


def generate_status_marks(
    history_holdings: dict[pd.Timestamp, list[str]],
    current_date: pd.Timestamp,
    universe_codes: Iterable[str],
) -> dict[str, str]:
    """Generate three-character recent target-holding marks for each ETF."""
    current_ts = pd.Timestamp(current_date).normalize()
    normalized_history = {pd.Timestamp(k).normalize(): _as_set(v) for k, v in history_holdings.items()}
    dates = sorted([dt for dt in normalized_history if dt <= current_ts])[-3:]
    while len(dates) < 3:
        dates.insert(0, pd.NaT)

    marks: dict[str, str] = {}
    for code in universe_codes:
        chars = []
        for dt in dates:
            chars.append(CHECK if pd.notna(dt) and code in normalized_history.get(dt, set()) else CROSS)
        marks[str(code)] = "".join(chars)
    return marks


def annotate_holding_changes(yesterday_holdings: list[str], today_holdings: list[str]) -> tuple[list[str], list[str]]:
    """Append up/down arrows to changed display-name holdings."""
    yesterday_set = set(yesterday_holdings)
    today_set = set(today_holdings)
    yesterday_display = [f"{name}↓" if name not in today_set else name for name in yesterday_holdings]
    today_display = [f"{name}↑" if name not in yesterday_set else name for name in today_holdings]
    return yesterday_display, today_display
