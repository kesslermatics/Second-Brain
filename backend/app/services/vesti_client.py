"""
Vesti REST Client — calls the Vesti wardrobe API.

All endpoints are GET requests with optional query-param filters.
Filter rules (server-side):
  - String filters: case-insensitive substring match
  - favorite: real bool (true/false)
  - season/occasion/family: match against list fields on the item
Auth is via a static API key header.
"""

import logging
import httpx
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_ENDPOINT_PATHS = {
    "clothing":              "/mcp/clothing",
    "watches":               "/mcp/watches",
    "fragrances":            "/mcp/fragrances",
    "accessories":           "/mcp/accessories",
    "analytics_watches":     "/mcp/analytics/watches",
    "analytics_fragrances":  "/mcp/analytics/fragrances",
    "analytics_accessories": "/mcp/analytics/accessories",
}


async def call_vesti(endpoint_key: str, params: dict[str, Any] | None = None) -> Any:
    """
    Fetch a single Vesti endpoint with optional query params and return parsed JSON.
    Returns {"error": "..."} on failure so the agent can handle it gracefully.

    Filter params are passed as-is as query string parameters.
    None/empty values are stripped before sending.
    """
    settings = get_settings()
    base_url = settings.VESTI_API_URL.rstrip("/")
    api_key  = settings.VESTI_API_KEY

    if not base_url or not api_key:
        return {"error": "Vesti API not configured (VESTI_API_URL / VESTI_API_KEY missing)"}

    path = _ENDPOINT_PATHS.get(endpoint_key)
    if not path:
        return {"error": f"Unbekannter Vesti-Endpoint: {endpoint_key}"}

    # Strip None and empty-string values — only send real filters
    clean_params: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if v is None or v == "":
            continue
        # Convert booleans to lowercase strings for query params
        if isinstance(v, bool):
            clean_params[k] = "true" if v else "false"
        else:
            clean_params[k] = v

    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base_url}{path}",
                headers=headers,
                params=clean_params or None,
            )
            resp.raise_for_status()
            return resp.json()

    except httpx.HTTPStatusError as e:
        logger.error(f"Vesti HTTP {e.response.status_code} for {endpoint_key}: {e.response.text[:200]}")
        return {"error": f"Vesti API HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        logger.error(f"Vesti timeout for {endpoint_key}")
        return {"error": "Vesti API timeout"}
    except Exception as e:
        logger.error(f"Vesti unexpected error for {endpoint_key}: {e}")
        return {"error": str(e)[:200]}
