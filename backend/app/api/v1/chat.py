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
    page_url: str = ""


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
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.160:11435"),
            "model": os.environ.get("OLLAMA_MODEL", "qwen3:32b"),
            "max_tokens": 4096,
        },
    }


def _extract_ticker_from_url(page_url: str) -> str | None:
    """Extract a ticker symbol from the page URL, if present."""
    if not page_url:
        return None
    parts = page_url.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "security":
        return parts[1].upper()
    return None


def _build_page_context(page_url: str) -> str:
    """Build a context string describing which page the user is currently viewing."""
    if not page_url or page_url == "/":
        return "The user is on the Dashboard (home page)."

    parts = page_url.strip("/").split("/")
    page_map = {
        "portfolio": "Portfolio overview",
        "holdings": "Holdings",
        "watchlist": "Watchlist",
        "security": "Security detail",
        "fundamentals": "Fundamentals screener",
        "research": "Research",
        "recommendations": "Recommendations",
        "risk": "Risk analysis",
        "macro": "Macro indicators",
        "fixed-income": "Fixed income",
        "dividends": "Dividends",
        "tax": "Tax analysis",
        "charts": "Charts",
        "heatmap": "Heatmap",
        "market": "Market overview",
        "news": "News",
        "insider": "Insider transactions",
        "earnings": "Earnings",
        "esg": "ESG scores",
        "alerts": "Alerts",
        "global-events": "Global events",
        "transactions": "Transactions",
        "import": "Data import",
    }

    section = parts[0]
    label = page_map.get(section, section.replace("-", " ").title())

    if len(parts) >= 2 and section == "security":
        ticker = parts[1].upper()
        return f"The user is viewing the Security detail page for ticker **{ticker}**. If they ask for analysis, research, or data, assume it's about {ticker} unless stated otherwise."

    return f"The user is on the {label} page ({page_url})."


