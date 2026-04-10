# Security Audit — Bloomvalley Terminal

Last updated: 2026-04-10

This document describes known security issues in the current deployment,
why each matters, and how to fix it. Intended audience: anyone deploying
this project or reviewing its security posture.

## Context

Bloomvalley is a **single-user, self-hosted** personal finance terminal.
It runs behind Traefik on a home network. There is no public exposure by
design. The threat model is:

- An attacker on the same LAN (or with DNS access) can reach exposed services
- A compromised container can access secrets and other services
- Leaked `.env` exposes all API keys and database credentials

---

## Findings Summary

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | CRITICAL | No authentication on the API | **REMEDIATED** (2026-03-26) |
| 2 | CRITICAL | Database exposed on host with weak credentials | **REMEDIATED** (2026-04-10) |
| 3 | CRITICAL | Redis exposed on host with no authentication | **REMEDIATED** (2026-04-10) |
| 4 | CRITICAL | API keys stored in plain-text `.env` | Accepted risk |
| 5 | HIGH | Backend port 8000 exposed to host | **REMEDIATED** (2026-04-10) |
| 6 | HIGH | Frontend port 3000 exposed to host | Partially mitigated |
| 7 | HIGH | Pipeline endpoints allow unauthenticated DoS | **REMEDIATED** by #1 |
| 8 | HIGH | Analyst-swarm mounts `~/.claude` credentials | Accepted risk |
| 9 | MEDIUM | CORS allows wildcard methods/headers | Open |
| 10 | MEDIUM | No request size limits | **REMEDIATED** (2026-04-10) |
| 11 | MEDIUM | No container security hardening | Open |
| 12 | MEDIUM | OpenInsider scraped over HTTP | Open |
| 13 | LOW | No Content Security Policy headers | Open |
| 14 | LOW | Backup SQL dump in project directory | Open |
| 15 | LOW | No CSRF protection | Not applicable |

---

## CRITICAL

#### 1. ~~No authentication on the API~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed (2026-03-26).** Static API key (`API_KEY` in `.env`) checked via `X-API-Key` header on all `/api/*` routes. Next.js middleware injects the header server-side — the key never reaches the browser. Cron and analyst-swarm pass the key via env var. Health endpoint exempt for Docker healthchecks. |
| **Traefik** | All traffic routes through the frontend (single router). The separate backend Traefik router was removed. |

#### 2. ~~Database exposed on host with weak default credentials~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed (2026-04-10).** Host port mapping removed — PostgreSQL only reachable via Docker internal network. Password changed from `warren` to a 32-char random token. Existing data volume updated via `ALTER USER`. Access via `docker compose exec -T db psql -U warren -d warren` only. |

#### 3. ~~Redis exposed on host with no authentication~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed (2026-04-10).** Host port mapping removed. `--requirepass` added to redis-server command with a 22-char random token. `REDIS_URL` updated with auth credentials. |

#### 4. API keys stored in plain-text `.env`

