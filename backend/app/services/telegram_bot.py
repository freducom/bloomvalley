"""Bidirectional Telegram bot — receives messages and responds with LLM-powered answers.

Uses long polling to receive messages, the same LLM pipeline as the web chat,
and Redis for conversation history.
"""

import asyncio
import json
import os
import re

import httpx
import structlog

from app.services import telegram

logger = structlog.get_logger()

# Ticker detection patterns
_TICKER_PATTERNS = [
    re.compile(r"\$([A-Z][A-Z0-9]{0,5})\b"),                          # $MSFT
    re.compile(r"\b([A-Z][A-Z0-9]{0,5}(?:[.-][A-Z]{1,3})?\.(?:HE|ST|DE|BR|L|PA))\b"),  # NOKIA.HE, INVE-B.ST
    re.compile(r"(?:analyze|research|look at|check|what about)\s+([A-Za-z][A-Za-z0-9.-]{0,10})", re.I),
]

# Markdown to Telegram HTML conversion patterns
_MD_CONVERSIONS = [
    # Code blocks first (before inline)
    (re.compile(r"```[\w]*\n([\s\S]*?)```"), r"<pre>\1</pre>"),
    # Inline code
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    # Bold (** or __)
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"__(.+?)__"), r"<b>\1</b>"),
    # Italic (* or _) — but not inside HTML tags
    (re.compile(r"(?<![<\w])\*([^*]+?)\*(?![>\w])"), r"<i>\1</i>"),
    # Links
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
    # Headings → bold
    (re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE), r"<b>\1</b>"),
    # Strikethrough
    (re.compile(r"~~(.+?)~~"), r"<s>\1</s>"),
]

# Common short words that are NOT tickers
_TICKER_BLACKLIST = {"I", "A", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO",
                     "IF", "IN", "IS", "IT", "MY", "NO", "OF", "OK", "ON", "OR",
                     "SO", "TO", "UP", "US", "WE", "AI", "PM", "EU", "UK", "ALL",
                     "AND", "ARE", "BUT", "CAN", "DID", "FOR", "GET", "GOT", "HAS",
                     "HAD", "HER", "HIM", "HIS", "HOW", "ITS", "LET", "MAY", "NEW",
                     "NOT", "NOW", "OLD", "OUR", "OUT", "OWN", "RUN", "SAY", "SHE",
                     "THE", "TOO", "TRY", "USE", "WAY", "WHO", "WHY", "YES", "YET",
                     "YOU", "BUY", "ETF", "P&L", "DCF", "EUR", "USD", "GBP", "SEK",
                     "ACC", "NAV", "FFO", "DDM", "EPS", "ROE", "FCF"}


