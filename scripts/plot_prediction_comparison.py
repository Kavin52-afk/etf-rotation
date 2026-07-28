"""Plot real ETF moves against distilled-object and local model predictions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Iterable
import warnings

os.environ.setdefault("MPLCONFIGDIR", "/tmp/etf_rotation_matplotlib")
warnings.filterwarnings("ignore", message=r"Glyph (108|112).*Droid Sans Fallback", category=UserWarning)

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_rotation.backtest import run_backtest  # noqa: E402
from etf_rotation.config import ProjectConfig, load_project_config  # noqa: E402
from etf_rotation.data_provider import load_prices  # noqa: E402
from etf_rotation.execution_workbench import _load_holding_overrides  # noqa: E402
from etf_rotation.realworld_execution import freeze_signal  # noqa: E402
from etf_rotation.risk_overlay import apply_risk_overlay  # noqa: E402
from etf_rotation.selector import select_holdings  # noqa: E402
from etf_rotation.stability_controller import apply_stability_controls  # noqa: E402
from etf_rotation.utils import ensure_dir, from_pipe_list, to_pipe_list  # noqa: E402


FONT_CANDIDATES = [
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
]


def _setup_chinese_font() -> font_manager.FontProperties:
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", *plt.rcParams.get("font.sans-serif", [])]
    plt.rcParams["axes.unicode_minus"] = False
    for path in FONT_CANDIDATES:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            return font_manager.FontProperties(fname=str(path))
    return font_manager.FontProperties()


CHINESE_FONT = _setup_chinese_font()

FULLWIDTH_TRANS = str.maketrans(
    {
        **{str(i): chr(ord("０") + i) for i in range(10)},
        **{chr(code): chr(ord("Ａ") + code - ord("A")) for code in range(ord("A"), ord("Z") + 1)},
        **{chr(code): chr(ord("ａ") + code - ord("a")) for code in range(ord("a"), ord("z") + 1)},
        "-": "－",
        "+": "＋",
        "/": "／",
        "%": "％",
        "(": "（",
        ")": "）",
        "=": "＝",
        ".": "．",
        ":": "：",
        "|": "｜",
    }
)

SHORT_LABELS = {
    "588000.SH": "科创五十",
    "513520.SH": "日经二二五",
    "164824.SZ": "印度",
    "513030.SH": "德国",
    "159985.SZ": "豆粕",
    "563300.SH": "中证二千",
    "159338.SZ": "中证五百",
    "159949.SZ": "创业板五十",
}

DEFAULT_PLOT_CODES = ["588000.SH", "513520.SH", "164824.SZ", "513030.SH", "159985.SZ"]
DIGIT_CN = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}


def _short(code: str) -> str:
    return _fw(SHORT_LABELS.get(str(code), str(code).split(".")[0]))


def _fw(text: object) -> str:
    return str(text).translate(FULLWIDTH_TRANS)


def _combo(codes: Iterable[str]) -> str:
    values = [str(code) for code in codes if str(code)]
    return "、".join(_short(code) for code in values) if values else "无"


def _number_cn(value: int) -> str:
    if value <= 10:
        return ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][value]
    if value < 20:
        return "十" + _number_cn(value - 10)
    tens, ones = divmod(value, 10)
    return _number_cn(tens) + "十" + (_number_cn(ones) if ones else "")


def _date_cn(value: object) -> str:
    date_value = pd.Timestamp(value)
    year = "".join(DIGIT_CN[digit] for digit in f"{date_value.year}")
    return f"{year}年{_number_cn(date_value.month)}月{_number_cn(date_value.day)}日"


def _month_day_cn(value: object) -> str:
    date_value = pd.Timestamp(value)
    return f"{_number_cn(date_value.month)}月{_number_cn(date_value.day)}日"


def _signal_text(buy_codes: Iterable[str], sell_codes: Iterable[str]) -> str:
    buy = [str(code) for code in buy_codes if str(code)]
    sell = [str(code) for code in sell_codes if str(code)]
    parts: list[str] = []
    if buy:
        parts.append("买 " + "、".join(_short(code) for code in buy))
    if sell:
        parts.append("卖 " + "、".join(_short(code) for code in sell))
    return "\n".join(parts) if parts else "无"


def _signal_date_for_report(report_date: pd.Timestamp, trading_dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    cutoff = pd.Timestamp(report_date).normalize() - pd.Timedelta(days=1)
    possible = [dt for dt in trading_dates if dt <= cutoff]
    return possible[-1] if possible else None


def _next_trading_date(signal_date: pd.Timestamp, trading_dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    future = [dt for dt in trading_dates if dt > signal_date]
    return future[0] if future else None


def _portfolio_return_pct(
    prices: pd.DataFrame,
    codes: Iterable[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp | None,
) -> float:
    if end_date is None:
        return float("nan")
    frame = prices[
        prices["date"].isin([start_date, end_date]) & prices["code"].astype(str).isin([str(code) for code in codes])
    ]
    if frame.empty:
        return float("nan")
    pivot = frame.pivot_table(index="date", columns="code", values="close", aggfunc="last")
    if start_date not in pivot.index or end_date not in pivot.index:
        return float("nan")
    rets = pivot.loc[end_date].astype(float) / pivot.loc[start_date].astype(float) - 1.0
    rets = rets.replace([np.inf, -np.inf], np.nan).dropna()
    return float(rets.mean() * 100.0) if not rets.empty else float("nan")


def _build_model_contexts(
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    signal_dates: Iterable[pd.Timestamp],
) -> dict[pd.Timestamp, dict[str, object]]:
    requested = sorted({pd.Timestamp(dt).normalize() for dt in signal_dates})
    if not requested:
        return {}

    result = run_backtest(prices, cfg, start=None, end=requested[-1].strftime("%Y-%m-%d"), write_reports=False)
    history_dates = sorted(pd.Timestamp(dt).normalize() for dt in result.target_history)
    holding_overrides = _load_holding_overrides(cfg)
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))

    contexts: dict[pd.Timestamp, dict[str, object]] = {}
    for requested_date in requested:
        available_dates = [dt for dt in history_dates if dt <= requested_date]
        if not available_dates:
            continue
        as_of = available_dates[-1]
        idx = history_dates.index(as_of)
        yesterday = list(result.target_history[history_dates[idx - 1]]) if idx > 0 else []
        proposed = list(result.target_history[as_of])
        ranking = result.ranking_history[as_of].copy()

        prior_history = {dt: result.target_history[dt] for dt in history_dates if dt < as_of}
        for override_date, override_codes in holding_overrides.items():
            if override_date < as_of:
                prior_history[pd.Timestamp(override_date).normalize()] = override_codes

        override_used = False
        if as_of in holding_overrides or any(dt < as_of for dt in holding_overrides):
            override_used = True
            latest_features = result.features[result.features["date"].eq(as_of)].copy()
            yesterday = list(holding_overrides.get(as_of, yesterday))
            selection = select_holdings(
                latest_features=latest_features,
                yesterday_holdings=yesterday,
                history_holdings=prior_history,
                strategy=cfg.strategy,
                max_hold=max_hold,
            )
            proposed = list(selection.target_holdings)
            ranking = selection.ranking_table

        risk_table = apply_risk_overlay(ranking, cfg.strategy)
        stability = apply_stability_controls(as_of, yesterday, proposed, prior_history, prices=prices, max_changes=1)
        freeze = freeze_signal(as_of, stability.target_holdings, risk_table, state_dir=None, persist=False)

        contexts[requested_date] = {
            "as_of": as_of,
            "yesterday": yesterday,
            "proposed": proposed,
            "final": list(freeze.state.frozen_signal),
            "ignored_signals": list(stability.ignored_signals),
            "override_used": override_used,
        }
    return contexts


def _comparison_rows(prices: pd.DataFrame, cfg: ProjectConfig, labels_path: Path) -> pd.DataFrame:
    labels = pd.read_csv(labels_path).fillna("")
    labels["report_date"] = pd.to_datetime(labels["report_date"]).dt.normalize()
    trading_dates = sorted(pd.Timestamp(dt).normalize() for dt in prices["date"].drop_duplicates())

    rows: list[dict[str, object]] = []
    for row in labels.itertuples(index=False):
        report_date = pd.Timestamp(row.report_date).normalize()
        signal_date = _signal_date_for_report(report_date, trading_dates)
        if signal_date is None:
            continue
        rows.append(
            {
                "report_date": report_date,
                "signal_close_date": signal_date,
                "next_trade_date": _next_trading_date(signal_date, trading_dates),
                "object_target_codes": from_pipe_list(row.target_holdings),
                "object_buy_codes": from_pipe_list(row.buy_signals),
                "object_sell_codes": from_pipe_list(row.sell_signals),
            }
        )

    contexts = _build_model_contexts(prices, cfg, [row["signal_close_date"] for row in rows])

    enriched: list[dict[str, object]] = []
    for row in rows:
        signal_date = pd.Timestamp(row["signal_close_date"]).normalize()
        next_date = row["next_trade_date"]
        context = contexts.get(signal_date, {})
        object_target = list(row["object_target_codes"])
        model_final = list(context.get("final", []))
        model_raw = list(context.get("proposed", []))
        exact_final = set(object_target) == set(model_final)
        exact_raw = set(object_target) == set(model_raw)
        enriched.append(
            {
                "report_date": pd.Timestamp(row["report_date"]).strftime("%Y-%m-%d"),
                "signal_close_date": signal_date.strftime("%Y-%m-%d"),
                "next_trade_date": pd.Timestamp(next_date).strftime("%Y-%m-%d") if next_date is not None else "",
                "object_target_codes": to_pipe_list(object_target),
                "object_target_labels": _combo(object_target),
                "model_final_codes": to_pipe_list(model_final),
                "model_final_labels": _combo(model_final),
                "model_raw_codes": to_pipe_list(model_raw),
                "model_raw_labels": _combo(model_raw),
                "exact_final": exact_final,
                "exact_raw": exact_raw,
                "object_signal": _signal_text(row["object_buy_codes"], row["object_sell_codes"]),
                "ignored_signals": "|".join(context.get("ignored_signals", [])),
                "override_used": bool(context.get("override_used", False)),
                "object_next_return_pct": _portfolio_return_pct(prices, object_target, signal_date, next_date),
                "model_final_next_return_pct": _portfolio_return_pct(prices, model_final, signal_date, next_date),
                "model_raw_next_return_pct": _portfolio_return_pct(prices, model_raw, signal_date, next_date),
            }
        )
    return pd.DataFrame(enriched)


def _plot_market_panel(ax: plt.Axes, prices: pd.DataFrame, comparison: pd.DataFrame) -> None:
    signal_dates = pd.to_datetime(comparison["signal_close_date"]).dt.normalize()
    window_start = signal_dates.min() - pd.Timedelta(days=14)
    window_end = signal_dates.max()
    plot_codes = list(DEFAULT_PLOT_CODES)
    frame = prices[
        prices["date"].between(window_start, window_end) & prices["code"].astype(str).isin(plot_codes)
    ].copy()
    pivot = frame.pivot_table(index="date", columns="code", values="close", aggfunc="last").sort_index()
    normalized = pivot.divide(pivot.apply(lambda col: col.dropna().iloc[0] if col.dropna().size else np.nan), axis=1) * 100.0

    colors = {
        "588000.SH": "#2563eb",
        "513520.SH": "#059669",
        "164824.SZ": "#d97706",
        "513030.SH": "#7c3aed",
        "159985.SZ": "#dc2626",
    }
    for code in plot_codes:
        if code in normalized:
            ax.plot(
                normalized.index,
                normalized[code],
                label=_short(code),
                color=colors.get(code),
                linewidth=2.0,
            )

    for row in comparison.itertuples(index=False):
        signal_date = pd.Timestamp(row.signal_close_date)
        ax.axvline(signal_date, color="#64748b", linewidth=0.9, linestyle="--", alpha=0.45)
        ax.text(
            signal_date,
            1.01,
            _month_day_cn(row.report_date),
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=8,
            color="#334155",
            fontproperties=CHINESE_FONT,
        )
        raw_codes = from_pipe_list(row.model_raw_codes)
        final_codes = from_pipe_list(row.model_final_codes)
        object_codes = from_pipe_list(row.object_target_codes)
        for code in object_codes:
            if code in normalized and signal_date in normalized.index:
                ax.scatter(signal_date, normalized.loc[signal_date, code], color="#111827", s=28, marker="o", zorder=6)
        for code in final_codes:
            if code in normalized and signal_date in normalized.index:
                ax.scatter(signal_date, normalized.loc[signal_date, code], color="#16a34a", s=46, marker="x", zorder=7)
        for code in set(raw_codes) - set(final_codes):
            if code in normalized and signal_date in normalized.index:
                ax.scatter(signal_date, normalized.loc[signal_date, code], color="#dc2626", s=38, marker="D", zorder=8)

    ax.set_title(
        "市场真实走势（收盘价归一化，首个可见交易日等于一百）",
        loc="left",
        fontsize=12,
        pad=10,
        fontproperties=CHINESE_FONT,
    )
    ax.set_ylabel("收盘指数", fontproperties=CHINESE_FONT)
    ax.grid(True, axis="y", color="#e2e8f0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=5, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.02), fontsize=9, prop=CHINESE_FONT)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))


def _plot_return_panel(ax: plt.Axes, comparison: pd.DataFrame) -> None:
    x = np.arange(len(comparison))
    width = 0.24
    object_ret = pd.to_numeric(comparison["object_next_return_pct"], errors="coerce").to_numpy()
    final_ret = pd.to_numeric(comparison["model_final_next_return_pct"], errors="coerce").to_numpy()
    raw_ret = pd.to_numeric(comparison["model_raw_next_return_pct"], errors="coerce").to_numpy()

    ax.bar(x - width, object_ret, width=width, label="蒸馏对象", color="#111827", alpha=0.86)
    ax.bar(x, final_ret, width=width, label="我们最终预测", color="#16a34a", alpha=0.82)
    ax.bar(x + width, raw_ret, width=width, label="我们原始预测", color="#dc2626", alpha=0.72)
    ax.axhline(0, color="#334155", linewidth=0.8)

    for idx, value in enumerate(object_ret):
        if np.isnan(value):
            ax.text(idx, 0, "暂无", ha="center", va="bottom", fontsize=8, color="#64748b", fontproperties=CHINESE_FONT)

    labels = [
        f"{_date_cn(row.report_date)}\n信号{_month_day_cn(row.signal_close_date)}"
        for row in comparison.itertuples(index=False)
    ]
    ax.set_xticks(x, labels, fontsize=8)
    for label in ax.get_xticklabels():
        label.set_fontproperties(CHINESE_FONT)
    ax.set_ylabel("下一交易日收盘收益百分比", fontproperties=CHINESE_FONT)
    ax.set_title("每次信号后的真实下一交易日收益", loc="left", fontsize=12, pad=10, fontproperties=CHINESE_FONT)
    ax.grid(True, axis="y", color="#e2e8f0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper left", fontsize=9, prop=CHINESE_FONT)


def _plot_table_panel(ax: plt.Axes, comparison: pd.DataFrame) -> None:
    ax.axis("off")
    col_labels = [_date_cn(value) for value in comparison["report_date"]]
    rows = [
        ("信号收盘日", [_date_cn(value) for value in comparison["signal_close_date"]]),
        ("蒸馏对象目标", list(comparison["object_target_labels"])),
        ("我们最终预测", list(comparison["model_final_labels"])),
        ("我们原始预测", list(comparison["model_raw_labels"])),
        ("最终是否匹配", ["是" if value else "否" for value in comparison["exact_final"]]),
        ("蒸馏对象信号", list(comparison["object_signal"])),
    ]
    cell_text = [values for _, values in rows]
    row_labels = [label for label, _ in rows]
    table = ax.table(
        cellText=cell_text,
        rowLabels=row_labels,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
        rowLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.45)

    for (row, col), cell in table.get_celld().items():
        cell.get_text().set_fontproperties(CHINESE_FONT)
        cell.set_edgecolor("#cbd5e1")
        cell.set_linewidth(0.6)
        if row == 0:
            cell.set_facecolor("#e2e8f0")
            cell.set_text_props(weight="bold", color="#0f172a")
        if col == -1:
            cell.set_facecolor("#f8fafc")
            cell.set_text_props(weight="bold", color="#334155")
        cell.get_text().set_fontproperties(CHINESE_FONT)

    exact_row = 5
    for col, exact in enumerate(comparison["exact_final"]):
        cell = table[(exact_row, col)]
        cell.set_facecolor("#dcfce7" if exact else "#fee2e2")
        cell.set_text_props(color="#166534" if exact else "#991b1b", weight="bold")
        cell.get_text().set_fontproperties(CHINESE_FONT)
    ax.set_title("预测对照表", loc="left", fontsize=12, pad=6, fontproperties=CHINESE_FONT)


def write_plot(prices: pd.DataFrame, comparison: pd.DataFrame, output_path: Path) -> None:
    ensure_dir(output_path.parent)
    max_real_date = pd.Timestamp(prices["date"].max()).strftime("%Y-%m-%d")
    fig = plt.figure(figsize=(16, 10), constrained_layout=False)
    gs = fig.add_gridspec(nrows=3, ncols=1, height_ratios=[2.1, 1.15, 1.45], hspace=0.42)
    ax_market = fig.add_subplot(gs[0, 0])
    ax_return = fig.add_subplot(gs[1, 0])
    ax_table = fig.add_subplot(gs[2, 0])

    _plot_market_panel(ax_market, prices, comparison)
    _plot_return_panel(ax_return, comparison)
    _plot_table_panel(ax_table, comparison)
    fig.suptitle(
        "市场真实走势、蒸馏对象预测与我们的预测",
        fontsize=16,
        x=0.05,
        ha="left",
        y=1.005,
        fontproperties=CHINESE_FONT,
    )
    fig.text(
        0.05,
        0.955,
        f"本地日线收盘价截至{_date_cn(max_real_date)}；{_date_cn('2026-07-08')}按前一交易日收盘生成的预测进行对比。",
        fontsize=9,
        color="#475569",
        ha="left",
        fontproperties=CHINESE_FONT,
    )
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels",
        type=Path,
        default=ROOT / "data" / "labels" / "manual_object_signals_2026-07.csv",
        help="Manual distilled-object signal CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "reports" / "prediction_comparison_2026-07.png",
        help="Output PNG path.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "data" / "reports" / "prediction_comparison_2026-07.csv",
        help="Output comparison CSV path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_project_config(ROOT)
    prices = load_prices(cfg)

    comparison = _comparison_rows(prices, cfg, args.labels)
    ensure_dir(args.csv.parent)
    comparison.to_csv(args.csv, index=False)
    write_plot(prices, comparison, args.output)
    print(f"wrote {args.output}")
    print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
