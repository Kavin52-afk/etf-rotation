"""Typer CLI for the ETF rotation research project."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .backtest import run_backtest
from .calibration import run_calibration, run_layered_calibration
from .config import load_project_config
from .counterfactual_analysis import run_counterfactual_analysis
from .data_provider import fetch_akshare_prices, init_sample_data, load_prices
from .execution_workbench import (
    finalize_execution,
    generate_trade_sheet,
    review_executions,
    summarize_trade_sheet,
)
from .parser_docx import copy_default_doc_if_available, parse_docx_file
from .realworld_execution import run_paper_trading
from .report import generate_daily_report
from .source_attribution import run_source_attribution

app = typer.Typer(
    help="ETF rotation research CLI. Generates signals, backtests, and reports only; no live trading.",
    no_args_is_help=True,
)
console = Console()


@app.command("init-sample")
def init_sample() -> None:
    """Generate deterministic synthetic ETF daily data for offline runs."""
    cfg = load_project_config()
    path = init_sample_data(cfg)
    copied = copy_default_doc_if_available(cfg)
    console.print(f"[green]Sample price data written:[/green] {path}")
    if copied:
        console.print(f"[green]DOCX source copied/found:[/green] {copied}")
    else:
        console.print("[yellow]No /mnt/data/股票策略etf.docx found. You can place it under data/raw/ manually.[/yellow]")


@app.command("fetch")
def fetch(
    start: str = typer.Option("2020-01-01", help="Start date, e.g. 2020-01-01."),
    end: str = typer.Option("latest", help="End date or latest."),
) -> None:
    """Fetch real ETF historical daily prices via AKShare."""
    cfg = load_project_config()
    path, errors = fetch_akshare_prices(cfg, start=start, end=end)
    if path:
        console.print(f"[green]Fetched price cache written:[/green] {path}")
        if errors:
            console.print("[yellow]Some symbols failed. The cache contains successfully fetched symbols.[/yellow]")
            for item in errors[:20]:
                console.print(f"- {item}")
    else:
        console.print("[red]AKShare fetch did not produce a usable cache.[/red]")
        for item in errors[:30]:
            console.print(f"- {item}")
        console.print("[yellow]You can run `python -m etf_rotation.cli init-sample` first and continue with --sample.[/yellow]")


@app.command("daily")
def daily(
    date: str = typer.Option("latest", help="Report date or latest."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
    execution_stability: bool = typer.Option(
        True,
        "--execution-stability/--no-execution-stability",
        help="Use frozen-signal/debounce execution overlay.",
    ),
) -> None:
    """Run the daily strategy and write markdown/csv reports."""
    cfg = load_project_config()
    prices = load_prices(cfg, sample=sample)
    paths = generate_daily_report(
        prices,
        cfg,
        report_date=date,
        sample=sample,
        execution_stability=execution_stability,
    )
    console.print(f"[green]Daily markdown written:[/green] {paths['markdown']}")
    console.print(f"[green]Daily CSV written:[/green] {paths['csv']}")


@app.command("backtest")
def backtest(
    start: Optional[str] = typer.Option(None, help="Start date, e.g. 2021-01-01."),
    end: str = typer.Option("latest", help="End date or latest."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
) -> None:
    """Run the ETF rotation backtest and write reports."""
    cfg = load_project_config()
    prices = load_prices(cfg, sample=sample)
    result = run_backtest(prices, cfg, start=start, end=end, write_reports=True)
    console.print("[green]Backtest finished.[/green]")
    for key, path in result.paths.items():
        console.print(f"- {key}: {path}")


@app.command("parse-doc")
def parse_doc(
    doc: Path = typer.Option(Path("data/raw/股票策略etf.docx"), help="Source DOCX path."),
) -> None:
    """Parse source strategy DOCX labels and row data."""
    cfg = load_project_config()
    path = doc if doc.is_absolute() else cfg.project_root / doc
    if not path.exists():
        copied = copy_default_doc_if_available(cfg)
        if copied:
            path = copied
    if not path.exists():
        console.print(f"[red]DOCX file not found:[/red] {path}")
        console.print("Place 股票策略etf.docx under data/raw/ and rerun this command.")
        raise typer.Exit(code=1)
    label_path, row_path = parse_docx_file(path, cfg)
    console.print(f"[green]Labels written:[/green] {label_path}")
    console.print(f"[green]Rows written:[/green] {row_path}")


@app.command("calibrate")
def calibrate(
    labels: Path = typer.Option(Path("data/labels/doc_labels.csv"), help="Parsed label CSV."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
    mode: str = typer.Option("default", help="Calibration mode: default or layered."),
) -> None:
    """Compare generated target holdings with parsed source-document labels."""
    cfg = load_project_config()
    label_path = labels if labels.is_absolute() else cfg.project_root / labels
    prices = load_prices(cfg, sample=sample)
    note = "未使用真实行情，当前 calibration 使用 synthetic sample data 仅验证流程。" if sample else ""
    if mode == "default":
        output = run_calibration(label_path, prices, cfg, data_note=note)
    elif mode == "layered":
        output = run_layered_calibration(label_path, prices, cfg, data_note=note)
    else:
        console.print(f"[red]Unsupported calibration mode:[/red] {mode}. Use default or layered.")
        raise typer.Exit(code=2)
    console.print(f"[green]Calibration report written:[/green] {output}")


@app.command("counterfactual")
def counterfactual(
    labels: Path = typer.Option(Path("data/labels/doc_labels.csv"), help="Parsed label CSV."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
) -> None:
    """Run structure-only counterfactual ablations against parsed source-document labels."""
    cfg = load_project_config()
    label_path = labels if labels.is_absolute() else cfg.project_root / labels
    prices = load_prices(cfg, sample=sample)
    note = "未使用真实行情，当前 counterfactual 使用 synthetic sample data 仅验证流程。" if sample else ""
    output = run_counterfactual_analysis(label_path, prices, cfg, data_note=note)
    console.print(f"[green]Counterfactual report written:[/green] {output}")


@app.command("source-attribution")
def source_attribution() -> None:
    """Run structure-only source attribution for the current strategy."""
    cfg = load_project_config()
    output = run_source_attribution(cfg)
    console.print(f"[green]Source attribution report written:[/green] {output}")


@app.command("paper-trade")
def paper_trade(
    days: int = typer.Option(30, help="Number of recent trading days to simulate."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
) -> None:
    """Simulate frozen T+1 paper trading without changing the backtest."""
    cfg = load_project_config()
    prices = load_prices(cfg, sample=sample)
    output = run_paper_trading(prices, cfg, days=days)
    console.print(f"[green]Paper-trade report written:[/green] {output}")


@app.command("trade-sheet")
def trade_sheet(
    date: str = typer.Option("latest", help="Signal date or latest."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
) -> None:
    """Generate a human-reviewable trade sheet and daily risk notice."""
    cfg = load_project_config()
    prices = load_prices(cfg, sample=sample)
    result = generate_trade_sheet(prices, cfg, date=date)
    console.print(summarize_trade_sheet(result))


@app.command("execute")
def execute(
    date: str = typer.Option("latest", help="Signal date or latest."),
    sample: bool = typer.Option(False, help="Use synthetic sample data."),
) -> None:
    """Run manual confirmation workflow for a generated trade sheet."""
    cfg = load_project_config()
    prices = load_prices(cfg, sample=sample)
    result = generate_trade_sheet(prices, cfg, date=date)
    console.print(summarize_trade_sheet(result))
    if result.status == "executed":
        console.print("[yellow]This signal is already marked executed. No duplicate execution is allowed.[/yellow]")
        return
    answer = typer.prompt("Type YES to mark manually executed, or NO to reject the signal")
    record = finalize_execution(cfg, result, answer)
    console.print(f"[green]Manual execution status recorded:[/green] {record['status']}")


@app.command("review")
def review(
    start: str = typer.Option("2026-01-01", help="Start signal date."),
    end: str = typer.Option("latest", help="End signal date or latest."),
) -> None:
    """Review past manual execution decisions."""
    cfg = load_project_config()
    frame = review_executions(cfg, start=start, end=end)
    if frame.empty:
        console.print("[yellow]No execution log rows found.[/yellow]")
        return
    columns = [
        col
        for col in [
            "signal_date",
            "execution_id",
            "status",
            "decision_latency",
            "executed_signals",
            "rejected_signals",
            "trade_sheet",
        ]
        if col in frame.columns
    ]
    console.print(frame[columns].to_string(index=False))


if __name__ == "__main__":
    app()
