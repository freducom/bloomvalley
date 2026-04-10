# Security Audit — Bloomvalley Terminal

Last updated: 2026-04-10

This document describes known security issues in the current deployment,
why each matters, and how to fix it. Intended audience: anyone deploying
this project or reviewing its security posture.

## Context

Bloomvalley is a **single-user, self-hosted** personal finance terminal.
It runs behind Traefik on a home network. There is no authentication,
no multi-tenancy, and no public exposure by design. The threat model is:

- An attacker on the same LAN (or with DNS access) can reach all services
- A compromised container can access secrets and other services
- Leaked `.env` exposes all API keys and database credentials

---

## Findings

### CRITICAL

#### 1. ~~No authentication on the API~~ — REMEDIATED

| | |
|---|---|
| **Where** | `backend/app/main.py` — API key middleware on all `/api/*` routes |
| **Status** | **Fixed (2026-03-26).** Static API key (`API_KEY` in `.env`) checked via `X-API-Key` header. Next.js middleware (`frontend/src/middleware.ts`) injects the header server-side on rewrite — the key never reaches the browser. Cron and analyst-swarm pass the key via env var. Health endpoint exempt for Docker healthchecks. Auth is optional — empty `API_KEY` disables it for local dev. |
| **Traefik change** | All traffic now routes through the frontend (single router) so the middleware always injects the key. The separate `bloomvalley-api` Traefik router pointing directly to port 8000 was removed. |

#### 2. ~~Database exposed on host with weak default credentials~~ — REMEDIATED

| | |
|---|---|
| **Where** | `docker-compose.yml` — db service; `.env` — `POSTGRES_PASSWORD` |
| **Status** | **Fixed (2026-04-10).** Host port mapping removed — PostgreSQL only reachable via Docker internal network. Password changed from `warren` to a 32-char random token. Existing data volume updated via `ALTER USER`. |

#### 3. ~~Redis exposed on host with no authentication~~ — REMEDIATED

| | |
|---|---|
| **Where** | `docker-compose.yml` — redis service; `.env` — `REDIS_PASSWORD` |
| **Status** | **Fixed (2026-04-10).** Host port mapping removed. `--requirepass` added to redis-server command. Password stored in `.env` as `REDIS_PASSWORD`. `REDIS_URL` updated with auth. |

#### 4. API keys stored in plain-text `.env`

| | |
|---|---|
| **Where** | `.env` — `FRED_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `ANTHROPIC_API_KEY` |
| **Risk** | If the host is compromised or a backup is leaked, all external API keys are exposed |
| **Why it matters** | Third-party API keys can be used to exhaust rate limits or (for Anthropic) incur costs. FRED/Alpha Vantage keys are free-tier but still personal |
| **Fix** | Acceptable for self-hosted single-user if host security is solid. For stronger posture, use Docker secrets or a secrets manager. Rotate keys periodically. Keep `.env` out of backups |

---

### HIGH

#### 5. ~~Backend port 8000 exposed to host~~ — REMEDIATED

| | |
|---|---|
| **Where** | `docker-compose.yml` — backend service |
| **Status** | **Fixed (2026-04-10).** Port bound to `127.0.0.1:8000` — only reachable from localhost, not from LAN. |

#### 6. Frontend port 3000 exposed to host — PARTIALLY MITIGATED

| | |
|---|---|
| **Where** | `docker-compose.yml` — frontend service, `ports: "3000:3000"` |
| **Status** | Port remains open because Traefik routes to `172.17.0.1:3000` (host bridge IP). Cannot bind to `127.0.0.1` without moving both services to a shared Docker network. Risk is mitigated by API key auth — the frontend injects the key server-side, so direct port access sees the same protected API. |
| **Future fix** | Join bloomvalley services to the `proxy` network and route via Docker DNS instead of host IP. |

#### 7. Pipeline endpoints allow unauthenticated DoS

| | |
|---|---|
| **Where** | `backend/app/api/v1/pipelines.py` — `POST /api/v1/pipelines/{name}/run` |
| **Risk** | Anyone can trigger all data pipelines repeatedly, hammering external APIs and consuming resources |
| **Why it matters** | Could exhaust API rate limits (Alpha Vantage has 25 calls/day on free tier), cause IP bans, or spike CPU/memory |
| **Fix** | Solved by API authentication (#1). Additionally, add rate limiting via `slowapi` or a simple in-memory cooldown per pipeline |

#### 8. Analyst-swarm mounts `~/.claude` credentials

| | |
|---|---|
| **Where** | `docker-compose.yml:102-103` — `${HOME}/.claude:/root/.claude:ro` and `${HOME}/.claude.json:/root/.claude.json:ro` |
| **Risk** | Claude CLI auth tokens are available inside the analyst-swarm container. A supply-chain compromise of the swarm image or its dependencies could exfiltrate them |
| **Why it matters** | These credentials may grant access to a paid Anthropic subscription |
| **Fix** | Acceptable if using `claude_cli` provider and the image is built locally. If switching to API-key provider, mount only `ANTHROPIC_API_KEY` as an env var instead of the entire `.claude` directory |

---

### MEDIUM

#### 9. CORS allows credentials with wildcard methods/headers

| | |
|---|---|
| **Where** | `backend/app/main.py:53-59` — `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]` |
| **Risk** | If `FRONTEND_URL` is misconfigured or DNS is hijacked, an attacker page could make credentialed cross-origin requests |
| **Fix** | Restrict `allow_methods` to `["GET", "POST", "PUT", "DELETE"]` and `allow_headers` to `["Content-Type"]`. Low priority since single-origin |

#### 10. No request size limits

| | |
|---|---|
| **Where** | `backend/app/main.py` — no explicit body size limit; `backend/app/api/v1/imports.py` — `ParseRequest.text` has no `max_length` |
| **Risk** | Large payloads could cause memory exhaustion |
| **Fix** | Add `max_length` to the Pydantic field. Optionally configure a body size limit in the ASGI server |

#### 11. No container security hardening

| | |
|---|---|
| **Where** | `docker-compose.yml` — all services |
| **Risk** | Containers run as root, no capability restrictions, no read-only filesystem |
| **Fix** | Add `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, and `user:` fields where possible. Lower priority for a personal tool |

