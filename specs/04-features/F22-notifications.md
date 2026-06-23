# F22: Notification System

**Status: Implemented (Signal default, Telegram alternative) — updated 2026-06-18**
**Created: 2026-03-26**

Push notifications and a bidirectional chat bot for the Bloomvalley investment terminal. Two backends are supported and selected via `NOTIFICATION_PROVIDER`:

- **Signal** (default) — outbound and inbound via the self-hosted [signal-gateway](https://github.com/freducom/signal-gateway). Linked-device pattern, no third-party servers, messages flow through your own Signal account ("Note to Self").
- **Telegram** — outbound via the Telegram Bot API; inbound via Bot long-polling.

The event taxonomy, privacy model, and message templates below are provider-agnostic. Where wire format matters, both options are documented.

---

## 1. Architecture

### Provider abstraction

All outbound notifications pass through `backend/app/services/notifier.py`. Callers produce Telegram-HTML; the dispatcher routes to the configured backend and strips HTML to plain text when needed (Signal).

```
notify_recommendations(html) ─┐
notify_insider_*(html)        ├─► notifier.send(html) ──┬─► telegram._send_via_telegram(html)
notifier.send(html)           ─┘                        └─► signal.send(html-stripped-to-plain)
```

### Signal backend (default)

- **Outbound:** `signal-gateway-notify:8090/notify` over the shared `signal` docker network. `X-Token: $SIGNAL_NOTIFY_TOKEN`.
- **Inbound:** The signal-gateway router receives messages from your phone in "Note to Self", strips the `bv` prefix, and POSTs to `POST /api/v1/notifications/signal-webhook`. The body is `{"message": "..."}`. The router includes `X-API-Key` so the existing API-key middleware authenticates the call. The `signal-register` compose service self-registers the prefix at startup.
- **No new phone number** — bloomvalley uses your existing Signal account as a linked device via signal-gateway.

### Telegram backend

- **Outbound:** `POST https://api.telegram.org/bot<TOKEN>/sendMessage` with `parse_mode=HTML`.
- **Inbound:** Long-polling via `getUpdates` in a background task started by `app/main.py` lifespan when `NOTIFICATION_PROVIDER=telegram`. Handled by `backend/app/services/telegram_bot.py`.

### Service Location

- `backend/app/services/notifier.py` — provider dispatcher
- `backend/app/services/telegram.py` — Telegram low-level send + Telegram-specific formatted notify helpers
- `backend/app/services/telegram_bot.py` — Telegram long-poll bot
- `backend/app/services/signal.py` — Signal low-level send + HTML-to-plain
- `backend/app/services/signal_bot.py` — Signal inbound command/chat handler
- `backend/app/api/v1/notifications.py` — REST endpoints (test/send/signal-webhook)

The swarm and cron containers trigger notifications by calling `POST /api/v1/notifications/send` on the backend; the backend abstraction picks the right provider.

### Integration Points

| Source | Where | Trigger |
|---|---|---|
| Alert evaluation | `backend/app/services/alert_evaluator.py` | When price/insider/expiry alerts fire |
| Swarm completion | `analyst-swarm/swarm.py` | After `run_swarm()` finishes |
| PM recommendations | `analyst-swarm/swarm.py` | After `extract_and_post_recommendations()` |
| Pipeline failures | `backend/cron_scheduler.py` | When `trigger()` gets non-200 or exception |
| Scheduled checks | `backend/cron_scheduler.py` | New cron jobs for price moves, dividend alerts |

---

## 2. Event Types

| Event | Priority | Default |
|---|---|---|
| `recommendation_new` — PM posts BUY or SELL | HIGH | On |
| `recommendation_hold` — PM posts HOLD/WAIT | LOW | Off |
| `swarm_complete` — Swarm run finishes | MEDIUM | On |
| `swarm_failed` — Agent failures in swarm run | HIGH | On |
| `alert_triggered` — Price/insider alert fires | MEDIUM | On |
| `pipeline_failed` — Data pipeline HTTP error | HIGH | On |
| `pipeline_stale` — No successful run beyond threshold | MEDIUM | On |
| `price_significant_move` — Held position moves >5% | MEDIUM | On |
| `insider_buy_detected` — Cluster insider buying | HIGH | On |
| `dividend_exdate_approaching` — Ex-date within N days | LOW | On |
| `research_stale` — Security missing research >7 days | LOW | Off |
| `macro_regime_change` — Regime shifts | HIGH | On |
| `daily_digest` — Morning portfolio summary | LOW | Off |

### Priority Behavior

- **HIGH**: Sent immediately, even during quiet hours
- **MEDIUM**: Sent immediately during active hours, queued during quiet hours
- **LOW**: Batched into periodic digests (max 2x/day)

---

## 3. Privacy & Security

### Data Classification

| Data | Safe for Telegram? |
|---|---|
| Ticker symbols, security names | Yes (public) |
| Price levels, % changes | Yes (public) |
| Recommendation actions (BUY MSFT) | Configurable (reveals intent) |
| Portfolio value, position sizes | Never |
| Account names/types | Never |
| Tax calculations | Never |
| Pipeline/swarm status | Yes (system meta) |

### Privacy Modes

**Privacy-safe (default)**: Messages contain only public information (tickers, price changes, action counts) and system status. No trading intent revealed.

**Full detail**: Messages include recommendation actions, target prices, rationale summaries. Only if user trusts Telegram's encryption.

Global setting — not per-event-type.

### Credential Security

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`, never committed
- Bot token only in backend container — not passed to frontend, cron, or swarm
- Swarm/cron trigger notifications via backend API with `X-API-Key`
- Rate limiting: max 20 messages/minute
- Token rotation: revoke via `@BotFather /revoke`, update `.env`, restart backend

---

## 4. Configuration

### .env

```
TELEGRAM_BOT_TOKEN=           # From @BotFather
TELEGRAM_CHAT_ID=             # Your private chat ID
```

### Database Tables

**`notification_settings`** (singleton):
- `privacy_mode` (safe/full)
- `quiet_hours_start`, `quiet_hours_end` (TIME, Helsinki)
- `daily_digest_enabled`, `daily_digest_time`
- `rate_limit_per_minute` (default 20)

**`notification_event_config`**:
- `event_type` (VARCHAR UNIQUE)
- `enabled` (BOOLEAN)
- `priority` (high/medium/low)

### API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/notifications/settings` | Get global settings + event configs |
| PUT | `/api/v1/notifications/settings` | Update global settings |
| PUT | `/api/v1/notifications/events/{type}` | Toggle/configure event type |
| POST | `/api/v1/notifications/test` | Send test message |
| POST | `/api/v1/notifications/send` | Internal: send notification (swarm/cron) |

---

## 5. Message Formats

Use HTML parse_mode (simpler escaping than MarkdownV2). Max 4096 characters per message.

### New PM Recommendations

**Full:**
```
📊 <b>New PM Recommendations</b>

🟢 <b>BUY</b> MSFT — High confidence
Microsoft Corp | Target: $480 | Horizon: long
<i>Strong AI infrastructure moat, FCF yield attractive</i>

🔴 <b>SELL</b> NESTE.HE — Medium confidence
<i>Margin compression from SAF overcapacity</i>

<i>3 new recommendations posted</i>
```

**Privacy-safe:**
```
📊 <b>Analyst Swarm Complete</b>

3 new recommendations posted
• 1 buy, 1 sell, 1 hold
• 0 high-priority actions

<i>Open terminal for details</i>
```

### Swarm Run Complete
```
🤖 <b>Swarm Run Complete</b>

✅ 8/9 agents completed in 342s
❌ Failed: fixed-income-analyst

📋 3 new recommendations posted
🔄 Next run: 15:00 Helsinki
```

### Pipeline Failure
```
⚠️ <b>Pipeline Failure</b>

❌ <code>yahoo_daily_prices</code> failed
<i>HTTP 500 — Connection timeout</i>

Last success: 23:00 yesterday
```

### Insider Buy Detected

**Full:**
```
🕵️ <b>Insider Activity</b>

INVE-B.ST — 3 insider buys in 7 days
Largest: CEO, 12,500 shares
```

**Privacy-safe:**
```
🕵️ <b>Insider Activity</b>

Insider buying detected on 1 held security
<i>Open terminal for details</i>
```

### Significant Price Move

**Full:**
```
📉 <b>Price Move</b>

NESTE.HE: -7.2% today (€18.45)
```

**Privacy-safe:**
```
📉 <b>Price Alert</b>

1 held position moved >5% today
```

### Macro Regime Change
```
🌍 <b>Macro Regime Change</b>

Previous: Expansion
Current: Late Cycle
<i>Review allocation</i>
```

### Daily Digest
```
☀️ <b>Morning Briefing — 2026-03-26</b>

📊 S&P 500 +0.3%, OMXH25 -0.1%
🔔 2 active alerts
📋 3 recommendations expiring this week
💰 1 dividend ex-date (MSFT)
🕵️ Insider activity: INVE-B.ST, KESKOB.HE
📰 12 new news items

🔄 Next swarm: 07:00
```

---

## 6. Implementation Phases

### Phase 1: Core Service (MVP)

Create:
- `backend/app/services/telegram.py` — TelegramNotifier class (send, send_event, is_configured)
- `backend/app/api/v1/notifications.py` — test + send endpoints

Modify:
- `backend/app/config.py` — add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- `backend/app/api/v1/router.py` — register notifications router
- `.env.example`, `README.md`

### Phase 2: Database Preferences + Event Routing

Create:
- `backend/app/db/models/notifications.py` — NotificationSettings, NotificationEventConfig
- `backend/alembic/versions/020_add_notification_tables.py`
- `backend/app/services/telegram_templates.py` — message templates per event type

### Phase 3: Integration with Swarm + Cron

Modify:
- `analyst-swarm/swarm.py` — call notification endpoint after swarm + recommendations
- `backend/cron_scheduler.py` — call notification on pipeline failure
- `backend/app/services/alert_evaluator.py` — call notification on alert trigger

New cron jobs:
- Alert evaluation: every 15 min during market hours
- Price move check: weekdays 22:30

### Phase 4: UI Settings Page

Create:
- `frontend/src/app/notifications/page.tsx` — settings with toggles, privacy mode, quiet hours, test button
- Sidebar nav item

### Phase 5: Advanced

- Batching/digest for LOW priority events
- Rate limiting with token bucket
- `notification_log` table for delivery tracking
- Retry on failure (once after 30s)

---

## 7. Risks

- **Provider downtime**: Silent failure, logged. Caller decides whether to retry.
- **Message formatting**: HTML is the canonical wire format internally; Signal strips it (Signal renders plain text only).
- **Message length**: Telegram chunks at 4096 chars at line boundaries; Signal truncates at 4000 chars with `[...truncated]` suffix.
- **Outbound network**: Telegram needs HTTPS to `api.telegram.org`; Signal needs the shared `signal` docker network with `signal-gateway` running.
- **Auth on inbound Signal webhook**: protected by the existing `X-API-Key` middleware. The `signal-register` sidecar registers with signal-gateway router using `auth_header: {name: "X-API-Key", value: $API_KEY}`. Without that, any other container on the `signal` network could spoof commands.
- **No new dependencies**: just httpx (already available); signal-gateway is a separate compose stack.

---

## 8. Setup Instructions

### Signal (default)

1. Set up the signal-gateway stack: <https://github.com/freducom/signal-gateway>. One-time QR-link via your existing Signal account, ≈5 min.
2. Copy `NOTIFY_TOKEN` and `ROUTER_TOKEN` from `signal-gateway/.env` into bloomvalley `.env`:
   ```
   NOTIFICATION_PROVIDER=signal
   SIGNAL_NOTIFY_TOKEN=<NOTIFY_TOKEN from signal-gateway>
   SIGNAL_ROUTER_TOKEN=<ROUTER_TOKEN from signal-gateway>
   ```
3. `docker compose up -d` — the `signal-register` sidecar registers the `bv` prefix with signal-gateway's router (idempotent, retries until ready).
4. Verify outbound: `curl -H "X-API-Key: $API_KEY" -X POST http://localhost:8000/api/v1/notifications/test` → "Bloomvalley — test notification" lands in Signal Note-to-Self.
5. Verify inbound: on your phone in Note-to-Self, type `bv help` — bot replies in the same chat.

### Telegram (alternative)

1. Open Telegram, search `@BotFather`, send `/newbot`
2. Choose name ("Bloomvalley Terminal") and username
3. Copy bot token to `.env` as `TELEGRAM_BOT_TOKEN`
4. Message your bot (search username, tap Start)
5. Get chat ID: visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. Copy chat ID to `.env` as `TELEGRAM_CHAT_ID` and set `NOTIFICATION_PROVIDER=telegram`
7. `docker compose up -d backend`
8. Test: `POST /api/v1/notifications/test`
