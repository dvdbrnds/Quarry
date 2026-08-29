# Add "Same-Day Multiple Offers" Query to Lottery Manager

## Context

The lottery V2 system (`lottery_v2_runner.py`) can sometimes issue multiple offers to different students on the same day via manual admin actions, waitlist advances, or the repair function. We need a way to quickly see which students received offers on a particular date so we can audit what happened (e.g., the August 4th incident).

The existing duplicates report (`GET /api/lottery-v2/cycles/{cycle_id}/duplicates-report`) shows students who currently hold multiple offers in a cycle, but it doesn't filter by date and doesn't catch cases where a student received and then lost an offer on the same day.

## Requirements

### 1. New backend endpoint

Add `GET /api/lottery-v2/cycles/{cycle_id}/same-day-offers` with an optional query parameter `date` (ISO date string, e.g. `2026-08-04`). If no date is provided, default to today.

The query should find all `lottery_v2_applications` rows in the given cycle where the `offer_expires_at` was set on that date. Since there is no explicit `offered_at` column, derive the offer date from `offer_expires_at` minus `cycle.offer_window_days` (default 5). Alternatively, use `updated_at::date = date` combined with `status IN ('selected', 'accepted', 'superseded')` as a simpler heuristic -- a row that moved to one of those statuses on the target date received an offer that day.

Return:

```json
{
  "date": "2026-08-04",
  "cycle_name": "...",
  "total_offers_on_date": 15,
  "students_with_multiple": [
    {
      "email": "student@moravian.edu",
      "name": "Jane Doe",
      "offer_count": 2,
      "applications": [
        {
          "id": "...",
          "status": "accepted",
          "tier": "Resident Premium",
          "lot": "Lot A",
          "updated_at": "2026-08-04T14:22:00Z",
          "offer_expires_at": "2026-08-09T14:22:00Z"
        }
      ]
    }
  ],
  "all_offers": []
}
```

Require admin role (`require_admin()`), same as the existing duplicates report.

### 2. Frontend: date picker + button in LotteryV2Manager

In `LotteryV2Manager.tsx`, add a small UI element near the existing "Duplicates" button in the capacity/audit toolbar area. It should have:

- A date picker (Ant Design `DatePicker`) defaulting to today
- A button labeled "Same-Day Offers" that calls the new endpoint with the selected date
- Display results in a dismissable card (similar style to the existing `dupesReport` purple card), showing:
  - Total offers issued on that date
  - A highlighted section for students who received more than one offer that day, with their name, email, and the tiers/lots for each offer
  - A collapsible "All offers" table showing every offer made that day for full context

### 3. No changes to the lottery runner logic

This is a read-only audit query. Do not modify the offer, repair, or advance functions.

## Implementation notes

- Follow the same patterns as the existing `duplicates_report` endpoint and its frontend rendering in `LotteryV2Manager.tsx`
- The `updated_at` field on `lottery_v2_applications` auto-updates on any change (`onupdate=func.now()`), so filtering by `updated_at::date` combined with status is the most reliable approach
- Also include rows with status `superseded` -- these are students who had an offer that was later replaced, which is exactly the kind of thing we want to catch
- Use Ant Design components consistent with the rest of the page
- Admin-only (both admin and operator roles should NOT see this -- admin only, same as lottery management)
