from __future__ import annotations

from etf_rotation.data_provider import eastmoney_secid_for_symbol
from etf_rotation.universe import ETF


def test_explicit_eastmoney_secid_is_used_for_index_symbols() -> None:
    symbol = ETF(name="中证2000", code="932000.CSI", kind="index", secid="2.932000")

    assert eastmoney_secid_for_symbol(symbol) == "2.932000"

