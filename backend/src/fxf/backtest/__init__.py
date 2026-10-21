"""Walk-forward backtest (FR-13). Entry points: run_backtest, run_backtest_job.

The entry points load lazily, so importing fxf.backtest.metrics (numpy and scipy only, as
the API's AI track record does) never pulls in the model stack (LightGBM needs libgomp,
which the Vercel runtime lacks).
"""

from typing import Any

__all__ = ["backtest", "run_backtest", "run_backtest_job"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from fxf.backtest import runner

        return getattr(runner, name)
    raise AttributeError(f"module 'fxf.backtest' has no attribute {name!r}")
