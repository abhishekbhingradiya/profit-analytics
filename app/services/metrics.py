"""Core SaaS profitability metrics computed from a tenant dataset."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.datasets import Dataset

COGS_CATEGORIES = ("hosting", "support", "third_party", "payment_fees")
OPEX_CATEGORIES = ("sales", "marketing", "rnd", "gna")
SALES_MARKETING = ("sales", "marketing")
ALL_CATEGORIES = COGS_CATEGORIES + OPEX_CATEGORIES
DIMENSIONS = ("segment", "region", "industry", "channel", "plan")

CATEGORY_LABELS = {
    "hosting": "Hosting",
    "support": "Customer support",
    "third_party": "Third-party software",
    "payment_fees": "Payment fees",
    "sales": "Sales",
    "marketing": "Marketing",
    "rnd": "R&D",
    "gna": "G&A",
}


def ratio(num, den) -> float | None:
    if den is None or num is None:
        return None
    den = float(den)
    if den == 0 or np.isnan(den):
        return None
    value = float(num) / den
    return None if np.isnan(value) else value


def month_range(ds: Dataset) -> pd.DatetimeIndex:
    months = ds.revenue["month"]
    return pd.date_range(months.min(), months.max(), freq="MS")


def monthly_pnl(ds: Dataset) -> pd.DataFrame:
    idx = month_range(ds)
    rev = ds.revenue.groupby("month")[["mrr", "list_mrr"]].sum().reindex(idx, fill_value=0.0)
    if ds.costs.empty:
        costs = pd.DataFrame(0.0, index=idx, columns=list(ALL_CATEGORIES))
    else:
        costs = ds.costs.pivot_table(index="month", columns="category", values="amount", aggfunc="sum", fill_value=0.0)
        costs = costs.reindex(index=idx, columns=list(ALL_CATEGORIES), fill_value=0.0)

    pnl = pd.DataFrame(index=idx)
    pnl.index.name = "month"
    pnl["revenue"] = rev["mrr"]
    pnl["list_revenue"] = rev["list_mrr"]
    pnl["discounts"] = pnl["list_revenue"] - pnl["revenue"]
    for c in ALL_CATEGORIES:
        pnl[c] = costs[c]
    pnl["cogs"] = costs[list(COGS_CATEGORIES)].sum(axis=1)
    pnl["gross_profit"] = pnl["revenue"] - pnl["cogs"]
    pnl["opex"] = costs[list(OPEX_CATEGORIES)].sum(axis=1)
    pnl["operating_income"] = pnl["gross_profit"] - pnl["opex"]
    safe_rev = pnl["revenue"].replace(0, np.nan)
    pnl["gross_margin"] = pnl["gross_profit"] / safe_rev
    pnl["operating_margin"] = pnl["operating_income"] / safe_rev
    return pnl


def mrr_matrix(ds: Dataset) -> pd.DataFrame:
    """Customers x months matrix of MRR (0 when inactive)."""
    m = ds.revenue.pivot_table(index="customer_id", columns="month", values="mrr", aggfunc="sum", fill_value=0.0)
    return m.reindex(columns=month_range(ds), fill_value=0.0)


def _movement_arrays(m: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cur = m.to_numpy(dtype=float)
    prev = np.zeros_like(cur)
    prev[:, 1:] = cur[:, :-1]
    seen_before = np.zeros(cur.shape, dtype=bool)
    seen_before[:, 1:] = np.cumsum(cur > 0, axis=1)[:, :-1] > 0
    return cur, prev, seen_before


def mrr_bridge(ds: Dataset) -> pd.DataFrame:
    """Monthly MRR movements: new, expansion, reactivation, contraction, churn."""
    m = mrr_matrix(ds)
    cur, prev, seen = _movement_arrays(m)
    started = (prev <= 0) & (cur > 0)
    is_new = started & ~seen
    reactivated = started & seen
    retained = (prev > 0) & (cur > 0)
    churned = (prev > 0) & (cur <= 0)
    bridge = pd.DataFrame(
        {
            "starting_mrr": prev.sum(axis=0),
            "new": np.where(is_new, cur, 0.0).sum(axis=0),
            "expansion": np.where(retained & (cur > prev), cur - prev, 0.0).sum(axis=0),
            "reactivation": np.where(reactivated, cur, 0.0).sum(axis=0),
            "contraction": np.where(retained & (cur < prev), cur - prev, 0.0).sum(axis=0),
            "churn": np.where(churned, -prev, 0.0).sum(axis=0),
            "ending_mrr": cur.sum(axis=0),
            "new_customers": is_new.sum(axis=0),
            "churned_customers": churned.sum(axis=0),
            "active_customers": (cur > 0).sum(axis=0),
        },
        index=m.columns,
    )
    bridge.index.name = "month"
    bridge["net_new_mrr"] = bridge["ending_mrr"] - bridge["starting_mrr"]
    # The first month has no prior period to compare with.
    return bridge.iloc[1:]


def retention(ds: Dataset, lookback: int = 12) -> dict:
    m = mrr_matrix(ds)
    lookback = min(lookback, m.shape[1] - 1)
    if lookback < 1:
        return {"lookback_months": 0, "nrr": None, "grr": None, "logo_retention": None}
    base = m.iloc[:, -1 - lookback]
    cur = m.iloc[:, -1]
    mask = base > 0
    b, c = base[mask], cur[mask]
    return {
        "lookback_months": lookback,
        "nrr": ratio(c.sum(), b.sum()),
        "grr": ratio(np.minimum(c, b).sum(), b.sum()),
        "logo_retention": ratio((c > 0).sum(), mask.sum()),
    }


def cohort_retention(ds: Dataset, periods: int = 12, max_cohorts: int = 8) -> dict:
    """Net MRR retention by quarterly signup cohort, relative to each customer's first month."""
    m = mrr_matrix(ds)
    arr = m.to_numpy(dtype=float)
    n_months = arr.shape[1]
    active = arr > 0
    first = active.argmax(axis=1)
    # Customers active in the first observed month have no observable start.
    keep = active.any(axis=1) & (first > 0)
    labels = np.asarray(m.columns[first].to_period("Q").astype(str))
    cohorts = []
    for label in sorted(set(labels[keep]))[-max_cohorts:]:
        idx = np.where(keep & (labels == label))[0]
        start_mrr = arr[idx, first[idx]].sum()
        values = []
        for k in range(periods + 1):
            pos = first[idx] + k
            if (pos >= n_months).any() or not start_mrr:
                break
            values.append(float(arr[idx, pos].sum() / start_mrr))
        cohorts.append({"cohort": label, "customers": len(idx), "starting_mrr": float(start_mrr), "retention": values})
    return {"periods": periods, "cohorts": cohorts}


