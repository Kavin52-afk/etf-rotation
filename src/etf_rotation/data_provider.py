"""Market data providers and local cache helpers."""

from __future__ import annotations

from datetime import date
import multiprocessing as mp
from pathlib import Path
from queue import Empty
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from rich.console import Console

from .config import ProjectConfig
from .universe import ETF, code_to_ak_symbol, load_universe
from .utils import ensure_dir, parse_date, yyyymmdd

console = Console()

PRICE_COLUMNS = ["date", "code", "name", "open", "high", "low", "close", "volume", "amount"]

CN_FIELD_MAP = {
    "日期": "date",
    "开盘": "open",
    "开盘价": "open",
    "最高": "high",
    "最高价": "high",
    "最低": "low",
    "最低价": "low",
    "收盘": "close",
    "收盘价": "close",
    "成交量": "volume",
    "成交额": "amount",
}


def _akshare_worker(
    queue: mp.Queue,
    symbol: str,
    start_date: str,
    end_date: str,
) -> None:
    """Fetch one AKShare symbol in a child process so it can be timed out."""
    try:
        import akshare as ak

        raw = ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        queue.put(("ok", raw))
    except Exception as exc:  # pragma: no cover - provider dependent
        queue.put(("error", repr(exc)))


def _fetch_akshare_raw_with_timeout(symbol: ETF, start_date: str, end_date: str, timeout_seconds: int) -> pd.DataFrame:
    """Fetch one symbol from AKShare with a hard process timeout."""
    ctx = mp.get_context("fork")
    queue: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_akshare_worker,
        args=(queue, code_to_ak_symbol(symbol.code), start_date, end_date),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(f"request timed out after {timeout_seconds}s")
    try:
        status, payload = queue.get_nowait()
    except Empty as exc:
        raise RuntimeError("provider returned no result") from exc
    if status == "error":
        raise RuntimeError(str(payload))
    return payload


def normalize_price_frame(frame: pd.DataFrame, symbol: ETF) -> pd.DataFrame:
    """Normalize AKShare or synthetic frames to the standard OHLCV schema."""
    if frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df = frame.rename(columns={col: CN_FIELD_MAP.get(col, col) for col in frame.columns}).copy()
    missing = {"date", "open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"{symbol.code} data missing required fields: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["code"] = symbol.code
    df["name"] = symbol.name
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[PRICE_COLUMNS].dropna(subset=["date", "open", "high", "low", "close"])
    return df.sort_values(["date", "code"]).reset_index(drop=True)


def eastmoney_secid(code: str) -> str:
    """Return Eastmoney secid for a suffixed ETF code."""
    symbol = code_to_ak_symbol(code)
    market = "1" if str(code).upper().endswith(".SH") else "0"
    return f"{market}.{symbol}"


def eastmoney_secid_for_symbol(symbol: ETF) -> str:
    """Return the configured or inferred Eastmoney secid for one symbol."""
    if symbol.secid:
        return symbol.secid
    return eastmoney_secid(symbol.code)


def fetch_eastmoney_prices(symbol: ETF, start_date: str, end_date: str, timeout_seconds: int) -> pd.DataFrame:
    """Fetch ETF daily prices directly from Eastmoney's kline endpoint."""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "1",
        "beg": start_date,
        "end": end_date,
        "secid": eastmoney_secid_for_symbol(symbol),
    }
    response = requests.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    rows: list[dict[str, object]] = []
    for item in klines:
        fields = str(item).split(",")
        if len(fields) < 7:
            continue
        rows.append(
            {
                "date": fields[0],
                "open": fields[1],
                "close": fields[2],
                "high": fields[3],
                "low": fields[4],
                "volume": fields[5],
                "amount": fields[6],
            }
        )
    return normalize_price_frame(pd.DataFrame(rows), symbol)


def _business_dates(start: str | date, end: str | date) -> pd.DatetimeIndex:
    """Return weekday dates used by synthetic sample data."""
    return pd.date_range(start=start, end=end, freq="B")


def generate_sample_prices(symbols: Iterable[ETF], start: str, end: str | date, seed: int) -> pd.DataFrame:
    """Generate deterministic synthetic ETF daily data for offline testing."""
    rng = np.random.default_rng(seed)
    dates = _business_dates(start, end)
    frames: list[pd.DataFrame] = []

    for index, symbol in enumerate(symbols):
        n = len(dates)
        base = 1.0 + (index % 9) * 0.12
        drift = 0.0001 + ((index % 7) - 2) * 0.00012
        seasonal = 0.0025 * np.sin(np.linspace(0, 9 * np.pi, n) + index / 3)
        factor_cycle = np.zeros(n)
        if index % 5 == 0:
            factor_cycle[n // 3 : n // 3 * 2] = 0.0012
        if index % 4 == 1:
            factor_cycle[n // 2 :] += 0.0009
        noise = rng.normal(0, 0.008 + (index % 4) * 0.001, n)
        returns = drift + seasonal + factor_cycle + noise
        close = base * np.cumprod(1 + returns)
        open_ = close / (1 + rng.normal(0, 0.003, n))
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.006, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.006, n))
        volume = rng.integers(1_000_000, 20_000_000, n)
        amount = volume * close * 100
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "code": symbol.code,
                    "name": symbol.name,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                }
            )
        )
    data = pd.concat(frames, ignore_index=True)
    return data.sort_values(["date", "code"]).reset_index(drop=True)


