"""Local source-layout shim for ``python -m etf_rotation.cli``.

The real package lives under ``src/etf_rotation``. This small shim appends that
directory to the package search path so commands work from the project root
without requiring an editable install first.
"""

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "etf_rotation"
if _SRC_PACKAGE.exists():
    __path__.append(str(_SRC_PACKAGE))  # type: ignore[name-defined]

__version__ = "0.1.0"
