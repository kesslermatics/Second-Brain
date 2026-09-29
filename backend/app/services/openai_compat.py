# OpenAI Responses API adapter for legacy internal service contracts.
# OpenAI Responses API adapter for the legacy internal service contracts.
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI


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
    """Marker mapped to OpenAI's built-in web_search tool."""


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


# Existing services import ``types``; keep the compatibility surface local to us.
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


def _get(value: Any, name: str, default: Any = None) -> Any:
    return getattr(value, name, default) if not isinstance(value, dict) else value.get(name, default)


def _response_tools(config: GenerateContentConfig | None) -> list[dict]:
    tools: list[dict] = []
    for tool in (config.tools or []) if config else []:
        if tool.web_search is not None:
            tools.append({"type": "web_search"})
        for declaration in tool.function_declarations or []:
            tools.append({
                "type": "function",
                "name": declaration.name,
                "description": declaration.description,
                "parameters": declaration.parameters,
                "strict": False,
            })
    return tools


def _part_to_input(part: Part) -> dict | None:
    if part.text is not None:
        return {"type": "input_text", "text": part.text}
    if part.function_call is not None:
        return {
            "type": "input_text",
            "text": f"Das Modell hat das Werkzeug {part.function_call.name} angefordert.",
        }
    if part.function_response is not None:
        return {
            "type": "input_text",
            "text": "Werkzeug-Ergebnis für " + part.function_response["name"] + ":\n" + json.dumps(
                part.function_response["response"], ensure_ascii=False, default=str
            ),
        }
    if part.data is not None:
        encoded = base64.b64encode(part.data).decode("ascii")
        mime = part.mime_type or "application/octet-stream"
        data_url = f"data:{mime};base64,{encoded}"
        if mime.startswith("image/"):
            return {"type": "input_image", "image_url": data_url}
        return {"type": "input_file", "filename": "upload", "file_data": data_url}
    return None


def _contents_to_input(contents: str | list[Content] | list[str]) -> list[dict]:
    if isinstance(contents, str):
        return [{"role": "user", "content": [{"type": "input_text", "text": contents}]}]
    result: list[dict] = []
    for content in contents:
        if isinstance(content, Part):
            converted = _part_to_input(content)
            if converted:
                result.append({"role": "user", "content": [converted]})
            continue
        if isinstance(content, str):
            result.append({"role": "user", "content": [{"type": "input_text", "text": content}]})
            continue
        parts = [converted for part in content.parts if (converted := _part_to_input(part))]
        if parts:
            role = "assistant" if content.role == "model" else "user"
            if role == "assistant":
                for part in parts:
                    if part["type"] == "input_text":
                        part["type"] = "output_text"
            result.append({"role": role, "content": parts})
    return result


def _extract_sources(response: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for output in _get(response, "output", []) or []:
        for content in _get(output, "content", []) or []:
            for annotation in _get(content, "annotations", []) or []:
                if _get(annotation, "type") != "url_citation":
                    continue
                url = _get(annotation, "url", "") or ""
                if url:
                    sources.append({"title": _get(annotation, "title", "") or url, "url": url})
    seen: set[str] = set()
    return [source for source in sources if not (source["url"] in seen or seen.add(source["url"]))][:8]


def _patch_schema(schema: dict) -> dict:
    """Recursively add 'additionalProperties': false to every object node.

    OpenAI's structured-output mode requires this on every object in the schema,
    including nested ones. Our existing schemas were written for Gemini which does
    not have this requirement, so we normalise them here rather than touching each
    schema definition individually.
    """
    import copy
    schema = copy.deepcopy(schema)

    def _walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
            for prop in (node.get("properties") or {}).values():
                _walk(prop)
        elif node.get("type") == "array":
            _walk(node.get("items"))
        # handle anyOf / oneOf / allOf
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in node.get(key) or []:
                _walk(sub)

    _walk(schema)
    return schema



    def __init__(self, client: AsyncOpenAI):
        self._client = client

    async def generate_content(self, *, model: str, contents: Any, config: GenerateContentConfig | None = None) -> _Response:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": _contents_to_input(contents),
        }
        if config and config.system_instruction:
            kwargs["instructions"] = config.system_instruction
        if config and config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config and config.max_output_tokens:
            kwargs["max_output_tokens"] = config.max_output_tokens
        tools = _response_tools(config)
        if tools:
            kwargs["tools"] = tools
        if config and config.response_schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "structured_response",
                    "strict": True,
                    "schema": _patch_schema(config.response_schema),
                }
            }

        raw = await self._client.responses.create(**kwargs)
        text = _get(raw, "output_text", "") or ""
        function_calls: list[FunctionCall] = []
        for output in _get(raw, "output", []) or []:
            if _get(output, "type") == "function_call":
                arguments = _get(output, "arguments", "{}") or "{}"
                try:
                    args = json.loads(arguments)
                except json.JSONDecodeError:
                    args = {}
                function_calls.append(FunctionCall(
                    name=_get(output, "name", ""), args=args, call_id=_get(output, "call_id"),
                ))
        parts: list[Part] = [Part(function_call=call) for call in function_calls]
        if text:
            parts.append(Part(text=text))
        sources = _extract_sources(raw)
        grounding = SimpleNamespace(
            grounding_chunks=[SimpleNamespace(web=SimpleNamespace(uri=s["url"], title=s["title"])) for s in sources]
        ) if sources else None
        parsed = None
        if config and config.response_schema and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass
        usage = _get(raw, "usage")
        usage_metadata = SimpleNamespace(
            prompt_token_count=_get(usage, "input_tokens", 0) or 0,
            thoughts_token_count=_get(usage, "reasoning_tokens", 0) or 0,
            candidates_token_count=_get(usage, "output_tokens", 0) or 0,
            total_token_count=_get(usage, "total_tokens", 0) or 0,
        )
        return _Response(
            text=text, parsed=parsed, candidates=[_Candidate(Content("model", parts), grounding)],
            usage_metadata=usage_metadata, function_calls=function_calls,
        )

    async def generate_content_stream(self, *, model: str, contents: Any, config: GenerateContentConfig | None = None) -> AsyncGenerator[_Response, None]:
        # The Responses API tool protocol requires complete function-call arguments.
        # Emit one complete normalized chunk; ordinary text streaming is exposed via
        # ai_service.generate_stream below.
        response = await self.generate_content(model=model, contents=contents, config=config)

        async def iterator() -> AsyncGenerator[_Response, None]:
            yield response

        return iterator()


class OpenAICompatClient:
    """Adapter exposing the narrow, legacy ``client.aio.models`` surface."""

    def __init__(self, api_key: str):
        async_client = AsyncOpenAI(api_key=api_key)
        self.aio = SimpleNamespace(models=_Models(async_client))
