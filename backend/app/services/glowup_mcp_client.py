"""
Glowup MCP Client — calls the Glowup routine-tracker MCP server.

Transport: HTTP Streamable MCP (JSON-RPC 2.0), identical to forge_mcp_client.
Auth: Bearer token via Authorization header.
"""

import logging
import httpx
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


async def call_glowup_tool(tool_name: str, arguments: dict[str, Any]) -> dict:
    """
    Call a single tool on the Glowup MCP server and return the parsed result.

    Returns {"error": ...} on any failure so the agent can handle it gracefully.
    """
    settings = get_settings()
    url = settings.GLOWUP_MCP_URL
    api_key = settings.GLOWUP_MCP_API_KEY

    if not url or not api_key:
        return {"error": "Glowup MCP not configured (GLOWUP_MCP_URL / GLOWUP_MCP_API_KEY missing)"}

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

            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                data = _parse_sse_response(resp.text)
            else:
                data = resp.json()

        # Unwrap JSON-RPC envelope
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            logger.warning(f"Glowup MCP error for {tool_name}: {msg}")
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
        logger.error(f"Glowup HTTP error {e.response.status_code} for {tool_name}: {e.response.text[:300]}")
        return {"error": f"Glowup API HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        logger.error(f"Glowup timeout for {tool_name}")
        return {"error": "Glowup API timeout"}
    except Exception as e:
        logger.error(f"Glowup unexpected error for {tool_name}: {e}")
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