| | |
|---|---|
| **Where** | `.env` — `FRED_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `ANTHROPIC_API_KEY`, `API_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` |
| **Risk** | If the host is compromised or a backup is leaked, all credentials are exposed |
| **Status** | **Accepted risk.** Standard for self-hosted single-user deployment. `.env` is gitignored. For stronger posture, use Docker secrets or a secrets manager. Rotate keys periodically. |

---

## HIGH

#### 5. ~~Backend port 8000 exposed to host~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed (2026-04-10).** Port bound to `127.0.0.1:8000` — only reachable from localhost, not from LAN. Internal Docker communication unaffected. |

#### 6. Frontend port 3000 exposed to host — PARTIALLY MITIGATED

| | |
|---|---|
| **Where** | `docker-compose.yml` — `ports: "3000:3000"` |
| **Status** | Port remains open because Traefik routes to `172.17.0.1:3000` (host bridge IP). Cannot bind to `127.0.0.1` without moving both services to a shared Docker network. Risk mitigated by API key auth — direct port access sees the same protected API. |
| **Future fix** | Join bloomvalley services to the `proxy` network and route via Docker DNS. |

#### 7. ~~Pipeline endpoints allow unauthenticated DoS~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed by #1 (2026-03-26).** All `/api/*` routes require `X-API-Key` header — pipeline endpoints return 401 without a valid key. The pipeline runner also prevents concurrent runs of the same pipeline (`_active_runs` set). |

#### 8. Analyst-swarm mounts `~/.claude` credentials

| | |
|---|---|
| **Where** | `docker-compose.yml` — `${HOME}/.claude:/root/.claude` and `${HOME}/.claude.json:/root/.claude.json` (both backend and analyst-swarm) |
| **Risk** | Claude CLI auth tokens are available inside containers. A supply-chain compromise of dependencies could exfiltrate them. |
| **Status** | **Accepted risk.** Required for `claude_cli` provider (company subscription). Mounts are not read-only — Claude CLI needs write access for token refresh. Image is built locally from trusted source. |
| **Future fix** | Switch to API-key auth (`ANTHROPIC_API_KEY` env var) instead of CLI token mount. |

---

## MEDIUM

#### 9. CORS allows wildcard methods/headers

| | |
|---|---|
| **Where** | `backend/app/main.py` — `allow_methods=["*"]`, `allow_headers=["*"]` |
| **Risk** | If `FRONTEND_URL` is misconfigured or DNS is hijacked, an attacker page could make cross-origin requests with arbitrary methods/headers. |
| **Status** | Open. Origin is correctly locked to `FRONTEND_URL` (not `*`). Low risk for single-origin deployment. |
| **Fix** | Restrict to `allow_methods=["GET", "POST", "PUT", "DELETE"]` and `allow_headers=["Content-Type", "X-API-Key"]`. |

#### 10. ~~No request size limits~~ — REMEDIATED

| | |
|---|---|
| **Status** | **Fixed (2026-04-10).** Global 100KB body size limit via middleware (returns 413 for oversized requests). Pydantic `max_length` on largest fields: import paste text (50KB), research note thesis (65KB), bull/bear/base cases (10KB each), note title (500 chars). |

#### 11. No container security hardening

| | |
|---|---|
| **Where** | `docker-compose.yml` — all services run as root with full capabilities |
| **Status** | Open. Low priority for a personal tool on a home network. |
| **Fix** | Add `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, and `user:` fields where possible. |

#### 12. OpenInsider scraped over HTTP

| | |
|---|---|
| **Where** | `backend/app/pipelines/openinsider.py:106,183` — `http://openinsider.com/...` |
| **Risk** | Data in transit is unencrypted. A MITM could inject false insider trading data. |
| **Status** | Open. |
| **Fix** | Change `http://` to `https://` (site supports HTTPS). |

---

## LOW / INFORMATIONAL

#### 13. No Content Security Policy headers

The frontend does not set CSP headers. Low risk for a single-user tool
but good practice to prevent XSS if any user-generated content is rendered.

#### 14. Backup SQL dump in project directory

A 20MB backup file (`backup_20260323_1545.sql`) exists in the project root
containing all portfolio data in plain text. Should be moved outside the
project directory and encrypted at rest.

#### 15. ~~No CSRF protection~~ — NOT APPLICABLE

API uses header-based authentication (`X-API-Key`), not session cookies.
CSRF attacks require cookie-based auth to be exploitable. This finding
is not applicable to the current architecture.

---

## Things that are already done right

- **SQL injection**: All queries use SQLAlchemy parameterized queries or `text()` with named bindings
- **API authentication**: Static API key (`X-API-Key`) on all `/api/*` routes, injected server-side by Next.js middleware
- **`.env` excluded from git**: `.gitignore` correctly excludes `.env`, `backend/.env`, `frontend/.env.local`
- **Debug mode off**: SQLAlchemy `echo=False`, no debug endpoints exposed
- **Input validation**: All API endpoints use Pydantic models with type checking
- **CORS origin locked**: Only `FRONTEND_URL` is allowed (not `*`)
- **External API keys loaded from env**: No hardcoded credentials in source code
- **Database ports closed**: PostgreSQL and Redis only reachable via Docker internal network
- **Strong credentials**: Database and Redis use randomly generated passwords (32-char and 22-char)
- **Backend localhost-only**: Port 8000 bound to `127.0.0.1`, not accessible from LAN
- **Pipeline concurrency guard**: Same pipeline cannot run concurrently (`_active_runs` set)
- **Request size limits**: Global 100KB body limit via middleware, field-level `max_length` on large text inputs

---

## Remediation History

| Date | Items | Description |
|------|-------|-------------|
| 2026-03-26 | #1, #7 | API key middleware on all routes. Pipeline endpoints now require auth. |
| 2026-04-10 | #2, #3, #5, #10 | Closed DB/Redis ports, strong passwords, backend localhost-only, request size limits. |
