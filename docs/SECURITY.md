# Security Audit — Bloomvalley Terminal

Last updated: 2026-03-24

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

#### 1. No authentication on the API

| | |
|---|---|
| **Where** | `backend/app/main.py:45-64` — no auth middleware; all routes in `backend/app/api/v1/` have no `Depends()` guards |
| **Risk** | Anyone who can reach the host has full read/write access to portfolio data, transactions, recommendations, and can trigger pipeline runs |
| **Why it matters** | Even on a home LAN, other devices (IoT, guests, compromised machines) share the network. The API also accepts destructive operations (delete transactions, close recommendations) |
| **Fix** | Add a static API key checked via FastAPI middleware on all `/api/v1/*` routes. Store the key in `.env`, inject it server-side via the Next.js rewrite so it never reaches the browser. See [Remediation](#r1-api-authentication) |

#### 2. Database exposed on host with weak default credentials

| | |
|---|---|
| **Where** | `docker-compose.yml:4-5` — `ports: "5432:5432"`; `.env` — `POSTGRES_USER=warren`, `POSTGRES_PASSWORD=warren` |
| **Risk** | Any process on the host (or LAN, depending on firewall) can connect directly to PostgreSQL with trivially guessable credentials |
| **Why it matters** | Direct DB access bypasses any future API-level auth. Full dump of portfolio, transactions, tax data |
| **Fix** | Remove the host port mapping. Services communicate over the Docker network. Generate a strong random password. See [Remediation](#r2-close-database-ports) |

#### 3. Redis exposed on host with no authentication

| | |
|---|---|
| **Where** | `docker-compose.yml:23-24` — `ports: "6379:6379"`; line 27 — no `--requirepass` |
| **Risk** | Unauthenticated Redis allows data theft, cache poisoning, and in some configurations arbitrary code execution via module loading |
| **Why it matters** | Redis is a known target for automated scanners. Even on a LAN, an IoT device running a botnet could find it |
| **Fix** | Remove the host port mapping. Add `--requirepass $(REDIS_PASSWORD)` to the command. See [Remediation](#r3-redis-authentication) |

#### 4. API keys stored in plain-text `.env`

| | |
|---|---|
| **Where** | `.env` — `FRED_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `ANTHROPIC_API_KEY` |
| **Risk** | If the host is compromised or a backup is leaked, all external API keys are exposed |
| **Why it matters** | Third-party API keys can be used to exhaust rate limits or (for Anthropic) incur costs. FRED/Alpha Vantage keys are free-tier but still personal |
| **Fix** | Acceptable for self-hosted single-user if host security is solid. For stronger posture, use Docker secrets or a secrets manager. Rotate keys periodically. Keep `.env` out of backups |

---

### HIGH

#### 5. Backend port 8000 exposed to host

| | |
|---|---|
| **Where** | `docker-compose.yml:37-38` — `ports: "8000:8000"` |
| **Risk** | Bypasses Traefik (and any future auth middleware on Traefik). Direct access to the raw API |
| **Why it matters** | Traefik is the intended entry point. Exposing the backend port creates a second, unprotected path |
| **Fix** | Remove the port mapping. Traefik reaches the backend via the Docker network. See [Remediation](#r4-remove-unnecessary-ports) |

#### 6. Frontend port 3000 exposed to host

| | |
|---|---|
| **Where** | `docker-compose.yml:54-55` — `ports: "3000:3000"` |
| **Risk** | Same as above — bypasses Traefik |
| **Fix** | Remove the port mapping if Traefik handles all external traffic |

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
- **`.env` excluded from git**: `.gitignore` correctly excludes `.env`, `backend/.env`, `frontend/.env.local`
- **Debug mode off**: SQLAlchemy `echo=False`, no debug endpoints
- **Input validation**: All API endpoints use Pydantic models
- **CORS origin locked**: Only `FRONTEND_URL` is allowed (not `*`)
- **External API keys loaded from env**: No hardcoded credentials in source code

---

## Remediation Plans

### R1: API authentication

Add a static API key validated by FastAPI middleware.

**Backend** (`backend/app/main.py`):
```python
from fastapi import Request
from fastapi.responses import JSONResponse

API_KEY = settings.API_KEY  # new field in .env

@app.middleware("http")
async def check_api_key(request: Request, call_next):
    # Allow health check without auth
    if request.url.path in ("/", "/docs", "/openapi.json"):
        return await call_next(request)
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)
```

**Frontend** — the Next.js rewrite injects the key server-side so it
never reaches the browser:

```javascript
// next.config.mjs — rewrites section
{
  source: '/api/:path*',
  destination: 'http://backend:8000/api/:path*',
  headers: [{ key: 'X-API-Key', value: process.env.API_KEY }],
}
```

**Other clients** (analyst-swarm, cron) pass `API_KEY` as an env var
and include the header in requests.

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

| Priority | Item | Effort |
|----------|------|--------|
| 1 | Close DB + Redis ports (#2, #3) | 10 min |
| 2 | Remove backend/frontend host ports (#5, #6) | 5 min |
| 3 | Strong DB + Redis passwords (#2, #3) | 10 min |
| 4 | API key middleware (#1) | 1-2 hrs |
| 5 | Traefik IP allowlist (#R5) | 10 min |
| 6 | Rate limiting on pipelines (#7) | 30 min |
| 7 | CORS tightening (#9) | 5 min |
| 8 | HTTPS for OpenInsider (#12) | 5 min |
| 9 | Container hardening (#11) | 30 min |
