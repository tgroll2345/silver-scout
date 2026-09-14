from __future__ import annotations
import base64
import os
import time
import requests
from urllib.parse import quote

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

class EbayClient:
    def __init__(self, client_id=None, client_secret=None, marketplace_id=None):
        self.client_id = client_id or os.getenv("EBAY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("EBAY_CLIENT_SECRET")
        self.marketplace_id = marketplace_id or os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
        self._token = None
        self._expires = 0

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    def get_token(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        if not self.configured:
            raise RuntimeError("eBay credentials are not configured")
        raw = f"{self.client_id}:{self.client_secret}".encode()
        auth = base64.b64encode(raw).decode()
        r = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def search(self, query: str, limit: int = 50):
        token = self.get_token()
        params = {
            "q": query,
            "limit": min(max(limit, 1), 200),
            "sort": "newlyListed",
            "fieldgroups": "EXTENDED",
        }
        r = requests.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            },
            params=params,
            timeout=25,
        )
        r.raise_for_status()
        return r.json().get("itemSummaries", [])


def normalize_item(item: dict) -> dict:
    price = float(item.get("price", {}).get("value", 0) or 0)
    shipping = 0.0
    shipping_options = item.get("shippingOptions") or []
    if shipping_options:
        shipping = float(shipping_options[0].get("shippingCost", {}).get("value", 0) or 0)
    return {
        "item_id": item.get("itemId"),
        "title": item.get("title", ""),
        "description": item.get("shortDescription", "") or "",
        "price": price,
        "shipping": shipping,
        "url": item.get("itemWebUrl", ""),
        "image": (item.get("image") or {}).get("imageUrl", ""),
        "condition": item.get("condition", ""),
    }
