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


async def stream_turn(
    endpoint: str, model: str, messages: list[dict], tools: list[dict] | None = None, **kw
) -> AsyncIterator[tuple[str, object]]:
    """
    One assistant turn, streamed. Yields ("text", delta) as reply text arrives and,
    if the model decided to call tools, a final ("tool_calls", [{"id", "name",
    "arguments"}]) with arguments parsed from JSON (or {"_raw": str} if malformed).
    """
    body: dict = {"model": model, "messages": messages, "stream": True, **NO_THINK, **kw}
    if tools:
        body["tools"] = tools
    calls: dict[int, dict] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
        async with client.stream("POST", f"{endpoint}/chat/completions", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0].get("delta", {})
                if text := delta.get("content"):
                    yield "text", text
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc["index"], {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function", {})
                    slot["name"] += fn.get("name") or ""
                    slot["args"] += fn.get("arguments") or ""
    if calls:
        parsed: list[dict] = []
        for c in (calls[i] for i in sorted(calls)):
            try:
                args = json.loads(c["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": c["args"]}
            parsed.append(
                {"id": c["id"] or f"call_{len(parsed)}", "name": c["name"], "arguments": args}
            )
        yield "tool_calls", parsed
