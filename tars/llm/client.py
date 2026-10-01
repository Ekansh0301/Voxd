"""Streaming chat against the OpenAI-compatible llama-swap endpoint."""

import json
from collections.abc import AsyncIterator

import httpx

NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


async def stream_chat(endpoint: str, model: str, messages: list[dict], **kw) -> AsyncIterator[str]:
    body = {"model": model, "messages": messages, "stream": True, **NO_THINK, **kw}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
        async with client.stream("POST", f"{endpoint}/chat/completions", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    return
                delta = json.loads(data)["choices"][0].get("delta", {})
                if text := delta.get("content"):
                    yield text


async def is_up(endpoint: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            return (await client.get(f"{endpoint}/models")).status_code == 200
    except httpx.HTTPError:
        return False