#### 12. OpenInsider scraped over HTTP

| | |
|---|---|
| **Where** | `backend/app/pipelines/openinsider.py:106,183` — `http://openinsider.com/...` |
| **Risk** | Data in transit is unencrypted. A network-level attacker could inject false insider trading data |
| **Fix** | Change to `https://openinsider.com/...` |

---

### LOW / INFORMATIONAL

#### 13. No Content Security Policy headers

The frontend does not set CSP headers. Low risk for a single-user tool
but good practice to prevent XSS if any user-generated content is rendered.

#### 14. Database backups stored unencrypted

Backup SQL dumps (e.g. `backup_*.sql`) in the project root contain all
portfolio data in plain text. Ensure backups are stored outside the
project directory and encrypted at rest.

#### 15. No CSRF protection

Not currently exploitable because there are no session cookies.
Becomes relevant if session-based auth is added (#1).

---

### Things that are already done right

- **SQL injection**: All database queries use SQLAlchemy parameterized queries or `text()` with named bindings — no string interpolation
- **API authentication**: Static API key (`X-API-Key` header) on all `/api/*` routes, injected server-side by Next.js middleware
- **`.env` excluded from git**: `.gitignore` correctly excludes `.env`, `backend/.env`, `frontend/.env.local`
- **Debug mode off**: SQLAlchemy `echo=False`, no debug endpoints
- **Input validation**: All API endpoints use Pydantic models
- **CORS origin locked**: Only `FRONTEND_URL` is allowed (not `*`)
- **External API keys loaded from env**: No hardcoded credentials in source code

---

## Remediation Plans

### R1: API authentication — DONE

Implemented 2026-03-26. See finding #1 for details.

- `backend/app/config.py` — `API_KEY` setting
- `backend/app/main.py` — `check_api_key` middleware
- `frontend/src/middleware.ts` — injects `X-API-Key` on `/api/*` rewrites
- `backend/cron_scheduler.py` — reads `API_KEY` from env, sends header
- `analyst-swarm/swarm.py` — reads `API_KEY` from env, sends header on all backend calls
- `docker-compose.yml` — passes `API_KEY` to frontend and analyst-swarm
- Traefik config — single router through frontend (removed direct backend route)

### R2: Close database ports

```yaml
# docker-compose.yml — remove ports, keep expose for internal access
db:
  # ports:            # REMOVED
  #   - "5432:5432"   # REMOVED
  expose:
    - "5432"
```

Generate a strong password:
```bash
openssl rand -base64 32
```

Update `.env`:
```
POSTGRES_PASSWORD=<generated-password>
```

For local DB admin access, use `docker compose exec db psql -U warren`.

### R3: Redis authentication

```yaml
# docker-compose.yml
redis:
  command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
  # ports:            # REMOVED
  #   - "6379:6379"   # REMOVED
  expose:
    - "6379"
```

Update `.env`:
```
REDIS_PASSWORD=<generated-password>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

### R4: Remove unnecessary host ports

After closing DB and Redis ports, also remove backend and frontend
host port mappings if all traffic goes through Traefik:

```yaml
backend:
  # ports:            # REMOVED — Traefik reaches via Docker network
  #   - "8000:8000"
  expose:
    - "8000"

frontend:
  # ports:            # REMOVED — Traefik reaches via Docker network
  #   - "3000:3000"
  expose:
    - "3000"
```

### R5: Traefik IP allowlist (defense in depth)

Add to `traefik/data/dynamic/bloomvalley.yml`:
```yaml
http:
  middlewares:
    bloomvalley-ipallow:
      ipAllowList:
        sourceRange:
          - "192.168.1.0/24"
  routers:
    bloomvalley:
      middlewares:
        - bloomvalley-ipallow
```

---

## Implementation priority

| Priority | Item | Effort | Status |
|----------|------|--------|--------|
| ~~1~~ | ~~API key middleware (#1)~~ | ~~1-2 hrs~~ | **Done** |
| 2 | Close DB + Redis ports (#2, #3) | 10 min | |
| 3 | Remove backend/frontend host ports (#5, #6) | 5 min | |
| 4 | Strong DB + Redis passwords (#2, #3) | 10 min | |
| 5 | Traefik IP allowlist (#R5) | 10 min | |
| 6 | Rate limiting on pipelines (#7) | 30 min | |
| 7 | CORS tightening (#9) | 5 min | |
| 8 | HTTPS for OpenInsider (#12) | 5 min | |
| 9 | Container hardening (#11) | 30 min | |
