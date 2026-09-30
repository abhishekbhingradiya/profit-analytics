"""Explains why gross profit changed between two periods."""

from __future__ import annotations

import pandas as pd

from app.services.datasets import Dataset
from app.services.formatting import money, signed_money
from app.services.metrics import (
    CATEGORY_LABELS,
    COGS_CATEGORIES,
    OPEX_CATEGORIES,
    monthly_pnl,
    mrr_bridge,
    ratio,
)


def _label(months: pd.DatetimeIndex) -> str:
    if len(months) == 1:
        return months[0].strftime("%b %Y")
    return f"{months[0]:%b %Y} to {months[-1]:%b %Y}"


def explain_change(ds: Dataset, period_months: int = 1) -> dict | None:
    """Decompose the gross profit change into revenue-by-segment and COGS-by-category drivers."""
    pnl = monthly_pnl(ds)
    n = period_months
    if len(pnl) < 2 * n:
        return None
    cur, prev = pnl.iloc[-n:], pnl.iloc[-2 * n : -n]

    rev = ds.revenue.merge(ds.customers[["customer_id", "segment"]], on="customer_id", how="left")
    rev["segment"] = rev["segment"].fillna("Unknown")
    seg_cur = rev[rev["month"].isin(cur.index)].groupby("segment")["mrr"].sum()
    seg_prev = rev[rev["month"].isin(prev.index)].groupby("segment")["mrr"].sum()
    seg_delta = seg_cur.subtract(seg_prev, fill_value=0.0).sort_values(ascending=False)

    revenue_drivers = [
        {"driver": f"{seg} revenue", "kind": "revenue", "impact": float(v)} for seg, v in seg_delta.items()
    ]
    cost_drivers = [
        {"driver": CATEGORY_LABELS[c], "kind": "cost", "impact": -float(cur[c].sum() - prev[c].sum())}
        for c in COGS_CATEGORIES
    ]
    cost_drivers.sort(key=lambda d: d["impact"], reverse=True)
    all_drivers = [d for d in revenue_drivers + cost_drivers if abs(d["impact"]) >= 0.01]
    ranked = sorted(all_drivers, key=lambda d: abs(d["impact"]), reverse=True)

    gp_prev, gp_cur = float(prev["gross_profit"].sum()), float(cur["gross_profit"].sum())
    rev_prev, rev_cur = float(prev["revenue"].sum()), float(cur["revenue"].sum())
    gm_prev, gm_cur = ratio(gp_prev, rev_prev), ratio(gp_cur, rev_cur)
    change = gp_cur - gp_prev
    change_pct = ratio(change, abs(gp_prev)) if gp_prev else None

    narrative = []
    direction = "rose" if change >= 0 else "fell"
    pct_txt = f" ({change_pct:+.1%})" if change_pct is not None else ""
    narrative.append(
        f"Gross profit {direction} {money(abs(change))}{pct_txt} to {money(gp_cur)} in "
        f"{_label(cur.index)} compared with {_label(prev.index)}."
    )
    if gm_prev is not None and gm_cur is not None:
        narrative.append(
            f"Gross margin moved from {gm_prev:.1%} to {gm_cur:.1%} ({(gm_cur - gm_prev) * 100:+.1f} pp)."
        )
    if ranked:
        parts = [f"{d['driver']} ({signed_money(d['impact'])})" for d in ranked[:3]]
        narrative.append("Largest drivers: " + ", ".join(parts) + ".")

    rev_growth = ratio(rev_cur - rev_prev, rev_prev)
    for c in COGS_CATEGORIES:
        growth = ratio(cur[c].sum() - prev[c].sum(), prev[c].sum())
        if growth is not None and rev_growth is not None and growth - rev_growth > 0.10:
            narrative.append(
                f"{CATEGORY_LABELS[c]} grew {growth:+.0%}, well ahead of revenue ({rev_growth:+.0%}). "
                f"Review {CATEGORY_LABELS[c].lower()} efficiency."
            )

    opex_delta = float(cur["opex"].sum() - prev["opex"].sum())
    if abs(opex_delta) >= 1:
        top = max(OPEX_CATEGORIES, key=lambda c: abs(cur[c].sum() - prev[c].sum()))
        narrative.append(
            f"Operating expenses {'increased' if opex_delta > 0 else 'decreased'} by {money(abs(opex_delta))}, "
            f"driven mostly by {CATEGORY_LABELS[top]} ({signed_money(float(cur[top].sum() - prev[top].sum()))})."
        )

    bridge = mrr_bridge(ds)
    if not bridge.empty:
        b = bridge.iloc[-1]
        narrative.append(
            f"Latest month MRR movement: new {money(b['new'])}, expansion {money(b['expansion'])}, "
            f"contraction {money(b['contraction'])}, churn {money(b['churn'])} "
            f"(net {signed_money(float(b['net_new_mrr']))})."
        )

    disc_prev = ratio(prev["discounts"].sum(), prev["list_revenue"].sum())
    disc_cur = ratio(cur["discounts"].sum(), cur["list_revenue"].sum())
    if disc_prev is not None and disc_cur is not None and disc_cur - disc_prev >= 0.01:
        cost = float(cur["list_revenue"].sum()) * (disc_cur - disc_prev)
        narrative.append(
            f"Average discount rate increased from {disc_prev:.1%} to {disc_cur:.1%}, "
            f"costing about {money(cost)} in the period."
        )

    return {
        "period_months": n,
        "current_period": _label(cur.index),
        "previous_period": _label(prev.index),
        "gross_profit": {"previous": gp_prev, "current": gp_cur, "change": change, "change_pct": change_pct},
        "gross_margin": {"previous": gm_prev, "current": gm_cur},
        "revenue": {"previous": rev_prev, "current": rev_cur},
        "discount_rate": {"previous": disc_prev, "current": disc_cur},
        "drivers": ranked,
        "waterfall": {
            "start": gp_prev,
            "end": gp_cur,
            "steps": [{"label": d["driver"], "impact": d["impact"]} for d in all_drivers],
        },
        "narrative": narrative,
    }
