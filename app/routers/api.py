from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user, require_role, verify_csrf
from app.services.anomalies import detect_anomalies
from app.services.datasets import dataset_status, has_data, load_dataset
from app.services.forecast import forecast_pnl
from app.services.insights import explain_change
from app.services.metrics import (
    DIMENSIONS,
    cohort_retention,
    customer_profitability,
    kpis,
    monthly_pnl,
    mrr_bridge,
    profitability_by,
    retention,
    unit_economics,
)
from app.services.scenario import run_scenario
from app.services.serialize import clean, records

router = APIRouter(prefix="/api", tags=["analytics"])


def _dataset(db: Session, user: User):
    if not has_data(db, user.org_id):
        raise HTTPException(status_code=404, detail="No data yet. Upload your SaaS CSVs or load sample data.")
    return load_dataset(db, user.org_id)


@router.get("/data-status")
def data_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dataset_status(db, user.org_id)


@router.get("/kpis")
def get_kpis(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return clean(kpis(_dataset(db, user)))


@router.get("/pnl")
def get_pnl(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return records(monthly_pnl(_dataset(db, user)).reset_index())


@router.get("/mrr-bridge")
def get_bridge(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return records(mrr_bridge(_dataset(db, user)).reset_index())


@router.get("/profitability")
def get_profitability(
    dimension: str = Query("segment", pattern="^(segment|region|industry|channel|plan)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return records(profitability_by(_dataset(db, user), dimension=dimension))


@router.get("/customers")
def get_customers(
    sort: str = Query("gross_profit", pattern="^(gross_profit|revenue|gross_margin|discount_rate)$"),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cp = customer_profitability(_dataset(db, user)).sort_values(sort, ascending=sort != "revenue")
    return records(cp.head(limit))


@router.get("/retention")
def get_retention(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ds = _dataset(db, user)
    return {"summary": clean(retention(ds)), "cohorts": clean(cohort_retention(ds))}


@router.get("/unit-economics")
def get_unit_economics(
    by: str | None = Query(None, pattern="^(segment|region|industry|channel|plan)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return clean(unit_economics(_dataset(db, user), by=by))


@router.get("/forecast")
def get_forecast(
    horizon: int = Query(12, ge=3, le=24), user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    result = forecast_pnl(_dataset(db, user), horizon)
    if result is None:
        raise HTTPException(status_code=422, detail="Forecasting needs at least 6 months of revenue history.")
    return clean(result)


@router.get("/anomalies")
def get_anomalies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return clean(detect_anomalies(_dataset(db, user)))


@router.get("/insights")
def get_insights(
    period_months: int = Query(1, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = explain_change(_dataset(db, user), period_months)
    if result is None:
        raise HTTPException(status_code=422, detail="There is not enough history to compare these periods.")
    return clean(result)


class ScenarioInput(BaseModel):
    price_change_pct: float = Field(default=0, ge=-50, le=100)
    churn_change_pct: float = Field(default=0, ge=-90, le=500)
    new_business_change_pct: float = Field(default=0, ge=-100, le=500)
    hosting_cost_change_pct: float = Field(default=0, ge=-90, le=500)
    opex_change_pct: float = Field(default=0, ge=-90, le=500)
    months: int = Field(default=12, ge=3, le=24)


@router.post("/scenarios", dependencies=[Depends(verify_csrf)])
def post_scenario(
    inputs: ScenarioInput,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
):
    return clean(run_scenario(_dataset(db, user), **inputs.model_dump()))


class CopilotInput(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("/copilot", dependencies=[Depends(verify_csrf)])
def copilot(
    inputs: CopilotInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Intent-routed metrics assistant; never executes model-generated SQL."""
    ds = _dataset(db, user)
    q = inputs.question.casefold()
    if any(term in q for term in ("cohort", "retention", "nrr", "grr")):
        return {
            "answer": "Retention is calculated from observed monthly recurring revenue. Cohort values are relative to each cohort's starting MRR.",
            "data": clean({"summary": retention(ds), "cohorts": cohort_retention(ds)}),
            "source": "Monthly revenue records",
        }
    if any(term in q for term in ("cac", "ltv", "payback", "acquisition")):
        return {
            "answer": "Unit economics use trailing six-month sales and marketing costs, new MRR, observed churn, and gross margin. Treat these as directional when cost attribution is incomplete.",
            "data": clean(unit_economics(ds)),
            "source": "Revenue, direct cost and sales/marketing records",
        }
    if any(term in q for term in ("forecast", "predict", "next", "future")):
        result = forecast_pnl(ds)
        if result is None:
            raise HTTPException(status_code=422, detail="Forecasting needs at least 6 months of history.")
        return {"answer": "A 12-month damped-trend forecast is shown below. It is a statistical baseline, not a causal prediction.", "data": clean(result), "source": result["method"]}
    match = re.search(r"(?:by|per|across)\s+(segment|region|industry|channel|plan)", q)
    if match and any(term in q for term in ("profit", "margin", "revenue", "cost")):
        dimension = match.group(1)
        return {
            "answer": f"Profitability is grouped by {dimension}; shared COGS is allocated in proportion to revenue.",
            "data": records(profitability_by(ds, dimension)),
            "source": "Revenue and cost records (trailing 12 months)",
        }
    if any(term in q for term in ("why", "changed", "change", "driver", "margin", "profit")):
        result = explain_change(ds)
        return {"answer": "The comparison below decomposes gross-profit change into revenue and cost drivers.", "data": clean(result), "source": "Price/volume changes in MRR and recorded COGS"}
    if any(term in q for term in ("alert", "anomal", "leak", "discount")):
        result = detect_anomalies(ds)
        return {"answer": f"Found {len(result)} current anomaly and profitability-leakage signals. Review the impact estimates before taking action.", "data": clean(result), "source": "Robust time-series outliers and account-level costs"}
    if match:
        dimension = match.group(1)
        return {
            "answer": f"Profitability is grouped by {dimension}; shared COGS is allocated in proportion to revenue.",
            "data": records(profitability_by(ds, dimension)),
            "source": "Revenue and cost records (trailing 12 months)",
        }
    return {
        "answer": "I can answer about profit drivers, segment/region/plan profitability, forecasts, retention and unit economics. I will not invent a query for unsupported questions.",
        "data": clean({"kpis": kpis(ds), "supported_dimensions": DIMENSIONS}),
        "source": "Tenant's monthly revenue and cost data",
    }