class TelegramBot:
    """Bidirectional Telegram bot with LLM-powered chat."""

    def __init__(self, token: str, chat_id: str, redis):
        self.token = token
        self.allowed_chat_id = str(chat_id)
        self.redis = redis
        self._offset = 0
        self._api_key = os.environ.get("API_KEY", "")
        self._headers = {"X-API-Key": self._api_key} if self._api_key else {}
        self._base_url = "http://localhost:8000/api/v1"

    async def start_polling(self):
        """Long-polling loop — runs forever as a background task."""
        logger.info("telegram_bot_started", chat_id=self.allowed_chat_id)

        # Small delay to let the backend fully start
        await asyncio.sleep(5)

        while True:
            try:
                updates = await telegram.get_updates(self._offset, timeout=30)
                for update in updates:
                    self._offset = update["update_id"] + 1
                    await self._process_update(update)
            except asyncio.CancelledError:
                logger.info("telegram_bot_stopped")
                return
            except Exception as e:
                logger.error("telegram_poll_error", error=str(e))
                await asyncio.sleep(5)

    async def _process_update(self, update: dict):
        """Process a single Telegram update."""
        msg = update.get("message")
        if not msg:
            return

        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()

        # Security: only respond to the configured user
        if chat_id != self.allowed_chat_id:
            return

        if not text:
            return

        # Route to command or chat handler
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower().split("@")[0]  # strip @botname suffix
            args = parts[1] if len(parts) > 1 else ""
            await self._handle_command(chat_id, cmd, args)
        else:
            await self._handle_message(chat_id, text)

    # ── Slash Commands ──

    async def _handle_command(self, chat_id: str, cmd: str, args: str):
        """Handle a slash command."""
        handlers = {
            "/help": self._cmd_help,
            "/start": self._cmd_help,
            "/portfolio": self._cmd_portfolio,
            "/brief": self._cmd_brief,
            "/status": self._cmd_status,
            "/clear": self._cmd_clear,
            "/analyze": self._cmd_analyze,
        }

        handler = handlers.get(cmd)
        if handler:
            await handler(chat_id, args)
        else:
            await telegram.send_reply(chat_id, f"Unknown command: {cmd}\nType /help for available commands.")

    async def _cmd_help(self, chat_id: str, args: str):
        text = (
            "<b>Bloomvalley Bot Commands</b>\n\n"
            "/portfolio — Portfolio summary\n"
            "/brief — Latest analyst brief\n"
            "/analyze TICKER — Quick security analysis\n"
            "/status — System health\n"
            "/clear — Clear conversation history\n"
            "/help — This message\n\n"
            "Or just type a message to chat!"
        )
        await telegram.send_reply(chat_id, text)

    async def _cmd_portfolio(self, chat_id: str, args: str):
        await telegram.send_chat_action(chat_id)
        try:
            async with httpx.AsyncClient(timeout=15, base_url=self._base_url, headers=self._headers) as client:
                resp = await client.get("/portfolio/summary")
                if resp.status_code != 200:
                    await telegram.send_reply(chat_id, "Failed to fetch portfolio summary.")
                    return
                d = resp.json().get("data", {})

            total = d.get("totalValueEurCents", 0) / 100
            cost = d.get("totalCostEurCents", 0) / 100
            cash = d.get("totalCashEurCents", 0) / 100
            pnl = d.get("unrealizedPnlPct", 0)
            count = d.get("holdingsCount", 0)

            alloc = d.get("allocation", {})
            alloc_total = d.get("totalValueEurCents", 1) or 1
            alloc_lines = []
            for cls, val in sorted(alloc.items(), key=lambda x: x[1], reverse=True):
                pct = val / alloc_total * 100
                alloc_lines.append(f"  {cls}: {pct:.1f}%")

            text = (
                f"<b>Portfolio Summary</b>\n\n"
                f"Total: <b>{total:,.0f} EUR</b> ({count} holdings)\n"
                f"Cost basis: {cost:,.0f} EUR\n"
                f"Cash: {cash:,.0f} EUR\n"
                f"P&amp;L: {pnl:+.1f}%\n\n"
                f"<b>Allocation:</b>\n" + "\n".join(alloc_lines)
            )
            await telegram.send_reply(chat_id, text)
        except Exception as e:
            await telegram.send_reply(chat_id, f"Error: {e}")

    async def _cmd_brief(self, chat_id: str, args: str):
        await telegram.send_chat_action(chat_id)
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            date_str = datetime.now(ZoneInfo("Europe/Helsinki")).strftime("%Y-%m-%d")

            # Try to find the latest brief for today
            async with httpx.AsyncClient(timeout=10, base_url=self._base_url, headers=self._headers) as client:
                for brief_type in ["evening", "midday", "morning", "weekend"]:
                    resp = await client.get(f"/notifications/brief-summary/{date_str}/{brief_type}")
                    if resp.status_code == 200:
                        data = resp.json().get("data", {})
                        summary = data.get("summary", "")
                        if summary:
                            header = telegram._BRIEF_HEADERS.get(brief_type, brief_type)
                            emoji = telegram._BRIEF_EMOJIS.get(brief_type, "")
                            text = f"{emoji} <b>{header} — {date_str}</b>\n\n{telegram._escape(summary)}"
                            await telegram.send_reply(chat_id, text)
                            return

            await telegram.send_reply(chat_id, "No brief available for today yet.")
        except Exception as e:
            await telegram.send_reply(chat_id, f"Error: {e}")

    async def _cmd_status(self, chat_id: str, args: str):
        await telegram.send_chat_action(chat_id)
        try:
            async with httpx.AsyncClient(timeout=10, base_url=self._base_url, headers=self._headers) as client:
                # Swarm status
                swarm_resp = await client.get("/swarm/status")
                swarm = swarm_resp.json().get("data", {}) if swarm_resp.status_code == 200 else {}

                # Pipeline status
                pipe_resp = await client.get("/pipelines")
                pipes = pipe_resp.json().get("data", []) if pipe_resp.status_code == 200 else []

            swarm_status = swarm.get("status", "unknown")
            swarm_agent = swarm.get("agent", "")
            swarm_info = f"{swarm_status}"
            if swarm_agent:
                swarm_info += f" ({swarm_agent})"

            pipe_lines = []
            for p in pipes[:10]:
                name = p.get("name", "?")
                last = (p.get("lastRunAt") or "never")[:16]
                status = p.get("status", "?")
                pipe_lines.append(f"  {name}: {status} ({last})")

            text = (
                f"<b>System Status</b>\n\n"
                f"Swarm: {swarm_info}\n\n"
                f"<b>Pipelines:</b>\n" + "\n".join(pipe_lines)
            )
            await telegram.send_reply(chat_id, text)
        except Exception as e:
            await telegram.send_reply(chat_id, f"Error: {e}")

    async def _cmd_clear(self, chat_id: str, args: str):
        key = f"bloomvalley:tg_history:{chat_id}"
        if self.redis:
            await self.redis.delete(key)
        await telegram.send_reply(chat_id, "Conversation history cleared.")

    async def _cmd_analyze(self, chat_id: str, args: str):
        ticker = args.strip().upper()
        if not ticker:
            await telegram.send_reply(chat_id, "Usage: /analyze TICKER\nExample: /analyze MSFT")
            return
        # Route to the chat handler with an analysis prompt
        await self._handle_message(chat_id, f"Give me a comprehensive analysis of {ticker}")

    # ── Chat Message Handling ──

    async def _handle_message(self, chat_id: str, text: str):
        """Handle a regular text message — full LLM chat flow."""
        # Send typing indicator (keep refreshing during LLM call)
        typing_task = asyncio.create_task(self._keep_typing(chat_id))

        try:
            # Detect tickers in the message
            tickers = await self._detect_tickers(text)

            # Fetch security context for the first detected ticker
            security_context = ""
            if tickers:
                from app.api.v1.chat import _fetch_security_context
                try:
                    security_context = await _fetch_security_context(tickers[0])
                except Exception:
                    pass

            # Load conversation history from Redis
            history = await self._get_history(chat_id)

            # Add user message
            history.append({"role": "user", "content": text})

            # Call LLM
            from app.api.v1.chat import get_full_response, ChatMessage
            messages = [ChatMessage(role=m["role"], content=m["content"]) for m in history]
            response = await get_full_response(messages, security_context=security_context)

            # Save assistant response to history
            history.append({"role": "assistant", "content": response})
            await self._save_history(chat_id, history)

            # Convert markdown to Telegram HTML and send
            html_response = self._md_to_telegram_html(response)
            await telegram.send_reply(chat_id, html_response)

        except Exception as e:
            logger.error("telegram_chat_error", error=str(e))
            await telegram.send_reply(chat_id, f"Sorry, something went wrong: {e}")
        finally:
            typing_task.cancel()

    async def _keep_typing(self, chat_id: str):
        """Send typing action every 4 seconds until cancelled."""
        try:
            while True:
                await telegram.send_chat_action(chat_id)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    # ── Ticker Detection ──

    async def _detect_tickers(self, text: str) -> list[str]:
        """Detect ticker symbols in a message, validated against the securities DB."""
        candidates = set()
        for pattern in _TICKER_PATTERNS:
            for match in pattern.finditer(text):
                ticker = match.group(1).upper()
                if ticker not in _TICKER_BLACKLIST and len(ticker) >= 2:
                    candidates.add(ticker)

        if not candidates:
            return []

        # Validate against securities database
        validated = []
        async with httpx.AsyncClient(timeout=10, base_url=self._base_url, headers=self._headers) as client:
            for ticker in candidates:
                try:
                    resp = await client.get(f"/securities?ticker={ticker}&limit=1")
                    if resp.status_code == 200:
                        secs = resp.json().get("data", [])
                        if secs:
                            validated.append(ticker)
                except Exception:
                    pass

        return validated

    # ── Conversation History (Redis) ──

    async def _get_history(self, chat_id: str) -> list[dict]:
        """Load conversation history from Redis."""
        if not self.redis:
            return []
        key = f"bloomvalley:tg_history:{chat_id}"
        try:
            raw = await self.redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return []

    async def _save_history(self, chat_id: str, history: list[dict]):
        """Save conversation history to Redis (max 20 messages, 24h TTL)."""
        if not self.redis:
            return
        key = f"bloomvalley:tg_history:{chat_id}"
        # Keep last 20 messages
        trimmed = history[-20:]
        try:
            await self.redis.set(key, json.dumps(trimmed), ex=86400)
        except Exception:
            pass

    # ── Markdown → Telegram HTML ──

    @staticmethod
    def _md_to_telegram_html(text: str) -> str:
        """Convert markdown to Telegram-compatible HTML."""
        # First escape HTML entities in the raw text
        # But preserve any existing HTML-like content from the LLM
        # We handle this by converting markdown patterns

        # Handle code blocks first — protect from other conversions
        code_blocks = []
        def _save_code_block(m):
            code_blocks.append(m.group(1))
            return f"\x00CODE{len(code_blocks) - 1}\x00"

        text = re.sub(r"```[\w]*\n([\s\S]*?)```", _save_code_block, text)

        inline_codes = []
        def _save_inline_code(m):
            inline_codes.append(m.group(1))
            return f"\x00INLINE{len(inline_codes) - 1}\x00"

        text = re.sub(r"`([^`]+)`", _save_inline_code, text)

        # Escape HTML entities in the remaining text
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Apply markdown conversions
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
        # Italic
        text = re.sub(r"(?<![<\w])\*([^*]+?)\*(?![>\w])", r"<i>\1</i>", text)
        # Links
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        # Headings → bold
        text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
        # Strikethrough
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

        # Restore code blocks
        for i, code in enumerate(code_blocks):
            escaped_code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            text = text.replace(f"\x00CODE{i}\x00", f"<pre>{escaped_code}</pre>")

        for i, code in enumerate(inline_codes):
            escaped_code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            text = text.replace(f"\x00INLINE{i}\x00", f"<code>{escaped_code}</code>")

        return text
