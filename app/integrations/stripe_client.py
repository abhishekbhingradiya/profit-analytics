"""Minimal read-only Stripe REST client with cursor pagination."""

from __future__ import annotations

import requests

API_BASE = "https://api.stripe.com/v1"


class StripeError(RuntimeError):
    pass


def is_test_key(api_key: str) -> bool:
    return api_key.startswith(("sk_test_", "rk_test_"))


class StripeClient:
    def __init__(self, api_key: str, session=None, base_url: str = API_BASE, timeout: int = 20):
        if not api_key or not api_key.startswith(("sk_", "rk_")):
            raise StripeError("Provide a Stripe secret key (sk_...) or restricted key (rk_...).")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = self._session.get(
                f"{self._base}{path}", params=params or {}, auth=(self._api_key, ""), timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise StripeError(f"Could not reach Stripe: {exc.__class__.__name__}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise StripeError(f"Stripe returned a non-JSON response (HTTP {response.status_code})") from exc
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") or f"Stripe error (HTTP {response.status_code})"
            raise StripeError(message)
        return payload

    def list_all(self, path: str, params: dict | None = None, page_size: int = 100, max_pages: int = 100) -> list[dict]:
        items: list[dict] = []
        starting_after = None
        for _ in range(max_pages):
            query = dict(params or {}, limit=page_size)
            if starting_after:
                query["starting_after"] = starting_after
            page = self.get(path, query)
            data = page.get("data") or []
            items.extend(data)
            if not page.get("has_more") or not data:
                return items
            starting_after = data[-1]["id"]
        raise StripeError(f"{path} returned more than {max_pages} pages; aborting to protect the sync.")

    def account(self) -> dict:
        return self.get("/account")
