# OpenRouter / OpenAI Chat Completions adapter.
# Exposes the same narrow ``client.aio.models`` surface that all services use,
# but now calls the standard Chat Completions API (/v1/chat/completions) which
# OpenRouter supports for every model including the Gemini family.
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI


# ── Public dataclasses (Gemini-style surface kept intact) ─────────────

@dataclass
class FunctionCall:
    name: str
    args: dict[str, Any]
    call_id: str | None = None


@dataclass
class Part:
    text: str | None = None
    function_call: FunctionCall | None = None
    function_response: dict[str, Any] | None = None
    data: bytes | None = None
    mime_type: str | None = None
    thought: bool = False

    @classmethod
    def from_text(cls, text: str) -> "Part":
        return cls(text=text)

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str) -> "Part":
        return cls(data=data, mime_type=mime_type)

    @classmethod
    def from_function_response(cls, name: str, response: dict[str, Any]) -> "Part":
        return cls(function_response={"name": name, "response": response})


@dataclass
class Content:
    role: str
    parts: list[Part]


@dataclass
class FunctionDeclaration:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class OpenAIWebSearch:
    """Marker — mapped to an injected system-prompt hint for web-aware models."""


@dataclass
class Tool:
    function_declarations: list[FunctionDeclaration] | None = None
    web_search: OpenAIWebSearch | None = None


@dataclass
class ThinkingConfig:
    thinking_level: str | None = None
    include_thoughts: bool | None = None


@dataclass
class AutomaticFunctionCallingConfig:
    disable: bool = True


@dataclass
class GenerateContentConfig:
    system_instruction: str | None = None
    temperature: float | None = None
    tools: list[Tool] | None = None
    response_mime_type: str | None = None
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    thinking_config: ThinkingConfig | None = None
    automatic_function_calling: AutomaticFunctionCallingConfig | None = None


# Existing services import ``types``; keep the compatibility surface.
types = SimpleNamespace(
    Part=Part,
    Content=Content,
    FunctionDeclaration=FunctionDeclaration,
    Tool=Tool,
    OpenAIWebSearch=OpenAIWebSearch,
    ThinkingConfig=ThinkingConfig,
    AutomaticFunctionCallingConfig=AutomaticFunctionCallingConfig,
    GenerateContentConfig=GenerateContentConfig,
)


@dataclass
class _Candidate:
    content: Content
    grounding_metadata: Any = None


@dataclass
class _Response:
    text: str
    parsed: dict | list | None
    candidates: list[_Candidate]
    usage_metadata: Any
    function_calls: list[FunctionCall] = field(default_factory=list)


# ── Conversion helpers ────────────────────────────────────────────────

def _function_tools(config: GenerateContentConfig | None) -> list[dict]:
    """Extract only *function* declarations as Chat Completions tool dicts."""
    tools: list[dict] = []
    for tool in (config.tools or []) if config else []:
        for declaration in tool.function_declarations or []:
            tools.append({
                "type": "function",
                "function": {
                    "name": declaration.name,
                    "description": declaration.description,
                    "parameters": declaration.parameters,
                },
            })
    return tools


def _has_web_search(config: GenerateContentConfig | None) -> bool:
    """Return True if any Tool requests web search grounding."""
    for tool in (config.tools or []) if config else []:
        if tool.web_search is not None:
            return True
    return False


def _part_to_content_block(part: Part) -> list[dict]:
    """Convert a Part to one or more Chat Completions content blocks."""
    if part.data is not None:
        encoded = base64.b64encode(part.data).decode("ascii")
        mime = part.mime_type or "application/octet-stream"
        data_url = f"data:{mime};base64,{encoded}"
        if mime.startswith("image/"):
            return [{"type": "image_url", "image_url": {"url": data_url}}]
        # Non-image binary (PDF, DOCX …) — embed as text description fallback
        return [{"type": "text", "text": f"[Attached file: {mime}, base64-encoded]"}]
    if part.function_response is not None:
        return [{
            "type": "text",
            "text": "Tool result for " + part.function_response["name"] + ":\n" + json.dumps(
                part.function_response["response"], ensure_ascii=False, default=str
            ),
        }]
    if part.text is not None:
        return [{"type": "text", "text": part.text}]
    return []


