"""The API runs on Vercel, whose runtime lacks libgomp: it must never import the model stack."""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
HEAVY = ("lightgbm", "arch", "statsmodels")


def test_api_entrypoint_does_not_import_model_libraries():
    code = f"import sys; import app; print(','.join(m for m in {HEAVY!r} if m in sys.modules))"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "", f"API imported: {out.stdout.strip()}"
