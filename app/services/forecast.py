"""Damped-trend exponential smoothing forecasts for the P&L."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.datasets import Dataset
from app.services.metrics import monthly_pnl

_ALPHAS = np.linspace(0.1, 0.9, 9)
_BETAS = np.linspace(0.05, 0.5, 10)


def _holt_fit(y: np.ndarray, alpha: float, beta: float, phi: float):
    level, trend = y[0], y[1] - y[0]
    fitted = np.empty_like(y)
    fitted[0] = y[0]
    for t in range(1, len(y)):
        forecast = level + phi * trend
        fitted[t] = forecast
        new_level = alpha * y[t] + (1 - alpha) * forecast
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return level, trend, fitted


def holt_forecast(values, horizon: int, phi: float = 0.98) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (point forecast, lower 95%, upper 95%). Parameters chosen by grid search on one-step SSE."""
    y = np.asarray(values, dtype=float)
    if len(y) < 3:
        flat = np.full(horizon, y[-1] if len(y) else 0.0)
        return flat, flat, flat
    best = None
    for a in _ALPHAS:
        for b in _BETAS:
            level, trend, fitted = _holt_fit(y, a, b, phi)
            sse = float(((y[1:] - fitted[1:]) ** 2).sum())
            if best is None or sse < best[0]:
                best = (sse, level, trend, fitted)
    _, level, trend, fitted = best
    steps = np.arange(1, horizon + 1)
    point = level + np.cumsum(phi**steps) * trend
    resid = y[1:] - fitted[1:]
    sigma = float(resid.std(ddof=1)) if len(resid) > 1 else 0.0
    width = 1.96 * sigma * np.sqrt(steps)
    return point, point - width, point + width


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])))


def forecast_pnl(ds: Dataset, horizon: int = 12) -> dict | None:
    pnl = monthly_pnl(ds)
    if len(pnl) < 6:
        return None
    future = pd.date_range(pnl.index[-1] + pd.DateOffset(months=1), periods=horizon, freq="MS")
    rev, rev_lo, rev_hi = holt_forecast(pnl["revenue"], horizon)
    cogs, _, _ = holt_forecast(pnl["cogs"], horizon)
    opex, _, _ = holt_forecast(pnl["opex"], horizon)
    rev = np.clip(rev, 0, None)
    rev_lo = np.clip(rev_lo, 0, None)
    rev_hi = np.maximum(np.clip(rev_hi, 0, None), rev)
    cogs = np.clip(cogs, 0, None)
    opex = np.clip(opex, 0, None)
    gross_profit = rev - cogs
    operating_income = gross_profit - opex

    forecast = pd.DataFrame(
        {
            "month": future,
            "revenue": rev,
            "revenue_lower": rev_lo,
            "revenue_upper": rev_hi,
            "cogs": cogs,
            "opex": opex,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "gross_margin": np.where(rev != 0, gross_profit / np.where(rev != 0, rev, 1), np.nan),
        }
    )
    history = pnl[["revenue", "cogs", "opex", "gross_profit", "operating_income", "gross_margin"]].reset_index(
        names="month"
    )

    backtest = None
    holdout = 3
    if len(pnl) >= 12:
        y = pnl["revenue"].to_numpy()
        predicted, _, _ = holt_forecast(y[:-holdout], holdout)
        backtest = _mape(y[-holdout:], predicted)

    return {
        "method": "Damped Holt exponential smoothing (level + trend), 95% prediction interval",
        "history": history,
        "forecast": forecast,
        "summary": {
            "horizon_months": horizon,
            "revenue": float(rev.sum()),
            "gross_profit": float(gross_profit.sum()),
            "operating_income": float(operating_income.sum()),
            "exit_arr": float(rev[-1] * 12),
            "backtest_mape_3m": backtest,
        },
    }