async def _fetch_security_context(ticker: str) -> str:
    """Fetch live data for a security and format as context for the chat LLM."""
    _api_key = os.environ.get("API_KEY", "")
    headers = {"X-API-Key": _api_key} if _api_key else {}
    base = "http://localhost:8000/api/v1"

    # Look up security ID
    async with httpx.AsyncClient(timeout=15, base_url=base, headers=headers) as client:
        try:
            resp = await client.get(f"/securities?ticker={ticker}&limit=1")
            if resp.status_code != 200:
                return ""
            secs = resp.json().get("data", [])
            if not secs:
                return ""
            sec = secs[0]
            sec_id = sec["id"]
            sec_name = sec.get("name", ticker)
        except Exception:
            return ""

        # Fetch data in parallel
        endpoints = {
            "fundamentals": f"/fundamentals?securityId={sec_id}",
            "holdings": "/portfolio/holdings",
            "recommendations": f"/recommendations?status=active&limit=50",
            "research": f"/research/notes?securityId={sec_id}&limit=3",
            "insiders": f"/insiders/trades?securityId={sec_id}&limit=10",
            "news": f"/news?securityId={sec_id}&limit=5",
            "dividends": f"/dividends/history?securityId={sec_id}&limit=5",
        }

        results = {}
        for key, ep in endpoints.items():
            try:
                r = await client.get(ep)
                if r.status_code == 200:
                    results[key] = r.json().get("data", r.json())
            except Exception:
                pass

    # Build context text
    parts = [f"\n## Live Data for {ticker} ({sec_name})\n"]

    # Fundamentals
    funds = results.get("fundamentals", [])
    if isinstance(funds, list) and funds:
        f = funds[0] if funds else {}
    elif isinstance(funds, dict):
        f = funds
    else:
        f = {}
    if f:
        lines = []
        price = f.get("currentPriceCents")
        if price:
            lines.append(f"Current Price: €{price/100:.2f}")
        for label, key, fmt in [
            ("P/E", "peRatio", ".1f"),
            ("P/B", "priceToBook", ".1f"),
            ("ROIC", "roic", ".1%"),
            ("ROE", "roe", ".1%"),
            ("FCF Yield", "fcfYield", ".1%"),
            ("Gross Margin", "grossMargin", ".1%"),
            ("Operating Margin", "operatingMargin", ".1%"),
            ("Net Debt/EBITDA", "netDebtEbitda", ".1f"),
            ("Dividend Yield", "dividendYield", ".1%"),
        ]:
            val = f.get(key)
            if val is not None:
                lines.append(f"{label}: {val:{fmt}}")
        dcf = f.get("dcfPerShareCents")
        dcf_up = f.get("dcfUpsidePct")
        if dcf:
            lines.append(f"DCF Fair Value: €{dcf/100:.2f} (upside: {dcf_up:+.1f}%)" if dcf_up is not None else f"DCF Fair Value: €{dcf/100:.2f}")
        if f.get("dcfModelNotes"):
            lines.append(f"DCF Model: {f['dcfModelNotes']}")
        si = f.get("shortInterestPct")
        if si:
            lines.append(f"Short Interest: {si}% (squeeze risk: {f.get('shortSqueezeRisk', '?')})")
        sm = f.get("smartMoneySignal")
        if sm and sm != "neutral":
            lines.append(f"Smart Money Signal: {sm}")
        if lines:
            parts.append("**Fundamentals:**\n" + "\n".join(f"- {l}" for l in lines))

    # Holdings (filter to this security)
    holdings = results.get("holdings", [])
    if isinstance(holdings, list):
        sec_holdings = [h for h in holdings if h.get("securityId") == sec_id]
        if sec_holdings:
            h_lines = []
            for h in sec_holdings:
                acct = h.get("accountName", "?")
                qty = h.get("quantity", 0)
                val = h.get("marketValueEurCents")
                pnl = h.get("unrealizedPnlPct")
                cost = h.get("avgCostCents")
                h_lines.append(f"- {acct}: {float(qty):.0f} shares, "
                               f"value €{val/100:,.2f}, "
                               f"avg cost €{cost/100:.2f}, "
                               f"P&L {pnl:+.1f}%" if val and cost and pnl is not None else f"- {acct}: {qty} shares")
            parts.append("**Position:**\n" + "\n".join(h_lines))
        else:
            parts.append("**Position:** Not held in portfolio.")

    # Active recommendations for this security
    recs = results.get("recommendations", [])
    if isinstance(recs, list):
        sec_recs = [r for r in recs if r.get("security", {}).get("ticker") == ticker
                    or r.get("security_id") == sec_id]
        if sec_recs:
            r = sec_recs[0]
            action = r.get("action", "?").upper()
            conf = r.get("confidence", "?")
            rationale = r.get("rationale", "")
            parts.append(f"**Active Recommendation:** {action} (confidence: {conf})\n{rationale}")

    # Research notes
    notes = results.get("research", [])
    if isinstance(notes, list):
        for n in notes[:2]:
            title = n.get("title", "")
            thesis = (n.get("thesis") or "")[:1500]
            bull = n.get("bullCase") or ""
            bear = n.get("bearCase") or ""
            tags = n.get("tags", [])
            source = next((t for t in tags if t not in ("swarm", "held", "watchlist")), "analyst")
            parts.append(f"**Research ({source}):** {title}\n{thesis[:800]}")
            if bull:
                parts.append(f"Bull case: {bull[:300]}")
            if bear:
                parts.append(f"Bear case: {bear[:300]}")

    # Insider trades
    insiders = results.get("insiders", [])
    if isinstance(insiders, list) and insiders:
        i_lines = []
        for i in insiders[:5]:
            name = i.get("insiderName", "?")
            itype = i.get("transactionType", "?")
            shares = i.get("shares", "?")
            price = i.get("priceCents")
            date = (i.get("filingDate") or i.get("transactionDate") or "?")[:10]
            price_str = f" @ €{price/100:.2f}" if price else ""
            i_lines.append(f"- {date}: {name} {itype} {shares} shares{price_str}")
        parts.append("**Recent Insider Trades:**\n" + "\n".join(i_lines))

    # News
    news = results.get("news", [])
    if isinstance(news, list) and news:
        n_lines = []
        for n in news[:3]:
            title = (n.get("title") or "")[:100]
            date = (n.get("publishedAt") or "")[:10]
            n_lines.append(f"- {date}: {title}")
        parts.append("**Recent News:**\n" + "\n".join(n_lines))

    # Dividends
    divs = results.get("dividends", [])
    if isinstance(divs, list) and divs:
        d_lines = []
        for d in divs[:3]:
            ex_date = d.get("exDate", "?")
            amount = d.get("amountPerShare") or d.get("amount", "?")
            currency = d.get("currency", "EUR")
            d_lines.append(f"- Ex-date: {ex_date}, Amount: {amount} {currency}")
        parts.append("**Recent Dividends:**\n" + "\n".join(d_lines))

    context = "\n\n".join(parts)
    # Cap total context to avoid overwhelming the prompt
    if len(context) > 8000:
        context = context[:8000] + "\n\n[... data truncated]"
    return context


