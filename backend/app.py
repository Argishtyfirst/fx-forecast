"""Vercel entrypoint. The Python runtime serves the FastAPI `app` found here (see
[tool.vercel] in pyproject.toml); locally, run `uv run fxf serve` instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fxf.api.main import app  # noqa: E402

__all__ = ["app"]
