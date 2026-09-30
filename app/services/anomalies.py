"""Detects unusual movements in revenue and costs, plus customer-level margin leakage."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.datasets import Dataset
from app.services.formatting import money
from app.services.metrics import ALL_CATEGORIES, CATEGORY_LABELS, customer_profitability, monthly_pnl

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def robust_z(values: np.ndarray) -> np.ndarray:
    med = np.median(values)
    scale = 1.4826 * np.median(np.abs(values - med))
    if scale == 0:
        scale = values.std()
    if scale == 0:
        return np.zeros_like(values)
    return (values - med) / scale


def _metric_anomalies(pnl: pd.DataFrame, threshold: float, recent: pd.DatetimeIndex) -> list[dict]:
    findings = []
    series = {"revenue": pnl["revenue"]}
    series.update({c: pnl[c] for c in ALL_CATEGORIES if pnl[c].abs().sum() > 0})
    for metric, s in series.items():
        change = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if len(change) < 5:
            continue
        z = robust_z(change.to_numpy())
        last_flag_sign = 0
        for month, zc, pct in zip(change.index, z, change.to_numpy()):
            sign = int(np.sign(zc))
            flagged = abs(zc) >= threshold
            # Skip the snap-back month right after a spike in the opposite direction.
            if flagged and last_flag_sign and sign == -last_flag_sign:
                last_flag_sign = 0
                continue
            last_flag_sign = sign if flagged else 0
            if not flagged or month not in recent:
                continue
            label = "Revenue" if metric == "revenue" else CATEGORY_LABELS[metric]
            prior = float(s.shift(1).loc[month])
            value = float(s.loc[month])
            impact = value - prior if metric == "revenue" else prior - value
            findings.append(
                {
                    "type": "metric_spike",
                    "severity": "high" if abs(zc) >= 2 * threshold else "medium",
                    "metric": metric,
                    "month": month,
                    "title": f"{label} {'jumped' if pct > 0 else 'dropped'} {abs(pct):.0%} in {month:%b %Y}",
                    "message": (
                        f"{label} went from {money(prior)} to {money(value)}, far outside its normal "
                        f"month-over-month range (robust z = {zc:.1f})."
                    ),
                    "value": value,
                    "impact": impact,
                }
            )
    return findings


def _margin_anomaly(pnl: pd.DataFrame, threshold: float, recent: pd.DatetimeIndex) -> list[dict]:
    gm = pnl["gross_margin"].dropna()
    diff = gm.diff().dropna()
    if len(diff) < 5:
        return []
    z = robust_z(diff.to_numpy())
    out = []
    for month, zc, d in zip(diff.index, z, diff.to_numpy()):
        if abs(zc) >= threshold and month in recent and d < 0:
            out.append(
                {
                    "type": "margin_drop",
                    "severity": "high",
                    "metric": "gross_margin",
                    "month": month,
                    "title": f"Gross margin fell {abs(d) * 100:.1f} pp in {month:%b %Y}",
                    "message": f"Gross margin was {gm.loc[month]:.1%} versus {gm.shift(1).loc[month]:.1%} the month before.",
                    "value": float(gm.loc[month]),
                    "impact": float(d * pnl.loc[month, "revenue"]),
                }
            )
    return out


def _customer_leakage(ds: Dataset) -> list[dict]:
    cp = customer_profitability(ds, months=3)
    out = []
    losers = cp[(cp["revenue"] > 0) & (cp["gross_profit"] < 0)].sort_values("gross_profit").head(10)
    for row in losers.itertuples():
        out.append(
            {
                "type": "unprofitable_customer",
                "severity": "high" if row.gross_margin < -0.25 else "medium",
                "metric": "customer_gross_profit",
                "month": None,
                "title": f"{row.name} is unprofitable",
                "message": (
                    f"{row.name} ({row.segment}, {row.region}) generated {money(row.revenue)} but cost "
                    f"{money(row.direct_cogs + row.allocated_cogs)} to serve over the last 3 months "
                    f"(margin {row.gross_margin:.0%}). Hosting: {money(row.hosting)}, support: {money(row.support)}."
                ),
                "value": float(row.gross_margin),
                "impact": float(row.gross_profit),
            }
        )

    cp = cp[cp["list_revenue"] > 0]
    seg_median = cp.groupby("segment")["discount_rate"].transform("median")
    heavy = cp[(cp["discount_rate"] >= 0.25) & (cp["discount_rate"] > seg_median + 0.12)]
    for row in heavy.sort_values("discount", ascending=False).head(10).itertuples():
        out.append(
            {
                "type": "discount_leakage",
                "severity": "medium",
                "metric": "discount_rate",
                "month": None,
                "title": f"High discount for {row.name}",
                "message": (
                    f"{row.name} ({row.segment}) receives a {row.discount_rate:.0%} discount, well above the "
                    f"segment norm. That is {money(row.discount)} of list price given away over the last 3 months."
                ),
                "value": float(row.discount_rate),
                "impact": -float(row.discount),
            }
        )
    return out


def detect_anomalies(ds: Dataset, threshold: float = 3.5, recent_months: int = 12, limit: int | None = None) -> list[dict]:
    pnl = monthly_pnl(ds)
    recent = pnl.index[-recent_months:]
    findings: list[dict] = []
    if len(pnl) >= 6:
        findings += _metric_anomalies(pnl, threshold, recent)
        findings += _margin_anomaly(pnl, threshold, recent)
    findings += _customer_leakage(ds)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], -abs(f["impact"] or 0)))
    return findings[:limit] if limit else findings
