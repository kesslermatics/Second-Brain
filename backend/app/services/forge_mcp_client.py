"""
Forge MCP Client — calls the Forge fitness/nutrition MCP server.

The Forge MCP server uses the standard MCP HTTP+SSE transport.
We call it via the `POST /mcp` endpoint with JSON-RPC style tool calls.

All calls are stateless (no session management needed for tools/call).
"""

import logging
import httpx
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


async def call_forge_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """
    Call a single tool on the Forge MCP server and return the parsed result.

    Raises on HTTP errors; returns {"error": ...} on MCP-level errors.
    """
    settings = get_settings()
    url = settings.FORGE_MCP_URL
    api_key = settings.FORGE_API_KEY

    if not url or not api_key:
        return {"error": "Forge MCP not configured (FORGE_MCP_URL / FORGE_API_KEY missing)"}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

            # MCP responses can come as plain JSON or as an SSE stream
            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                data = _parse_sse_response(resp.text)
            else:
                data = resp.json()

        # Unwrap JSON-RPC envelope
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            logger.warning(f"Forge MCP error for {tool_name}: {msg}")
            return {"error": msg}

        result = data.get("result", {})

        # MCP wraps text results in content[].text
        if isinstance(result, dict) and "content" in result:
            content_parts = result["content"]
            if isinstance(content_parts, list) and content_parts:
                first = content_parts[0]
                if isinstance(first, dict) and first.get("type") == "text":
                    import json as _json
                    try:
                        return _json.loads(first["text"])
                    except (_json.JSONDecodeError, KeyError):
                        return {"text": first.get("text", "")}

        return result if isinstance(result, dict) else {"result": result}

    except httpx.HTTPStatusError as e:
        logger.error(f"Forge HTTP error {e.response.status_code} for {tool_name}: {e.response.text[:300]}")
        return {"error": f"Forge API HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        logger.error(f"Forge timeout for {tool_name}")
        return {"error": "Forge API timeout"}
    except Exception as e:
        logger.error(f"Forge unexpected error for {tool_name}: {e}")
        return {"error": str(e)[:200]}


def _parse_sse_response(text: str) -> dict:
    """Parse an SSE response body and return the last data payload as dict."""
    import json as _json
    last_data = {}
    for line in text.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw and raw != "[DONE]":
                try:
                    last_data = _json.loads(raw)
                except _json.JSONDecodeError:
                    pass
    return last_data