def init_sample_data(cfg: ProjectConfig) -> Path:
    """Generate and cache synthetic sample prices."""
    symbols = load_universe(cfg.universe, pools=["broad_etf", "sector_etf", "market_index"])
    sample_cfg = cfg.data.get("sample", {})
    start = str(sample_cfg.get("start", "2020-01-01"))
    seed = int(sample_cfg.get("seed", 20260628))
    prices = generate_sample_prices(symbols, start=start, end=date.today(), seed=seed)
    ensure_dir(cfg.sample_price_cache.parent)
    prices.to_parquet(cfg.sample_price_cache, index=False)
    return cfg.sample_price_cache


def read_price_cache(path: Path) -> pd.DataFrame:
    """Read a price parquet cache and validate the minimum schema."""
    if not path.exists():
        raise FileNotFoundError(f"Price cache not found: {path}")
    df = pd.read_parquet(path)
    missing = set(PRICE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Price cache missing columns: {sorted(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(["date", "code"]).reset_index(drop=True)


def load_prices(cfg: ProjectConfig, sample: bool = False) -> pd.DataFrame:
    """Load either synthetic sample prices or real cached prices."""
    path = cfg.sample_price_cache if sample else cfg.price_cache
    if not path.exists() and not sample and cfg.sample_price_cache.exists():
        console.print("[yellow]Real price cache not found; using sample cache. Pass --sample to make this explicit.[/yellow]")
        path = cfg.sample_price_cache
    return read_price_cache(path)


def load_premium_cache(cfg: ProjectConfig) -> pd.DataFrame:
    """Load optional QDII premium/PB cache if present."""
    if not cfg.premium_cache.exists():
        return pd.DataFrame(columns=["date", "code", "premium_pct", "premium_pb"])
    df = pd.read_csv(cfg.premium_cache)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    if "pb" in df.columns and "premium_pb" not in df.columns:
        df["premium_pb"] = pd.to_numeric(df["pb"], errors="coerce")
    if "premium_pct" in df.columns and "premium_pb" not in df.columns:
        df["premium_pb"] = 1 + pd.to_numeric(df["premium_pct"], errors="coerce") / 100
    if "premium_pb" not in df.columns:
        df["premium_pb"] = 1.0
    return df


def fetch_akshare_prices(cfg: ProjectConfig, start: str, end: str) -> tuple[Path | None, list[str]]:
    """Fetch ETF history via AKShare and write the real-data price cache.

    The function returns a tuple of ``(cache_path, errors)``. It does not raise
    for provider failures so the CLI can give a clear offline fallback message.
    """
    try:
        import akshare  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on optional install
        return None, [f"AKShare import failed: {exc}"]

    pools = cfg.data.get("fetch_pools", ["broad_etf"])
    symbols = load_universe(cfg.universe, pools=pools)
    start_ts = parse_date(start)
    end_ts = parse_date(end, latest=date.today())
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    timeout_seconds = int(cfg.data.get("fetch_timeout_seconds", 20))

    for symbol in symbols:
        try:
            normalized = fetch_eastmoney_prices(symbol, yyyymmdd(start_ts), yyyymmdd(end_ts), timeout_seconds)
            if normalized.empty:
                errors.append(f"{symbol.code} {symbol.name}: empty response")
                continue
            frames.append(normalized)
        except Exception as direct_exc:  # pragma: no cover - network/provider dependent
            try:
                raw = _fetch_akshare_raw_with_timeout(symbol, yyyymmdd(start_ts), yyyymmdd(end_ts), timeout_seconds)
                normalized = normalize_price_frame(raw, symbol)
                if normalized.empty:
                    errors.append(f"{symbol.code} {symbol.name}: empty response after Eastmoney error {direct_exc}")
                    continue
                frames.append(normalized)
            except Exception as ak_exc:
                errors.append(f"{symbol.code} {symbol.name}: Eastmoney {direct_exc}; AKShare {ak_exc}")

    if not frames:
        return None, errors or ["No data fetched from AKShare."]

    prices = pd.concat(frames, ignore_index=True).sort_values(["date", "code"])
    ensure_dir(cfg.price_cache.parent)
    prices.to_parquet(cfg.price_cache, index=False)
    return cfg.price_cache, errors


def filter_prices(prices: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Filter prices by inclusive date bounds."""
    df = prices.copy()
    if start:
        start_ts = parse_date(start)
        df = df[df["date"] >= start_ts]
    if end and str(end).lower() != "latest":
        end_ts = parse_date(end)
        df = df[df["date"] <= end_ts]
    return df.sort_values(["date", "code"]).reset_index(drop=True)
