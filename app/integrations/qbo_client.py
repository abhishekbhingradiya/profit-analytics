"""Minimal read-only QuickBooks Online client (sandbox by default)."""

from __future__ import annotations

from datetime import date

import requests

SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"


class QBOError(RuntimeError):
    pass


class QBOClient:
    def __init__(self, realm_id: str, access_token: str, session=None, base_url: str = SANDBOX_BASE, timeout: int = 20):
        if not realm_id.strip() or not access_token.strip():
            raise QBOError("Provide both the company (realm) ID and an access token.")
        self._realm = realm_id.strip()
        self._token = access_token.strip()
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}/v3/company/{self._realm}{path}"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        try:
            response = self._session.get(url, params=params or {}, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise QBOError(f"Could not reach QuickBooks: {exc.__class__.__name__}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise QBOError(f"QuickBooks returned a non-JSON response (HTTP {response.status_code})") from exc
        if response.status_code == 401:
            raise QBOError("QuickBooks rejected the token (expired or invalid). Paste a fresh access token and retry.")
        if response.status_code >= 400:
            fault = ((payload.get("Fault") or {}).get("Error") or [{}])[0]
            raise QBOError(fault.get("Message") or f"QuickBooks error (HTTP {response.status_code})")
        return payload

    def query(self, sql: str) -> dict:
        return self.get("/query", {"query": sql})

    def query_all(self, select_sql: str, entity: str, page_size: int = 200, max_pages: int = 50) -> list[dict]:
        items: list[dict] = []
        position = 1
        for _ in range(max_pages):
            page = self.query(f"{select_sql} STARTPOSITION {position} MAXRESULTS {page_size}")
            rows = (page.get("QueryResponse") or {}).get(entity) or []
            items.extend(rows)
            if len(rows) < page_size:
                return items
            position += page_size
        raise QBOError(f"{entity} query exceeded {max_pages} pages; aborting to protect the sync.")

    def company_name(self) -> str:
        payload = self.query("SELECT * FROM CompanyInfo")
        info = ((payload.get("QueryResponse") or {}).get("CompanyInfo") or [{}])[0]
        return info.get("CompanyName") or self._realm

    def expense_accounts(self) -> list[dict]:
        sql = "SELECT Id, Name, AccountType FROM Account WHERE AccountType IN ('Expense', 'Cost of Goods Sold', 'Other Expense')"
        return self.query_all(sql, "Account")

    def profit_and_loss_by_month(self, start: date, end: date) -> dict:
        return self.get(
            "/reports/ProfitAndLoss",
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "summarize_column_by": "Month",
                "accounting_method": "Accrual",
            },
        )
