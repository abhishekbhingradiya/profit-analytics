from datetime import date

import pandas as pd
import pytest

from app.services.datasets import build_dataset
from app.services.forecast import forecast_pnl, holt_forecast
from app.services.metrics import customer_profitability, kpis, monthly_pnl, mrr_bridge, profitability_by, retention
from app.services.scenario import run_scenario


def sample_dataset():
    customers = pd.DataFrame(
        [
            {"customer_id": 1, "external_id": "A", "name": "Alpha", "segment": "SMB", "region": "NA", "industry": "Software", "channel": "Direct", "signup_month": date(2025, 2, 1)},
            {"customer_id": 2, "external_id": "B", "name": "Beta", "segment": "Enterprise", "region": "EU", "industry": "Finance", "channel": "Partner", "signup_month": date(2025, 1, 1)},
        ]
    )
    revenue = pd.DataFrame(
        [
            {"customer_id": 2, "month": date(2025, 1, 1), "plan": "Scale", "list_mrr": 220, "mrr": 200},
            {"customer_id": 1, "month": date(2025, 2, 1), "plan": "Starter", "list_mrr": 110, "mrr": 100},
            {"customer_id": 2, "month": date(2025, 2, 1), "plan": "Scale", "list_mrr": 220, "mrr": 200},
            {"customer_id": 1, "month": date(2025, 3, 1), "plan": "Starter", "list_mrr": 110, "mrr": 120},
            {"customer_id": 2, "month": date(2025, 3, 1), "plan": "Scale", "list_mrr": 220, "mrr": 180},
            {"customer_id": 2, "month": date(2025, 4, 1), "plan": "Scale", "list_mrr": 220, "mrr": 190},
            {"customer_id": 1, "month": date(2025, 5, 1), "plan": "Starter", "list_mrr": 110, "mrr": 130},
            {"customer_id": 2, "month": date(2025, 5, 1), "plan": "Scale", "list_mrr": 220, "mrr": 190},
            {"customer_id": 1, "month": date(2025, 6, 1), "plan": "Starter", "list_mrr": 110, "mrr": 132},
            {"customer_id": 2, "month": date(2025, 6, 1), "plan": "Scale", "list_mrr": 220, "mrr": 195},
            {"customer_id": 1, "month": date(2025, 7, 1), "plan": "Starter", "list_mrr": 110, "mrr": 134},
            {"customer_id": 2, "month": date(2025, 7, 1), "plan": "Scale", "list_mrr": 220, "mrr": 198},
            {"customer_id": 1, "month": date(2025, 8, 1), "plan": "Starter", "list_mrr": 110, "mrr": 136},
            {"customer_id": 2, "month": date(2025, 8, 1), "plan": "Scale", "list_mrr": 220, "mrr": 200},
            {"customer_id": 1, "month": date(2025, 9, 1), "plan": "Starter", "list_mrr": 110, "mrr": 138},
            {"customer_id": 2, "month": date(2025, 9, 1), "plan": "Scale", "list_mrr": 220, "mrr": 205},
            {"customer_id": 1, "month": date(2025, 10, 1), "plan": "Starter", "list_mrr": 110, "mrr": 140},
            {"customer_id": 2, "month": date(2025, 10, 1), "plan": "Scale", "list_mrr": 220, "mrr": 210},
            {"customer_id": 1, "month": date(2025, 11, 1), "plan": "Starter", "list_mrr": 110, "mrr": 142},
            {"customer_id": 2, "month": date(2025, 11, 1), "plan": "Scale", "list_mrr": 220, "mrr": 215},
            {"customer_id": 1, "month": date(2025, 12, 1), "plan": "Starter", "list_mrr": 110, "mrr": 145},
            {"customer_id": 2, "month": date(2025, 12, 1), "plan": "Scale", "list_mrr": 220, "mrr": 220},
        ]
    )
    costs = pd.DataFrame(
        [
            {"month": date(2025, month, 1), "category": "hosting", "customer_id": pd.NA, "amount": 30}
            for month in range(1, 13)
        ]
        + [
            {"month": date(2025, month, 1), "category": "sales", "customer_id": pd.NA, "amount": 50}
            for month in range(1, 13)
        ]
    )
    return build_dataset(customers, revenue, costs)


def test_monthly_pnl_reconciles_gross_profit():
    pnl = monthly_pnl(sample_dataset())
    assert pnl.iloc[-1].revenue == 365
    assert pnl.iloc[-1].cogs == 30
    assert pnl.iloc[-1].gross_profit == 335
    assert pnl.iloc[-1].gross_margin == pytest.approx(335 / 365)


def test_mrr_bridge_reconciles_monthly_change():
    bridge = mrr_bridge(sample_dataset())
    assert (bridge.ending_mrr - bridge.starting_mrr).to_numpy() == pytest.approx(bridge.net_new_mrr.to_numpy())
    assert bridge.iloc[1].contraction == -20
    assert bridge.iloc[-1].expansion > 0


def test_shared_cogs_allocates_in_proportion_to_revenue():
    cp = customer_profitability(sample_dataset(), months=12).set_index("external_id")
    assert cp.loc["A", "allocated_cogs"] / cp.loc["B", "allocated_cogs"] == pytest.approx(
        cp.loc["A", "revenue"] / cp.loc["B", "revenue"]
    )
    by_segment = profitability_by(sample_dataset(), "segment")
    assert by_segment.revenue.sum() == pytest.approx(cp.revenue.sum())
    assert by_segment.allocated_cogs.sum() == pytest.approx(cp.allocated_cogs.sum())


def test_kpis_and_retention_are_bounded_for_retained_accounts():
    ds = sample_dataset()
    metrics = kpis(ds)
    assert metrics["mrr"] == 365
    assert metrics["active_customers"] == 2
    assert retention(ds)["grr"] <= retention(ds)["nrr"]


def test_forecast_and_scenario_have_finite_nonnegative_revenue():
    ds = sample_dataset()
    result = forecast_pnl(ds, horizon=6)
    assert result is not None
    assert (result["forecast"]["revenue"] >= 0).all()
    scenario = run_scenario(ds, price_change_pct=5, months=6)
    assert (scenario["scenario"]["revenue"] >= scenario["baseline"]["revenue"]).all()
    assert scenario["totals"]["scenario"]["revenue"] > scenario["totals"]["baseline"]["revenue"]


def test_holt_forecast_returns_requested_horizon_and_ordered_bounds():
    point, lower, upper = holt_forecast([100, 110, 120, 130], 8)
    assert len(point) == len(lower) == len(upper) == 8
    assert (lower <= point).all()
    assert (point <= upper).all()
