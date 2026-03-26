# F19: Research Coverage Dashboard

## Status: Implemented (2026-03-26)

## Overview

Dashboard showing which securities in the portfolio and watchlists have been analysed by the research analyst, how fresh the analysis is, and where coverage gaps exist.

## Backend

### GET /api/v1/research/coverage

Cross-references all securities from holdings_snapshot + watchlist_items against research_notes table.

Returns per-security:
- `staleness`: "fresh" (<3 days), "stale" (3-7 days), "very_stale" (>7 days), "missing" (never analysed)
- `hasAnalystNote`: boolean — has a note tagged `research-analyst`
- `hasTechnicalNote`: boolean — has a note tagged `technical`
- `noteCount`: total active research notes
- `isInPortfolio` / `isOnWatchlist`: boolean

Summary: total, fresh, stale, veryStale, missing counts.

Sorted by staleness (missing first), then ticker.

## Frontend

Page: `/coverage`

- Summary cards: total, fresh, stale, very stale, missing (color-coded)
- Filter buttons: All, Portfolio, Watchlist Only, Stale, Missing
- Table: Security, Type, Source (Held/WL badges), Analyst (Y/-), Technical (Y/-), Notes count, Last Research date + age, Status badge

## Files

- `backend/app/api/v1/research.py` — `GET /coverage` endpoint
- `frontend/src/app/coverage/page.tsx` — coverage page
- `frontend/src/components/layout/Sidebar.tsx` — nav item under Analysis
