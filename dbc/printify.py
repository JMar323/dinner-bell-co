"""Printify API client. Read-only: it can only send GET requests.

    client = Client(token)
    client.shops()                   # [{id, title, sales_channel}]
    client.orders(shop_id, page=1)   # one page (Printify's max is 10 orders a page)

There is deliberately no send_to_production, cancel or create here. Sending an order to
production stays John's click in Printify until he OKs stage-2 auto-approval (docs/plan.md).
API reference: https://developers.printify.com/ (Bearer token, User-Agent required, 600 req/min).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

BASE_URL = "https://api.printify.com/v1"
USER_AGENT = "DinnerBellCo/0.1 (python-urllib)"
PAGE_SIZE = 10           # Printify's maximum for the orders list
RETRY_STATUSES = {429, 500, 502, 503, 504}

# A transport takes (method, url, headers) and returns (status, headers, body bytes).
Transport = Callable[[str, str, dict], tuple[int, dict, bytes]]


class PrintifyError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def urllib_transport(method: str, url: str, headers: dict, timeout: float = 30) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise PrintifyError(f"can't reach Printify: {getattr(e, 'reason', e)}") from None


class Client:
    def __init__(self, token: str, transport: Transport = urllib_transport,
                 retries: int = 2, sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise PrintifyError("PRINTIFY_TOKEN is not set (see docs/keys.md #1)")
        self._token = token
        self._transport = transport
        self._retries = retries
        self._sleep = sleep
        self.requests = 0

    def _get(self, path: str, params: dict | None = None):
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        for attempt in range(self._retries + 1):
            self.requests += 1
            status, resp_headers, body = self._transport("GET", url, headers)
            if status in RETRY_STATUSES and attempt < self._retries:
                self._sleep(_retry_after(resp_headers, attempt))
                continue
            break
        if status == 401:
            raise PrintifyError("Printify rejected the token (401): expired, revoked or mistyped", status)
        if status == 403:
            raise PrintifyError("Printify token lacks a scope this needs (403): check shops.read and orders.read", status)
        if status >= 400:
            raise PrintifyError(f"Printify {path} returned {status}: {_error_message(body)}", status)
        try:
            return json.loads(body or b"null")
        except json.JSONDecodeError:
            raise PrintifyError(f"Printify {path} returned something that isn't JSON") from None

    def shops(self) -> list[dict]:
        return self._get("/shops.json") or []

    def orders(self, shop_id: int | str, page: int = 1, status: str | None = None) -> dict:
        return self._get(f"/shops/{shop_id}/orders.json",
                         {"page": page, "limit": PAGE_SIZE, "status": status}) or {}

    def order(self, shop_id: int | str, order_id: str) -> dict:
        return self._get(f"/shops/{shop_id}/orders/{order_id}.json") or {}


def _retry_after(headers: dict, attempt: int) -> float:
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                return min(float(v), 60.0)
            except ValueError:
                break
    return 2.0 * (attempt + 1)


def _error_message(body: bytes) -> str:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return (body or b"").decode("utf-8", "replace")[:200]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or data)[:200]
    return str(data)[:200]


def pick_shop(shops: list[dict], shop_id: str | None = None) -> tuple[dict | None, str]:
    """The Printify shop to watch: PRINTIFY_SHOP_ID if set, else the one Etsy-connected shop.

    Returns (shop, note). shop is None when there's nothing to watch yet (note says why).
    """
    if shop_id:
        for s in shops:
            if str(s.get("id")) == str(shop_id):
                return s, ""
        raise PrintifyError(f"PRINTIFY_SHOP_ID={shop_id} isn't one of this token's shops")
    etsy = [s for s in shops if str(s.get("sales_channel", "")).lower() == "etsy"]
    if len(etsy) == 1:
        return etsy[0], ""
    if len(etsy) > 1:
        ids = ", ".join(f"{s.get('id')} ({s.get('title')})" for s in etsy)
        raise PrintifyError(f"several Etsy shops in Printify ({ids}); set PRINTIFY_SHOP_ID in the .env")
    return None, "no Etsy-connected shop in Printify yet (connect after the shop opens); nothing to watch"
