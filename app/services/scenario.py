"""Driver-based what-if simulation of MRR, gross profit and operating income."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.datasets import Dataset
from app.services.metrics import monthly_pnl, mrr_bridge, ratio


def baseline_drivers(ds: Dataset, window: int = 6) -> dict:
    bridge = mrr_bridge(ds).tail(window)
    pnl = monthly_pnl(ds).tail(window)
    start = bridge["starting_mrr"].replace(0, np.nan)
    revenue = float(pnl["revenue"].sum())
    churn = (-(bridge["churn"] + bridge["contraction"]) / start).mean()
    expansion = ((bridge["expansion"] + bridge["reactivation"]) / start).mean()
    return {
        "monthly_churn_rate": 0.0 if pd.isna(churn) else float(churn),
        "monthly_expansion_rate": 0.0 if pd.isna(expansion) else float(expansion),
        "new_mrr_per_month": float(bridge["new"].mean()) if len(bridge) else 0.0,
        "hosting_ratio": ratio(pnl["hosting"].sum(), revenue) or 0.0,
        "other_cogs_ratio": ratio((pnl["cogs"] - pnl["hosting"]).sum(), revenue) or 0.0,
        "monthly_opex": float(pnl["opex"].tail(3).mean()),
        "window_months": len(bridge),
    }


def _simulate(start_mrr, drivers, months, future, price=0.0, churn_mult=1.0, new_mult=1.0, hosting_mult=1.0, opex_mult=1.0):
    # Volume is MRR at today's prices; price changes scale revenue but not cost-to-serve.
    volume = start_mrr
    rows = []
    for month in future[:months]:
        volume = (
            volume * (1 - drivers["monthly_churn_rate"] * churn_mult + drivers["monthly_expansion_rate"])
            + drivers["new_mrr_per_month"] * new_mult
        )
        revenue = volume * (1 + price)
        cogs = volume * (drivers["hosting_ratio"] * hosting_mult + drivers["other_cogs_ratio"])
        opex = drivers["monthly_opex"] * opex_mult
        gross_profit = revenue - cogs
        rows.append(
            {
                "month": month,
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": gross_profit,
                "opex": opex,
                "operating_income": gross_profit - opex,
            }
        )
    return pd.DataFrame(rows)


def run_scenario(
    ds: Dataset,
    price_change_pct: float = 0.0,
    churn_change_pct: float = 0.0,
    new_business_change_pct: float = 0.0,
    hosting_cost_change_pct: float = 0.0,
    opex_change_pct: float = 0.0,
    months: int = 12,
) -> dict:
    pnl = monthly_pnl(ds)
    drivers = baseline_drivers(ds)
    start_mrr = float(pnl["revenue"].iloc[-1])
    future = pd.date_range(pnl.index[-1] + pd.DateOffset(months=1), periods=months, freq="MS")

    baseline = _simulate(start_mrr, drivers, months, future)
    scenario = _simulate(
        start_mrr,
        drivers,
        months,
        future,
        price=price_change_pct / 100,
        churn_mult=1 + churn_change_pct / 100,
        new_mult=1 + new_business_change_pct / 100,
        hosting_mult=1 + hosting_cost_change_pct / 100,
        opex_mult=1 + opex_change_pct / 100,
    )

    def totals(df: pd.DataFrame) -> dict:
        rev = float(df["revenue"].sum())
        gp = float(df["gross_profit"].sum())
        oi = float(df["operating_income"].sum())
        return {
            "revenue": rev,
            "gross_profit": gp,
            "operating_income": oi,
            "gross_margin": ratio(gp, rev),
            "operating_margin": ratio(oi, rev),
            "exit_arr": float(df["revenue"].iloc[-1] * 12),
        }

    base_t, scen_t = totals(baseline), totals(scenario)
    delta = {k: (scen_t[k] - base_t[k]) if base_t[k] is not None and scen_t[k] is not None else None for k in base_t}
    return {
        "drivers": drivers,
        "assumptions": [
            "Price changes apply to all MRR from the first month; combine with a churn change to model price sensitivity.",
            "Churn and new-business changes are relative to the trailing 6-month run rate.",
            "Cost-to-serve scales with usage volume, not price.",
        ],
        "baseline": baseline,
        "scenario": scenario,
        "totals": {"baseline": base_t, "scenario": scen_t, "delta": delta},
    }
