"""Incrementally fill ETF daily prices from Sina via AKShare."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import shutil
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_rotation.config import load_project_config  # noqa: E402
from etf_rotation.data_provider import PRICE_COLUMNS, normalize_price_frame  # noqa: E402
from etf_rotation.universe import ETF, code_to_ak_symbol, load_universe  # noqa: E402


def _sina_symbol(code: str) -> str:
    suffix = "sh" if str(code).upper().endswith(".SH") else "sz"
    return f"{suffix}{code_to_ak_symbol(code)}"


def _fetch_sina_etf(symbol: ETF, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    import akshare as ak

    raw = ak.fund_etf_hist_sina(symbol=_sina_symbol(symbol.code))
    if raw.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    if "volume" in frame.columns:
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") / 100.0
    return normalize_price_frame(frame, symbol)


def main() -> None:
    cfg = load_project_config()
    cache = cfg.price_cache
    old = pd.read_parquet(cache)
    old["date"] = pd.to_datetime(old["date"]).dt.normalize()
    start = old["date"].max() + pd.Timedelta(days=1)
    end = pd.Timestamp(date.today()).normalize()
    print(f"cache={cache}")
    print(f"old_max={old['date'].max().date()} fetch_window={start.date()}->{end.date()}")
    if start > end:
        print("cache already current for today")
        return

    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for symbol in load_universe(cfg.universe, pools=["broad_etf"]):
        try:
            frame = _fetch_sina_etf(symbol, start, end)
            if frame.empty:
                print(f"EMPTY {symbol.code} {symbol.name}")
            else:
                print(f"OK {symbol.code} {symbol.name} {frame.date.min().date()}->{frame.date.max().date()} rows={len(frame)}")
                frames.append(frame)
        except Exception as exc:
            msg = f"ERR {symbol.code} {symbol.name}: {type(exc).__name__}: {exc}"
            print(msg)
            errors.append(msg)

    if not frames:
        raise SystemExit("no Sina incremental rows fetched")

    new = pd.concat(frames, ignore_index=True)
    backup = cache.with_name(f"{cache.stem}_before_sina_{date.today().strftime('%Y%m%d')}.parquet")
    shutil.copy2(cache, backup)
    combined = pd.concat([old, new], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.normalize()
    combined = combined.drop_duplicates(["date", "code"], keep="last").sort_values(["date", "code"]).reset_index(drop=True)
    combined.to_parquet(cache, index=False)
    print(f"backup={backup}")
    print(f"new_rows={len(new)} combined_rows={len(combined)} combined_max={combined.date.max().date()} codes={combined.code.nunique()}")
    if errors:
        print("errors:")
        for msg in errors:
            print(msg)


if __name__ == "__main__":
    main()