def customer_profitability(ds: Dataset, months: int = 12) -> pd.DataFrame:
    """Per-customer revenue, direct COGS, allocated shared COGS and gross profit over the last N months."""
    window = month_range(ds)[-months:]
    rev = ds.revenue[ds.revenue["month"].isin(window)]
    cogs = ds.costs[ds.costs["month"].isin(window) & ds.costs["category"].isin(COGS_CATEGORIES)]

    per = rev.groupby("customer_id").agg(revenue=("mrr", "sum"), list_revenue=("list_mrr", "sum"))
    direct = cogs[cogs["customer_id"].notna()]
    if direct.empty:
        direct_p = pd.DataFrame(index=pd.Index([], name="customer_id", dtype="int64"))
    else:
        direct = direct.astype({"customer_id": "int64"})
        direct_p = direct.pivot_table(
            index="customer_id", columns="category", values="amount", aggfunc="sum", fill_value=0.0
        )
    df = per.join(direct_p, how="outer").fillna(0.0)
    for c in COGS_CATEGORIES:
        if c not in df.columns:
            df[c] = 0.0
    df["direct_cogs"] = df[list(COGS_CATEGORIES)].sum(axis=1)
    shared = float(cogs.loc[cogs["customer_id"].isna(), "amount"].sum())
    total_rev = float(df["revenue"].sum())
    df["allocated_cogs"] = shared * df["revenue"] / total_rev if total_rev else 0.0
    df["gross_profit"] = df["revenue"] - df["direct_cogs"] - df["allocated_cogs"]
    df["gross_margin"] = df["gross_profit"] / df["revenue"].replace(0, np.nan)
    df["discount"] = df["list_revenue"] - df["revenue"]
    df["discount_rate"] = df["discount"] / df["list_revenue"].replace(0, np.nan)
    df["plan"] = rev.sort_values("month").groupby("customer_id")["plan"].last()
    df.index.name = "customer_id"

    attrs = ds.customers.set_index("customer_id")[["external_id", "name", "segment", "region", "industry", "channel"]]
    df = df.join(attrs, how="left").reset_index()
    df["plan"] = df["plan"].fillna("None")
    return df


def profitability_by(ds: Dataset, dimension: str = "segment", months: int = 12) -> pd.DataFrame:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Unsupported dimension: {dimension}")
    cp = customer_profitability(ds, months)
    cp[dimension] = cp[dimension].fillna("Unknown")
    g = (
        cp.groupby(dimension)
        .agg(
            customers=("customer_id", "nunique"),
            revenue=("revenue", "sum"),
            list_revenue=("list_revenue", "sum"),
            direct_cogs=("direct_cogs", "sum"),
            allocated_cogs=("allocated_cogs", "sum"),
            gross_profit=("gross_profit", "sum"),
            discount=("discount", "sum"),
        )
        .sort_values("revenue", ascending=False)
    )
    g["gross_margin"] = g["gross_profit"] / g["revenue"].replace(0, np.nan)
    g["discount_rate"] = g["discount"] / g["list_revenue"].replace(0, np.nan)
    total = g["revenue"].sum()
    g["revenue_share"] = g["revenue"] / total if total else np.nan
    return g.reset_index().rename(columns={dimension: "group"})


