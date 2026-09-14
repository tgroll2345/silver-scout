from __future__ import annotations
import os
import requests


def get_silver_spot_from_metals_dev(api_key: str | None = None) -> float | None:
    """Optional provider. Returns USD per troy ounce when configured."""
    key = api_key or os.getenv("METALS_DEV_API_KEY")
    if not key:
        return None
    # Provider response formats can change; fail safely to manual spot input.
    try:
        r = requests.get("https://api.metals.dev/v1/latest", params={"api_key": key, "currency": "USD", "unit": "toz"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        metals = data.get("metals", {})
        for k in ("silver", "XAG", "xag"):
            if k in metals:
                return float(metals[k])
    except Exception:
        return None
    return None
