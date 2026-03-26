# F21: Recommendation Accuracy Tracking

## Status: Implemented (2026-03-26)

## Overview

Tracks mark-to-market performance of Portfolio Manager recommendations at 30, 90, and 180 day checkpoints. Shows win rates, average returns, and best/worst calls.

## Database

### Table: recommendation_checkpoints

New table (migration 019):
- `recommendation_id` (FK -> recommendations.id, CASCADE)
- `days_elapsed` (30, 90, 180)
- `check_date` (date when checkpoint was computed)
- `price_at_check_cents` (market price on that date)
- `return_pct` (percentage return since recommendation)
- `was_correct` (boolean — positive return for buy, negative for sell)
- Unique constraint on (recommendation_id, days_elapsed)

Checkpoints are computed lazily — only created when enough time has elapsed since the recommendation date AND a price exists for the check date.

## Backend

### GET /api/v1/recommendations/accuracy

Returns aggregated accuracy stats:
- Overall checkpoints: 30d/90d/180d with total, wins, winRate, avgReturn
- By action: buy/sell/hold breakdown per time horizon
- Best 5 and worst 5 calls with ticker, action, days, returnPct

Auto-computes missing checkpoints on each request.

### POST /api/v1/recommendations/compute-checkpoints

Manual trigger to batch-compute checkpoints. Returns count of new checkpoints created.

## Frontend

Page: `/accuracy`

- "Update Checkpoints" button for manual trigger
- Overall accuracy: 3 cards for 30d/90d/180d with win rate (color-coded), avg return, sample size
- By action breakdown table
- Best/worst calls lists with ticker links

## Notes

- Checkpoints won't populate until recommendations are at least 30 days old
- The PM started posting recommendations on ~2026-03-23, so first 30d checkpoints will appear ~2026-04-22
- Could add cron job to compute checkpoints daily (currently computed on-demand)

## Files

- `backend/alembic/versions/019_add_recommendation_checkpoints.py` — migration
- `backend/app/db/models/recommendation_checkpoints.py` — model
- `backend/app/api/v1/recommendations.py` — accuracy + compute-checkpoints endpoints
- `frontend/src/app/accuracy/page.tsx` — accuracy page
- `frontend/src/components/layout/Sidebar.tsx` — nav item under Analysis
