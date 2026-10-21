"""LightGBM center model: one regressor per pair and horizon on the h-day log return.

Deterministic by construction (NFR-02): fixed seed (settings.random_seed), deterministic=True,
force_row_wise=True and num_threads=1. Missing features (NaN) are handled natively, so the
model still trains when a macro series or the meeting calendar is unavailable for a period.
"""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np

NUM_BOOST_ROUND = 200
BASE_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbose": -1,
}


def lgbm_params(seed: int) -> dict[str, Any]:
    return {**BASE_PARAMS, "seed": seed}


def train(X: np.ndarray, y: np.ndarray, seed: int, feature_names: list[str]) -> lgb.Booster:
    ds = lgb.Dataset(
        np.asarray(X, dtype="float64"),
        label=np.asarray(y, dtype="float64"),
        feature_name=feature_names,
        free_raw_data=True,
    )
    return lgb.train(lgbm_params(seed), ds, num_boost_round=NUM_BOOST_ROUND)


def predict(booster: lgb.Booster, X: np.ndarray) -> np.ndarray:
    return np.asarray(booster.predict(np.asarray(X, dtype="float64")), dtype="float64")