def _contents_to_messages(
    contents: str | list[Content] | list[str],
    system_instruction: str | None,
    web_search_hint: bool,
) -> list[dict]:
    """Convert Gemini-style contents + system instruction to Chat messages."""
    messages: list[dict] = []

    # Build system message
    sys_parts: list[str] = []
    if system_instruction:
        sys_parts.append(system_instruction)
    if web_search_hint:
        sys_parts.append(
            "You have access to current information from the web. "
            "When the user asks about recent events, facts, or anything that benefits "
            "from up-to-date knowledge, use your web browsing capability to search and "
            "include accurate, current information in your response. "
            "Always cite your sources with URLs when using web information."
        )
    if sys_parts:
        messages.append({"role": "system", "content": "\n\n".join(sys_parts)})

    # Simple string prompt
    if isinstance(contents, str):
        messages.append({"role": "user", "content": contents})
        return messages

    # List of Content / str items
    for content in contents:
        if isinstance(content, str):
            messages.append({"role": "user", "content": content})
            continue

        if isinstance(content, Part):
            blocks = _part_to_content_block(content)
            if blocks:
                messages.append({"role": "user", "content": blocks})
            continue

        # Content dataclass
        role = "assistant" if content.role == "model" else "user"
        blocks: list[dict] = []

        for part in content.parts:
            if part.function_call is not None:
                # assistant tool-call — handled as a special assistant message
                # We flush any accumulated text blocks first, then add the tool call
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
                    blocks = []
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": part.function_call.call_id or f"call_{part.function_call.name}",
                        "type": "function",
                        "function": {
                            "name": part.function_call.name,
                            "arguments": json.dumps(part.function_call.args, ensure_ascii=False),
                        },
                    }],
                })
                continue

            if part.function_response is not None:
                # tool result message
                if blocks:
                    messages.append({"role": role, "content": blocks})
                    blocks = []
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{part.function_response['name']}",
                    "content": json.dumps(
                        part.function_response["response"], ensure_ascii=False, default=str
                    ),
                })
                continue

            blocks.extend(_part_to_content_block(part))

        if blocks:
            # Flatten to a plain string when there's only one text block (cleaner for models)
            if len(blocks) == 1 and blocks[0].get("type") == "text":
                messages.append({"role": role, "content": blocks[0]["text"]})
            else:
                messages.append({"role": role, "content": blocks})

    return messages


def _extract_sources(choices: list[Any]) -> list[dict[str, str]]:
    """Extract URL citations from OpenRouter / OpenAI annotations in chat response."""
    sources: list[dict[str, str]] = []
    for choice in choices or []:
        message = getattr(choice, "message", None) or {}
        content = (
            message.get("content", "") if isinstance(message, dict)
            else getattr(message, "content", "") or ""
        )
        # OpenRouter returns annotations as part of message.annotations
        annotations = (
            message.get("annotations", []) if isinstance(message, dict)
            else getattr(message, "annotations", None) or []
        )
        for ann in annotations:
            ann_type = ann.get("type") if isinstance(ann, dict) else getattr(ann, "type", None)
            if ann_type == "url_citation":
                url_citation = ann.get("url_citation") if isinstance(ann, dict) else getattr(ann, "url_citation", None)
                if url_citation:
                    url = (
                        url_citation.get("url", "") if isinstance(url_citation, dict)
                        else getattr(url_citation, "url", "")
                    ) or ""
                    title = (
                        url_citation.get("title", "") if isinstance(url_citation, dict)
                        else getattr(url_citation, "title", "")
                    ) or url
                    if url:
                        sources.append({"title": title, "url": url})
    seen: set[str] = set()
    return [s for s in sources if not (s["url"] in seen or seen.add(s["url"]))][:8]  # type: ignore[func-returns-value]