def unit_economics(ds: Dataset, window: int = 6, by: str | None = None) -> list[dict]:
    """CAC, LTV and payback. S&M spend is allocated to groups by share of new MRR."""
    m = mrr_matrix(ds)
    if m.shape[1] < 2:
        return []
    window = max(1, min(window, m.shape[1] - 1))
    cur, prev, seen = _movement_arrays(m)
    cols = slice(m.shape[1] - window, m.shape[1])
    new = ((prev <= 0) & (cur > 0) & ~seen)[:, cols]
    churned = ((prev > 0) & (cur <= 0))[:, cols]
    exposure = (prev > 0)[:, cols]
    new_mrr = np.where(new, cur[:, cols], 0.0).sum(axis=1)
    last = cur[:, -1]
    window_months = m.columns[cols]

    costs = ds.costs
    sm_spend = float(
        costs.loc[costs["month"].isin(window_months) & costs["category"].isin(SALES_MARKETING), "amount"].sum()
    )
    cp = customer_profitability(ds, window).set_index("customer_id")

    if by is None:
        groups = pd.Series("All customers", index=m.index)
    elif by == "plan":
        groups = cp["plan"].reindex(m.index)
    elif by in DIMENSIONS:
        groups = ds.customers.set_index("customer_id")[by].reindex(m.index)
    else:
        raise ValueError(f"Unsupported dimension: {by}")
    groups = groups.fillna("Unknown").to_numpy()
    total_new_mrr = new_mrr.sum()

    results = []
    for group in pd.unique(groups):
        mask = groups == group
        n_new = int(new[mask].sum())
        n_churn = int(churned[mask].sum())
        active = int((last[mask] > 0).sum())
        arpa = ratio(last[mask].sum(), active)
        churn_rate = ratio(n_churn, int(exposure[mask].sum()))
        members = cp.loc[cp.index.isin(m.index[mask])]
        gm = ratio(members["gross_profit"].sum(), members["revenue"].sum())
        if total_new_mrr:
            sm = sm_spend * new_mrr[mask].sum() / total_new_mrr
        else:
            sm = sm_spend if by is None else 0.0
        cac = ratio(sm, n_new)
        gp_per_account = arpa * gm if arpa is not None and gm is not None else None
        ltv = ratio(gp_per_account, churn_rate) if gp_per_account is not None and churn_rate else None
        results.append(
            {
                "group": str(group),
                "active_customers": active,
                "mrr": float(last[mask].sum()),
                "arpa": arpa,
                "new_customers": n_new,
                "churned_customers": n_churn,
                "monthly_logo_churn": churn_rate,
                "gross_margin": gm,
                "sm_spend": sm,
                "cac": cac,
                "ltv": ltv,
                "ltv_to_cac": ratio(ltv, cac) if ltv is not None and cac else None,
                "cac_payback_months": ratio(cac, gp_per_account) if cac is not None and gp_per_account else None,
                "window_months": window,
            }
        )
    return sorted(results, key=lambda r: r["mrr"], reverse=True)


def kpis(ds: Dataset) -> dict:
    pnl = monthly_pnl(ds)
    last = pnl.iloc[-1]
    ttm = pnl.tail(12)
    mrr = float(last["revenue"])
    prev_month = float(pnl["revenue"].iloc[-2]) if len(pnl) > 1 else None
    year_ago = float(pnl["revenue"].iloc[-13]) if len(pnl) > 12 else None
    yoy = ratio(mrr - year_ago, year_ago) if year_ago else None
    ttm_op_margin = ratio(ttm["operating_income"].sum(), ttm["revenue"].sum())
    ret = retention(ds)
    ue_rows = unit_economics(ds)
    ue = ue_rows[0] if ue_rows else {}
    active = int((mrr_matrix(ds).iloc[:, -1] > 0).sum())
    return {
        "as_of": pnl.index[-1],
        "months_of_history": len(pnl),
        "mrr": mrr,
        "arr": mrr * 12,
        "mom_growth": ratio(mrr - prev_month, prev_month) if prev_month else None,
        "yoy_growth": yoy,
        "active_customers": active,
        "arpa": ratio(mrr, active),
        "gross_margin": ratio(last["gross_profit"], last["revenue"]),
        "ttm_revenue": float(ttm["revenue"].sum()),
        "ttm_gross_margin": ratio(ttm["gross_profit"].sum(), ttm["revenue"].sum()),
        "ttm_operating_income": float(ttm["operating_income"].sum()),
        "ttm_operating_margin": ttm_op_margin,
        "discount_rate": ratio(ttm["discounts"].sum(), ttm["list_revenue"].sum()),
        "nrr": ret["nrr"],
        "grr": ret["grr"],
        "logo_retention": ret["logo_retention"],
        "monthly_logo_churn": ue.get("monthly_logo_churn"),
        "cac": ue.get("cac"),
        "ltv": ue.get("ltv"),
        "ltv_to_cac": ue.get("ltv_to_cac"),
        "cac_payback_months": ue.get("cac_payback_months"),
        "rule_of_40": yoy + ttm_op_margin if yoy is not None and ttm_op_margin is not None else None,
    }
