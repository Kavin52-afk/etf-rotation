"""Wrapper for `python -m etf_rotation.cli calibrate`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etf_rotation.cli import app


if __name__ == "__main__":
    app()