def _extract_cost(usage: Any) -> float:
    """Pull the credit cost out of an OpenRouter usage object (0.0 if absent).

    OpenRouter returns the cost either directly on ``usage.cost`` or nested in
    ``usage.cost_details.upstream_inference_cost`` depending on the model."""
    if usage is None:
        return 0.0
    cost = getattr(usage, "cost", None)
    if cost is None and isinstance(usage, dict):
        cost = usage.get("cost")
    try:
        return float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _patch_schema(schema: dict) -> dict:
    """Recursively add 'additionalProperties': false and fill 'required' for strict JSON output."""
    import copy
    schema = copy.deepcopy(schema)

    def _walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
            props = node.get("properties") or {}
            if props:
                node["required"] = sorted(props.keys())
            for prop in props.values():
                _walk(prop)
        elif node.get("type") == "array":
            _walk(node.get("items"))
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in node.get(key) or []:
                _walk(sub)

    _walk(schema)
    return schema


# ── Core Chat Completions adapter ─────────────────────────────────────

class _Models:
    def __init__(self, client: AsyncOpenAI):
        self._client = client

    async def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: GenerateContentConfig | None = None,
    ) -> _Response:
        web_search = _has_web_search(config)
        messages = _contents_to_messages(
            contents,
            system_instruction=config.system_instruction if config else None,
            web_search_hint=web_search,
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if config and config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config and config.max_output_tokens:
            kwargs["max_tokens"] = config.max_output_tokens

        # Function-calling tools
        function_tools = _function_tools(config)
        if function_tools:
            kwargs["tools"] = function_tools
            kwargs["tool_choice"] = "auto"

        # Structured JSON output
        if config and config.response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": _patch_schema(config.response_schema),
                },
            }
        elif config and config.response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        # Ask OpenRouter to include the real credit cost in the usage object.
        kwargs["extra_body"] = {"usage": {"include": True}}

        raw = await self._client.chat.completions.create(**kwargs)

        # Extract text from the response
        text = ""
        function_calls: list[FunctionCall] = []
        for choice in raw.choices or []:
            message = choice.message
            if message.content:
                text = message.content
            # Handle tool calls
            for tc in getattr(message, "tool_calls", None) or []:
                arguments = getattr(tc.function, "arguments", "{}") or "{}"
                try:
                    args = json.loads(arguments)
                except json.JSONDecodeError:
                    args = {}
                function_calls.append(FunctionCall(
                    name=tc.function.name,
                    args=args,
                    call_id=tc.id,
                ))

        # Assemble response parts
        parts: list[Part] = [Part(function_call=call) for call in function_calls]
        if text:
            parts.append(Part(text=text))

        # Extract grounding sources (URL citations)
        sources = _extract_sources(raw.choices or [])
        grounding = SimpleNamespace(
            grounding_chunks=[
                SimpleNamespace(web=SimpleNamespace(uri=s["url"], title=s["title"]))
                for s in sources
            ]
        ) if sources else None

        # Parse JSON if schema was requested
        parsed = None
        if config and config.response_schema and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass

        usage = getattr(raw, "usage", None)
        usage_metadata = SimpleNamespace(
            prompt_token_count=getattr(usage, "prompt_tokens", 0) or 0,
            thoughts_token_count=0,
            candidates_token_count=getattr(usage, "completion_tokens", 0) or 0,
            total_token_count=getattr(usage, "total_tokens", 0) or 0,
            cost=_extract_cost(usage),
        )

        return _Response(
            text=text,
            parsed=parsed,
            candidates=[_Candidate(Content("model", parts), grounding)],
            usage_metadata=usage_metadata,
            function_calls=function_calls,
        )

    async def generate_content_stream(
        self,
        *,
        model: str,
        contents: Any,
        config: GenerateContentConfig | None = None,
    ) -> AsyncGenerator[_Response, None]:
        """Stream chat completions. Yields partial _Response objects for text chunks.

        Function calls are accumulated and returned as a single complete chunk at the
        end — the tool loop requires complete arguments before it can execute anything.
        """
        web_search = _has_web_search(config)
        messages = _contents_to_messages(
            contents,
            system_instruction=config.system_instruction if config else None,
            web_search_hint=web_search,
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            # Ask for a final usage chunk once the stream completes …
            "stream_options": {"include_usage": True},
            # … and have OpenRouter include the real credit cost in it.
            "extra_body": {"usage": {"include": True}},
        }

        if config and config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config and config.max_output_tokens:
            kwargs["max_tokens"] = config.max_output_tokens

        function_tools = _function_tools(config)
        if function_tools:
            kwargs["tools"] = function_tools
            kwargs["tool_choice"] = "auto"

        if config and config.response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": _patch_schema(config.response_schema),
                },
            }
        elif config and config.response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        # Accumulate tool-call arguments across chunks
        tool_call_accum: dict[int, dict] = {}  # index → {id, name, arguments}

        async def iterator() -> AsyncGenerator[_Response, None]:
            nonlocal tool_call_accum
            final_usage: Any = None
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                # The final chunk (with include_usage) carries usage and no choices.
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    final_usage = chunk_usage
                for choice in chunk.choices or []:
                    delta = choice.delta

                    # Accumulate tool call fragments
                    for tc in getattr(delta, "tool_calls", None) or []:
                        idx = tc.index
                        if idx not in tool_call_accum:
                            tool_call_accum[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_call_accum[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_call_accum[idx]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_call_accum[idx]["arguments"] += tc.function.arguments

                    # Stream text chunks immediately
                    text_chunk = getattr(delta, "content", None) or ""
                    if text_chunk:
                        part = Part(text=text_chunk)
                        yield _Response(
                            text=text_chunk,
                            parsed=None,
                            candidates=[_Candidate(Content("model", [part]), None)],
                            usage_metadata=SimpleNamespace(
                                prompt_token_count=0, thoughts_token_count=0,
                                candidates_token_count=0, total_token_count=0,
                            ),
                            function_calls=[],
                        )

            # Build usage metadata from the final usage chunk (zeros if absent).
            usage_metadata = SimpleNamespace(
                prompt_token_count=getattr(final_usage, "prompt_tokens", 0) or 0,
                thoughts_token_count=0,
                candidates_token_count=getattr(final_usage, "completion_tokens", 0) or 0,
                total_token_count=getattr(final_usage, "total_tokens", 0) or 0,
                cost=_extract_cost(final_usage),
            )

            # After stream ends: emit accumulated tool calls as a final chunk
            if tool_call_accum:
                function_calls: list[FunctionCall] = []
                for tc_data in sorted(tool_call_accum.values(), key=lambda d: list(tool_call_accum.values()).index(d)):
                    arguments = tc_data.get("arguments", "{}") or "{}"
                    try:
                        args = json.loads(arguments)
                    except json.JSONDecodeError:
                        args = {}
                    function_calls.append(FunctionCall(
                        name=tc_data["name"],
                        args=args,
                        call_id=tc_data["id"],
                    ))
                parts = [Part(function_call=fc) for fc in function_calls]
                yield _Response(
                    text="",
                    parsed=None,
                    candidates=[_Candidate(Content("model", parts), None)],
                    usage_metadata=usage_metadata,
                    function_calls=function_calls,
                )
            elif final_usage is not None:
                # No tool calls — emit a usage-only terminal chunk so the agent
                # loop can still read the token counts for this round.
                yield _Response(
                    text="",
                    parsed=None,
                    candidates=[_Candidate(Content("model", []), None)],
                    usage_metadata=usage_metadata,
                    function_calls=[],
                )

        return iterator()


class OpenAICompatClient:
    """Adapter exposing the narrow legacy ``client.aio.models`` surface via OpenRouter."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/second-brain",
                "X-Title": "Second Brain",
            },
        )
        self.aio = SimpleNamespace(models=_Models(async_client))
