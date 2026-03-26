# F20: Analyst Consensus View

## Status: Implemented (2026-03-26)

## Overview

Shows how the 9 AI analyst agents agree or disagree on each security, surfacing conflicts between the Research Analyst's verdict and the Portfolio Manager's recommendation.

## Backend

### GET /api/v1/research/consensus

For each tracked security (holdings + watchlists):
- Gathers all research_notes grouped by agent tag
- Gets the latest active recommendation from the PM
- Extracts the Research Analyst's verdict from thesis text (`**BUY**`, `**AVOID**`, `**WAIT**`, `**HOLD**`)
- Detects conflicts (e.g., PM says BUY but Research Analyst says AVOID)

Returns per-security: pmAction, pmConfidence, researchVerdict, moatRating, agentCoverage (N/9), hasConflict, conflictDetails, per-agent breakdown.

Sorted by: conflicts first, then lowest coverage.

## Frontend

Page: `/consensus`

- Summary: total securities, conflict count
- Filters: All, Conflicts, Low Coverage (<3 agents)
- Table: Security, PM Action (badge), Research Verdict (badge), Moat, Coverage (N/9), Status (Conflict/Aligned)
- Expandable rows: grid of 9 agent cards showing which agents have notes and their verdicts

## Conflict Detection

Currently detects:
- PM recommends BUY but Research Analyst says AVOID
- PM recommends SELL but Research Analyst says BUY

Future: could add technical-analyst signal conflicts, risk-manager warnings.

## Files

- `backend/app/api/v1/research.py` — `GET /consensus` endpoint
- `frontend/src/app/consensus/page.tsx` — consensus page
- `frontend/src/components/layout/Sidebar.tsx` — nav item under Analysis
