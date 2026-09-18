# Business Rules — Quarry Parking

Last updated: 2026-09-18

**Before changing any of these rules in code, update this file FIRST.**

## Lot Access Schedules

Access rules are defined as schedule arrays in `backend/app/routers/lots.py` and enforced in `backend/app/services/access.py`.

### Commuter Evening Lots (designation: FSC)

- **Weekday daytime (07:00–16:00):** Faculty/staff and visitors only.
- **Weekday evenings (16:00–07:00):** All permit holders.
- **Weekends (all day):** All permit holders.

### Commuter Lots (designation: C, PC)

- **Weekday daytime (07:00–16:00):** Commuter, faculty/staff, visitors, and student guests.
- **Weekday evenings (16:00–07:00):** All permit holders.
- **Weekends (all day):** All permit holders.

### Resident Lots (designation: RS, PR)

- **Weekday daytime (07:00–16:00):** Residents (north premium, north guaranteed, steel field, south premium, south guaranteed, south standalone), faculty/staff, visitors, and student guests.
- **Weekday evenings (16:00–07:00):** All permit holders.
- **Weekends (all day):** All permit holders.

### Key Rule: "After 4:00 PM"

- "After 4:00 PM" means >= 16:00.
- Midnight (00:00) counts as after hours (falls in the 16:00–07:00 window).
- Faculty/staff permits have 24/7 access to all assigned lots.
- Extended Premium Commuter has full-time access to FS, FSC, and all street lots.

## Lottery Eligibility

- Freshmen (class year = current academic year + 4) are excluded from residential parking lotteries by default.
- Each lottery cycle can override this with its own "Allow Freshmen" toggle.
- Commuter permits are NOT subject to the freshmen restriction.
- Lottery draw is time-based only (auto_draw_days). There is no threshold trigger.
- Application timing does not affect lottery outcome — all applications submitted before the deadline are weighted equally by seniority.

## Permit Lifecycle

- All permits expire June 30 annually.
- Renewal emails offer one-click Renew or Decline.
- Decline soft-deletes the permit (recoverable by admin).
- Permit numbers follow QPS format.

## Fee Exemptions and Discounts

- RA status: checked via SIS stored procedure first, falls back to fee_exempt_roster CSV.
- ABSN discount: checked via SIS AccelNursing flag first, falls back to discount_roster/Okta groups.
- Fee-exempt students pay $0. Discount students pay full price minus the configured discount amount.

## Ticket / Citation Rules

- Ticket numbers are sequential: CIT-00001 format.
- QR code on printed ticket links to the payment portal.
- Payment URL format must match between BirdDog (generator) and Hounddog (resolver).

## Sponsor Permits

- Deletion uses POST /revoke (not HTTP DELETE — WAF blocks it).
- Revocation is soft-delete (recoverable).
