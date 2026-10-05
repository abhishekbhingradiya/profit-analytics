"""Imports monthly costs from a QuickBooks P&L report using the account-category mappings."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.qbo_client import QBOClient
from app.models import AccountMapping, CostEntry, Organization
from app.services.metrics import ALL_CATEGORIES


def _shift_month(month: date, offset: int) -> date:
    absolute = month.year * 12 + month.month - 1 + offset
    year, index = divmod(absolute, 12)
    return date(year, index + 1, 1)


def report_months(report: dict) -> list[date]:
    """Month columns are identified by StartDate metadata; summary columns have none."""
    months: list[date] = []
    for column in ((report.get("Columns") or {}).get("Column") or []):
        for meta in column.get("MetaData") or []:
            if meta.get("Name") == "StartDate" and meta.get("Value"):
                year, month, _day = (int(part) for part in meta["Value"].split("-"))
                months.append(date(year, month, 1))
                break
    return months


def report_account_rows(report: dict) -> list[dict]:
    """Flatten nested report sections into {account_id, account_name, amounts[]} leaf rows."""
    rows: list[dict] = []

    def walk(node: dict) -> None:
        for row in ((node.get("Rows") or {}).get("Row") or []):
            col_data = row.get("ColData") or []
            if col_data and col_data[0].get("id"):
                amounts = []
                for cell in col_data[1:]:
                    raw = (cell.get("value") or "").replace(",", "")
                    try:
                        amounts.append(float(raw))
                    except ValueError:
                        amounts.append(0.0)
                rows.append(
                    {
                        "account_id": str(col_data[0]["id"]),
                        "account_name": col_data[0].get("value") or f"Account {col_data[0]['id']}",
                        "amounts": amounts,
                    }
                )
            walk(row)

    walk(report)
    return rows


def refresh_account_mappings(db: Session, org: Organization, accounts: list[dict]) -> int:
    existing = {
        mapping.account_id
        for mapping in db.scalars(
            select(AccountMapping).where(AccountMapping.org_id == org.id, AccountMapping.provider == "quickbooks")
        )
    }
    added = 0
    for account in accounts:
        account_id = str(account.get("Id") or "")
        if not account_id or account_id in existing:
            continue
        db.add(
            AccountMapping(
                org_id=org.id,
                provider="quickbooks",
                account_id=account_id,
                account_name=str(account.get("Name") or account_id)[:200],
                account_type=str(account.get("AccountType") or "")[:60],
                category=None,
            )
        )
        added += 1
    return added


def load_mappings(db: Session, org_id: int) -> dict[str, str]:
    rows = db.scalars(
        select(AccountMapping).where(
            AccountMapping.org_id == org_id,
            AccountMapping.provider == "quickbooks",
            AccountMapping.category.is_not(None),
        )
    )
    return {row.account_id: row.category for row in rows if row.category in ALL_CATEGORIES}


def sync_quickbooks(db: Session, org: Organization, client: QBOClient, months: int = 24, today: date | None = None) -> dict:
    """Replace shared cost pools for the report window; direct customer costs and revenue are untouched."""
    today = (today or date.today()).replace(day=1)
    start = _shift_month(today, -(months - 1))
    report = client.profit_and_loss_by_month(start, _shift_month(today, 1))
    month_columns = report_months(report)
    account_rows = report_account_rows(report)
    if not month_columns or not account_rows:
        raise ValueError("QuickBooks returned an empty profit-and-loss report; nothing was imported.")

    mappings = load_mappings(db, org.id)
    totals: dict[tuple[date, str], float] = {}
    imported_amount = 0.0
    excluded_amount = 0.0
    unmapped_accounts: set[str] = set()
    for row in account_rows:
        category = mappings.get(row["account_id"])
        for month, amount in zip(month_columns, row["amounts"]):
            if category is None:
                excluded_amount += amount
                if amount:
                    unmapped_accounts.add(row["account_name"])
                continue
            if amount == 0:
                continue
            totals[(month, category)] = totals.get((month, category), 0.0) + amount
            imported_amount += amount
    if not totals:
        raise ValueError("No mapped account produced any cost; map GL accounts to categories first.")

    db.execute(
        delete(CostEntry).where(
            CostEntry.org_id == org.id,
            CostEntry.customer_id.is_(None),
            CostEntry.month.in_(month_columns),
        )
    )
    db.add_all(
        CostEntry(org_id=org.id, month=month, category=category, customer_id=None, amount=round(amount, 2))
        for (month, category), amount in totals.items()
    )
    return {
        "cost_rows": len(totals),
        "first_month": month_columns[0].strftime("%Y-%m"),
        "last_month": month_columns[-1].strftime("%Y-%m"),
        "imported_amount": round(imported_amount, 2),
        "excluded_amount": round(excluded_amount, 2),
        "unmapped_accounts": sorted(unmapped_accounts)[:10],
        "mapped_accounts": len(mappings),
    }
