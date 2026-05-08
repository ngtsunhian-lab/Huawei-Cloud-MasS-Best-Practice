#!/usr/bin/env python3
import json
import os
import time
import uuid
from typing import Any, Iterable, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


MODEL = os.environ.get("MAAS_CODEX_MODEL", "glm-5.1")
UPSTREAM_BASE_URL = os.environ.get("LITELLM_INTERNAL_BASE_URL", "http://127.0.0.1:8788/v1")
UPSTREAM_API_KEY = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("MAAS_API_KEY", "")

app = FastAPI(title="Codex Responses adapter for LiteLLM MaaS")


def response_id() -> str:
    return f"resp_{uuid.uuid4().hex}"


def item_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def normalize_input(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]

    if not isinstance(value, list):
        return [{"role": "user", "content": str(value)}]

    messages: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, str):
            messages.append({"role": "user", "content": entry})
            continue
        if not isinstance(entry, dict):
            messages.append({"role": "user", "content": str(entry)})
            continue

        role = entry.get("role", "user")
        content = entry.get("content", "")

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    part_type = part.get("type")
                    if part_type in {"input_text", "output_text", "text"}:
                        parts.append(str(part.get("text", "")))
            text = "\n".join(part for part in parts if part)
        else:
            text = str(content)

        if text:
            messages.append({"role": role, "content": text})

    return messages or [{"role": "user", "content": ""}]


def normalize_tools(value: Any) -> Optional[list[dict[str, Any]]]:
    if not isinstance(value, list):
        return None

    tools: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            tools.append(tool)
            continue
        name = tool.get("name")
        if not name:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            }
        )
    return tools or None


def build_chat_payload(body: dict[str, Any], *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": body.get("model") or MODEL,
        "messages": normalize_input(body.get("input", body.get("messages", ""))),
        "stream": stream,
    }

    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_output_tokens", "max_tokens"),
        ("max_tokens", "max_tokens"),
        ("stop", "stop"),
    ):
        if source in body and body[source] is not None:
            payload[target] = body[source]

    tools = normalize_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        if body.get("tool_choice") is not None:
            payload["tool_choice"] = body["tool_choice"]

    return payload


async def post_chat(payload: dict[str, Any], authorization: Optional[str]) -> httpx.Response:
    headers = {"Authorization": authorization or f"Bearer {UPSTREAM_API_KEY}"}
    async with httpx.AsyncClient(timeout=None) as client:
        return await client.post(
            f"{UPSTREAM_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )


def responses_payload(resp_id: str, model: str, text: str, usage: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    out_id = item_id()
    return {
        "id": resp_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": out_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "output_text": text,
        "usage": usage,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/v1/chat/completions", methods=["POST"])
async def chat_completions(request: Request, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    body = await request.json()
    upstream = await post_chat(body, authorization)
    return JSONResponse(status_code=upstream.status_code, content=upstream.json())


@app.post("/v1/responses")
async def responses(request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
    body = await request.json()
    stream = bool(body.get("stream"))
    payload = build_chat_payload(body, stream=stream)
    model = payload["model"]

    if not stream:
        upstream = await post_chat(payload, authorization)
        if upstream.status_code >= 400:
            raise HTTPException(status_code=upstream.status_code, detail=upstream.text)
        data = upstream.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        return responses_payload(response_id(), model, text, data.get("usage"))

    async def event_stream() -> Iterable[str]:
        resp_id = response_id()
        out_id = item_id()
        created_at = int(time.time())
        yield sse({"type": "response.created", "response": {"id": resp_id, "object": "response", "created_at": created_at, "status": "in_progress", "model": model, "output": []}})
        yield sse({"type": "response.output_item.added", "output_index": 0, "item": {"id": out_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}})
        yield sse({"type": "response.content_part.added", "item_id": out_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})

        text_parts: list[str] = []
        headers = {"Authorization": authorization or f"Bearer {UPSTREAM_API_KEY}"}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{UPSTREAM_BASE_URL}/chat/completions", headers=headers, json=payload) as upstream:
                if upstream.status_code >= 400:
                    detail = await upstream.aread()
                    yield sse({"type": "response.failed", "response": {"id": resp_id, "status": "failed", "error": {"message": detail.decode("utf-8", "replace")}}})
                    yield "data: [DONE]\n\n"
                    return

                async for line in upstream.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        text_parts.append(piece)
                        yield sse({"type": "response.output_text.delta", "item_id": out_id, "output_index": 0, "content_index": 0, "delta": piece})

        text = "".join(text_parts)
        yield sse({"type": "response.output_text.done", "item_id": out_id, "output_index": 0, "content_index": 0, "text": text})
        yield sse({"type": "response.content_part.done", "item_id": out_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": text, "annotations": []}})
        yield sse({"type": "response.output_item.done", "output_index": 0, "item": {"id": out_id, "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": []}]}})
        yield sse({"type": "response.completed", "response": responses_payload(resp_id, model, text)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
