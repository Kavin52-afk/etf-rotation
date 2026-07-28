from __future__ import annotations

import json

from etf_rotation.parser_docx import parse_doc_text
from etf_rotation.universe import ETF


def test_parse_doc_text_labels_and_rows_multi_section() -> None:
    text = """
您好！今天是 2024-06-28
大类 ETF 截至昨日强弱排序：
昨日收盘组合持仓['日经 225', '纳指']
今日收盘组合应持仓['日经225', '科创 50']
单品种近20日表现:[涨幅%，乖离率%，现趋势，多空信号，趋势凹凸，净值，上次信号，盈利%，最新信号]
√√√日经225PB1.06:[22.4, 9.5, '↗', '-', '↘', 1.6, '0415_B', 28.5, '-']
××√科创50PB1.00:[9.3, 9.5, '↗', '★', '↗', 1.8, '0618_B', '-', '0628_B']
今日买入信号：159338.SZ(中证 A500)
今日卖出信号：-
行业 ETF 截至昨日强弱排序：
今天是 2024-06-27
大类 ETF 截至昨日强弱排序：
等待数据更新
行业 ETF 截至昨日强弱排序：
"""
    symbols = [ETF("日经225", "513520.SH"), ETF("纳指", "513100.SH"), ETF("科创50", "588000.SH")]
    labels, rows = parse_doc_text(text, symbols)
    assert len(labels) == 2
    active = labels[labels["date"].eq("2024-06-28")].iloc[0]
    waiting = labels[labels["date"].eq("2024-06-27")].iloc[0]
    assert json.loads(active["target_holdings"]) == ["日经225", "科创50"]
    assert json.loads(active["added_names"]) == ["科创50"]
    assert json.loads(active["removed_names"]) == ["纳指"]
    assert json.loads(active["buy_signals"]) == [{"code": "159338.SZ", "name": "中证A500"}]
    assert waiting["broad_valid"] == False
    assert json.loads(waiting["target_holdings"]) == []
    assert len(rows) == 2
    assert rows.loc[0, "name"] == "日经225"
    assert rows.loc[1, "code_if_found"] == "588000.SH"
    assert rows.loc[1, "latest_signal"] == "0628_B"