async def _call_claude_cli(messages: list[ChatMessage], page_url: str = "",
                           security_context: str = "") -> str:
    """Get full response from Claude CLI."""
    cfg = _get_llm_config()
    cli_cfg = cfg["claude_cli"]
    claude_bin = cli_cfg.get("binary", "claude")
    model = cli_cfg.get("model", "")

    # Build conversation: system + page context + security data + messages
    parts = [SYSTEM_PROMPT]
    if page_url:
        parts.append(f"\n\nCurrent page context: {_build_page_context(page_url)}")
    if security_context:
        parts.append(f"\n\n{security_context}")
    parts.append("\n---\n")
    for msg in messages:
        prefix = "User" if msg.role == "user" else "Assistant"
        parts.append(f"\n{prefix}: {msg.content}")
    full_prompt = "\n".join(parts)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(full_prompt)
        tmp_path = f.name

    try:
        cmd = [
            claude_bin, "-p",
            "--output-format", "text",
            "--allowedTools", "WebSearch", "WebFetch",
        ]
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


async def _stream_claude_cli(messages: list[ChatMessage], page_url: str = "",
                             security_context: str = ""):
    """Get response from Claude CLI and simulate streaming with chunked output."""
    text = await _call_claude_cli(messages, page_url, security_context)
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


async def _stream_claude_api(messages: list[ChatMessage], page_url: str = "",
                            security_context: str = ""):
    """Stream response from Claude API."""
    cfg = _get_llm_config()
    api_key = cfg["claude"]["api_key"]
    if not api_key:
        yield "Error: ANTHROPIC_API_KEY not configured."
        return

    system = SYSTEM_PROMPT
    if page_url:
        system += f"\n\nCurrent page context: {_build_page_context(page_url)}"
    if security_context:
        system += f"\n\n{security_context}"

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
                "system": system,
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


async def _stream_ollama(messages: list[ChatMessage], page_url: str = "",
                        security_context: str = ""):
    """Stream response from Ollama."""
    cfg = _get_llm_config()
    base_url = cfg["ollama"]["base_url"].rstrip("/")

    system = SYSTEM_PROMPT
    if page_url:
        system += f"\n\nCurrent page context: {_build_page_context(page_url)}"
    if security_context:
        system += f"\n\n{security_context}"

    api_messages = [
        {"role": "system", "content": system},
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
                "think": False,
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


async def _stream_response(messages: list[ChatMessage], page_url: str = ""):
    """Route to the configured LLM provider's streaming function."""
    cfg = _get_llm_config()
    provider = cfg["llm_provider"]

    # Fetch security-specific context if user is on a security page
    # or mentions a ticker in their latest message
    security_context = ""
    ticker = _extract_ticker_from_url(page_url)
    if ticker:
        try:
            security_context = await _fetch_security_context(ticker)
        except Exception as e:
            logger.warning("security_context_fetch_failed", ticker=ticker, error=str(e))

    if provider == "claude_cli":
        async for chunk in _stream_claude_cli(messages, page_url, security_context):
            yield chunk
    elif provider == "claude":
        async for chunk in _stream_claude_api(messages, page_url, security_context):
            yield chunk
    elif provider == "ollama":
        async for chunk in _stream_ollama(messages, page_url, security_context):
            yield chunk
    else:
        yield f"Error: Unknown LLM provider: {provider}"


async def _sse_generator(messages: list[ChatMessage], page_url: str = ""):
    """Generate SSE events from the LLM stream."""
    try:
        async for chunk in _stream_response(messages, page_url):
            if chunk:
                data = json.dumps({"type": "content", "text": chunk})
                yield f"data: {data}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as e:
        logger.error("chat_stream_error", error=str(e))
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"


async def get_full_response(messages: list[ChatMessage], page_url: str = "",
                           security_context: str = "") -> str:
    """Get a complete (non-streaming) LLM response. Used by Telegram bot."""
    cfg = _get_llm_config()
    provider = cfg["llm_provider"]

    # Fetch security context if on a security page and not already provided
    if not security_context:
        ticker = _extract_ticker_from_url(page_url)
        if ticker:
            try:
                security_context = await _fetch_security_context(ticker)
            except Exception:
                pass

    if provider == "claude_cli":
        return await _call_claude_cli(messages, page_url, security_context)
    else:
        # Accumulate streaming providers into full text
        chunks = []
        if provider == "claude":
            gen = _stream_claude_api(messages, page_url, security_context)
        elif provider == "ollama":
            gen = _stream_ollama(messages, page_url, security_context)
        else:
            return f"Error: Unknown LLM provider: {provider}"
        async for chunk in gen:
            chunks.append(chunk)
        return "".join(chunks)


@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    """Stream a chat response via Server-Sent Events."""
    return StreamingResponse(
        _sse_generator(body.messages, body.page_url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
