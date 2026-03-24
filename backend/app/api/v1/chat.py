"""Chat endpoint — streams LLM responses via SSE using the same provider as analyst-swarm."""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter()

SYSTEM_PROMPT = """You are Bloomvalley Assistant, an AI investment advisor built into a personal Bloomberg-style terminal.

You help with:
- Portfolio analysis and allocation strategy
- Security research (stocks, bonds, ETFs, crypto)
- Finnish tax optimization (osakesaastotili, PS-sopimus, kapitalisaatiosopimus)
- Macro-economic analysis
- Risk management and diversification
- Technical and fundamental analysis

Investment philosophy context:
- Munger total return + Boglehead hybrid (~60-70% index core, ~30-40% conviction satellite)
- 15-year horizon targeting fixed income by age 60
- Finnish investor (30% capital gains up to 30k EUR, 34% above)
- P/B is a core metric; accumulating (ACC) ETFs preferred
- Always consider both bull AND bear cases
- Broker: Nordnet (Finland)

Keep responses concise and actionable. Use markdown formatting. When discussing specific securities, mention relevant metrics."""


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def _get_llm_config() -> dict:
    """Build LLM config from environment variables (same as analyst-swarm)."""
    return {
        "llm_provider": os.environ.get("LLM_PROVIDER", "claude_cli"),
        "claude": {
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
            "max_tokens": 4096,
        },
        "claude_cli": {
            "binary": "claude",
            "model": os.environ.get("CLAUDE_CLI_MODEL", ""),
        },
        "ollama": {
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "llama3.1:70b"),
            "max_tokens": 4096,
        },
    }


async def _call_claude_cli(messages: list[ChatMessage]) -> str:
    """Get full response from Claude CLI."""
    cfg = _get_llm_config()
    cli_cfg = cfg["claude_cli"]
    claude_bin = cli_cfg.get("binary", "claude")
    model = cli_cfg.get("model", "")

    # Build conversation: system + messages
    parts = [SYSTEM_PROMPT, "\n---\n"]
    for msg in messages:
        prefix = "User" if msg.role == "user" else "Assistant"
        parts.append(f"\n{prefix}: {msg.content}")
    full_prompt = "\n".join(parts)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(full_prompt)
        tmp_path = f.name

    try:
        cmd = [claude_bin, "-p", "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        with open(tmp_path, "rb") as f:
            stdin_data = f.read()

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=600,
        )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            logger.error("claude_cli_error", rc=proc.returncode, stderr=err[:500])
            return f"Error: Claude CLI failed (rc={proc.returncode})"

        return stdout.decode().strip()
    finally:
        os.unlink(tmp_path)


async def _stream_claude_cli(messages: list[ChatMessage]):
    """Get response from Claude CLI and simulate streaming with chunked output."""
    text = await _call_claude_cli(messages)
    if not text:
        return

    # Simulate streaming: emit in word-sized chunks for typewriter effect
    chunk = ""
    for char in text:
        chunk += char
        # Emit at word boundaries or newlines for natural pacing
        if char in (" ", "\n", "\t") and len(chunk) >= 3:
            yield chunk
            chunk = ""
            await asyncio.sleep(0.01)
    if chunk:
        yield chunk


async def _stream_claude_api(messages: list[ChatMessage]):
    """Stream response from Claude API."""
    cfg = _get_llm_config()
    api_key = cfg["claude"]["api_key"]
    if not api_key:
        yield "Error: ANTHROPIC_API_KEY not configured."
        return

    api_messages = [{"role": m.role, "content": m.content} for m in messages]

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": cfg["claude"]["model"],
                "max_tokens": cfg["claude"]["max_tokens"],
                "system": SYSTEM_PROMPT,
                "messages": api_messages,
                "stream": True,
            },
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield f"Error: API returned {resp.status_code}: {body.decode()[:200]}"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta["text"]
                except json.JSONDecodeError:
                    pass


async def _stream_ollama(messages: list[ChatMessage]):
    """Stream response from Ollama."""
    cfg = _get_llm_config()
    base_url = cfg["ollama"]["base_url"].rstrip("/")

    api_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *[{"role": m.role, "content": m.content} for m in messages],
    ]

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json={
                "model": cfg["ollama"]["model"],
                "messages": api_messages,
                "stream": True,
            },
        ) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if "message" in event and "content" in event["message"]:
                        yield event["message"]["content"]
                except json.JSONDecodeError:
                    pass


async def _stream_response(messages: list[ChatMessage]):
    """Route to the configured LLM provider's streaming function."""
    cfg = _get_llm_config()
    provider = cfg["llm_provider"]

    if provider == "claude_cli":
        async for chunk in _stream_claude_cli(messages):
            yield chunk
    elif provider == "claude":
        async for chunk in _stream_claude_api(messages):
            yield chunk
    elif provider == "ollama":
        async for chunk in _stream_ollama(messages):
            yield chunk
    else:
        yield f"Error: Unknown LLM provider: {provider}"


async def _sse_generator(messages: list[ChatMessage]):
    """Generate SSE events from the LLM stream."""
    try:
        async for chunk in _stream_response(messages):
            if chunk:
                data = json.dumps({"type": "content", "text": chunk})
                yield f"data: {data}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as e:
        logger.error("chat_stream_error", error=str(e))
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"


@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    """Stream a chat response via Server-Sent Events."""
    return StreamingResponse(
        _sse_generator(body.messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
