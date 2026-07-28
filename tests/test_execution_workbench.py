from __future__ import annotations

import pandas as pd

from etf_rotation.execution_workbench import build_trade_orders
from etf_rotation.universe import ETF


def test_build_trade_orders_generates_buy_sell_hold_rows() -> None:
    code_map = {
        "A": ETF(name="Alpha", code="A"),
        "B": ETF(name="Beta", code="B"),
        "C": ETF(name="Gamma", code="C"),
    }
    risk_table = pd.DataFrame(
        [
            {
                "code": "A",
                "name": "Alpha",
                "momentum_rank": 1,
                "trend": "↗",
                "risk_reason": "OK",
                "qdii": False,
            },
            {
                "code": "B",
                "name": "Beta",
                "momentum_rank": 2,
                "trend": "↘",
                "risk_reason": "OVERHEAT",
                "qdii": False,
            },
            {
                "code": "C",
                "name": "Gamma",
                "momentum_rank": 3,
                "trend": "↗",
                "risk_reason": "OK",
                "qdii": True,
            },
        ]
    )

    orders = build_trade_orders(
        signal_date="2026-06-26",
        current_holdings=["A", "B"],
        target_holdings=["A", "C"],
        risk_table=risk_table,
        code_map=code_map,
        confidence_score=1.2,
    )
    by_symbol = {item.symbol: item for item in orders}

    assert by_symbol["A"].action == "HOLD"
    assert by_symbol["B"].action == "SELL"
    assert by_symbol["B"].risk_flag == "OVERHEAT"
    assert by_symbol["C"].action == "BUY"
    assert by_symbol["C"].risk_flag == "QDII"
