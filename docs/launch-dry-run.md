# Launch Dry-Run — End-to-End Test Script

**Environment:** Stripe TEST mode (`sk_test_...` / `pk_test_...`)  
**Test Card:** `4242 4242 4242 4242` (any future exp, any CVC, any ZIP)  
**Pre-requisite:** App is deployed and accessible. Admin is logged in.

---

## 1. Verify Environment

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Open admin dashboard, navigate to Settings → Data Management | Page loads |
| 1.2 | Call `GET /api/admin/preflight` (or check container startup logs) | All checks pass or only show WARNs for intentionally-missing optional services |
| 1.3 | Confirm Stripe key shows as "TEST key" in preflight (not live during dry-run) | `STRIPE_SECRET_KEY: warn — Using TEST key` |

---

## 2. Lottery Application Flow

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Log in as a test student (Okta test account or auth-disabled mode) | Lands on `/parking` |
| 2.2 | Select "Commuter" campus path | Commuter permit tiers load (Regular Undergrad, Regular Grad, Premium) |
| 2.3 | Enter Class Year, plate (`TEST001`), phone, check SMS opt-in | Fields accept input |
| 2.4 | Click "Continue" | Step changes to "choose" — shows available commuter tiers with Buy buttons |
| 2.5 | **Do NOT buy yet.** Switch to "North" path and enter same info | Step changes to "rank" — shows lottery tiers to rank |
| 2.6 | Rank at least one tier, click Submit | Application created. Status = "pending". DB: `lottery_v2_applications` has new row with `status=pending` |

---

## 3. Run Lottery Draw

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Open admin Permits → Lottery Manager (V2 tab) | Shows current cycle |
| 3.2 | Click "Run Draw" (or call `POST /api/lottery-v2/draw`) | Draw completes. At least one applicant shows status "selected" |
| 3.3 | Check logs or `GET /api/admin/notification-health` | Lottery offer emails attempted. If SMTP configured: emails_sent > 0. If not: emails_failed count matches selected count + clear ERROR logs |
| 3.4 | DB: verify `lottery_v2_applications` has rows with `status=selected`, `offer_expires_at` set | Confirm with admin UI or direct DB query |

---

## 4. Accept Offer → Pay via Stripe

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Log in as the selected test student | `/parking` shows "You've been selected" with Accept button |
| 4.2 | Click "Accept" | Redirects to Stripe Checkout (test mode) |
| 4.3 | Complete payment with test card `4242 4242 4242 4242` | Stripe shows success, redirects to `/parking?accepted=<id>&session_id=<cs_xxx>` |
| 4.4 | Verify success page | Toast: "Payment confirmed — your permit has been issued!" |
| 4.5 | DB: `permits` table | New row: `permit_type` matches selected tier, `status=active`, `plates=['TEST001']` |
| 4.6 | DB: `payments` table | New row: `payment_type=lottery_v2_permit`, `stripe_payment_id` populated |
| 4.7 | DB: `lottery_v2_applications` | Row status changed to `accepted` |

---

## 5. Direct Commuter Permit Purchase

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Log in as a different test student | Lands on `/parking` |
| 5.2 | Select "Commuter" → enter plate `TEST002`, class year, phone | Tier selection shown |
| 5.3 | Click "Buy" on any available commuter tier | Redirects to Stripe Checkout |
| 5.4 | Complete payment with test card | Redirects to `/parking?purchased=true&session_id=<cs_xxx>` |
| 5.5 | Verify toast message | "Payment confirmed — your permit has been issued!" |
| 5.6 | DB: `permits` table | New active permit with `permit_type` matching chosen commuter tier |

---

## 6. Pay-and-Close-Tab Variant (Reconciliation Test)

> **This is the critical gap test.**

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | Log in as another test student, start a commuter permit purchase | Stripe Checkout opens |
| 6.2 | Complete payment with test card `4242 4242 4242 4242` | Stripe confirms payment |
| 6.3 | **IMMEDIATELY close the browser tab** — do NOT wait for redirect | Tab closed. Student never hit success page. |
| 6.4 | Wait 5 minutes (or manually trigger: `POST /api/payments/reconcile-permits?lookback_hours=1` as admin) | Reconciler runs |
| 6.5 | Check response from reconcile endpoint | `fulfilled: 1` (or `tickets_fulfilled` for ticket variant) |
| 6.6 | DB: `permits` table | Permit created with correct plate, type, status=active |
| 6.7 | DB: `payments` table | Payment record exists with correct stripe_payment_id |
| 6.8 | Run reconcile again | `already_fulfilled` incremented, `fulfilled: 0` — idempotent |

---

## 7. iPad Sync Shows Permit

| Step | Action | Expected |
|------|--------|----------|
| 7.1 | Open the iPad app (BirdDog) or call `GET /api/sync/permits` | Returns permit list |
| 7.2 | Find the permit created in step 5 or 6 by plate | Permit present with correct type, lot assignment, active status |

---

## 8. Issue a Ticket

| Step | Action | Expected |
|------|--------|----------|
| 8.1 | Open admin Dashboard → Tickets or use iPad to issue | Issue form available |
| 8.2 | Create ticket: plate `TESTPAY`, violation `unauthorized_permit`, lot `X` | Ticket created, status = `issued` |
| 8.3 | DB: `tickets` table | New row with `status=issued`, `plate=TESTPAY` |
| 8.4 | Note the ticket UUID (visible in admin ticket detail or URL) | Save for next steps |

---

## 9. Pay Ticket via QR Code / Direct Link

| Step | Action | Expected |
|------|--------|----------|
| 9.1 | Open `/pay/<ticket-uuid>` in an incognito/unauthenticated browser | Ticket loads showing plate, violation, fine amount |
| 9.2 | Click "Pay Now" | Redirects to Stripe Checkout |
| 9.3 | Complete payment with test card | Redirects to `/pay/success?session_id=<cs_xxx>` |
| 9.4 | Success page shows "Payment Confirmed" | ✓ |
| 9.5 | DB: `tickets` table | Row status changed to `paid` |
| 9.6 | DB: `payments` table | New row: `payment_type=ticket_payment`, `ticket_id` populated |

---

## 10. Ticket Pay-and-Close-Tab Variant

| Step | Action | Expected |
|------|--------|----------|
| 10.1 | Create another test ticket (plate `TESTPAY2`) | Ticket with status `issued` |
| 10.2 | Open `/pay/<new-ticket-uuid>`, click "Pay Now" | Stripe Checkout |
| 10.3 | Complete payment, then **close the tab immediately** | Tab closed before redirect |
| 10.4 | Wait 5 min or trigger: `POST /api/payments/reconcile-permits?lookback_hours=1` | Reconciler runs |
| 10.5 | Check response | `tickets_fulfilled: 1` |
| 10.6 | DB: ticket status = `paid`, payment record created | ✓ |
| 10.7 | Run reconcile again | Idempotent — `already_fulfilled` incremented |

---

## 11. Plate Lookup Removed (Verify)

| Step | Action | Expected |
|------|--------|----------|
| 11.1 | Open `/pay` with no ticket ID (just the bare URL) | Page shows "Scan the QR code on your parking ticket" — no search input |
| 11.2 | Call `GET /api/payments/lookup?plate=TEST` directly | Returns `410 Gone` with message about QR codes |
| 11.3 | Call `GET /api/payments/lookup/<valid-uuid>` | Returns ticket data (this is the QR code target — still works) |

---

## Rollback Plan

If any critical step fails on Monday morning:

1. **Stripe in test mode?** Switch to live keys in Coolify env vars → redeploy
2. **Permits not creating?** Manually run `POST /api/payments/reconcile-permits?lookback_hours=4`
3. **Emails not sending?** Check `GET /api/admin/notification-health` and fix SMTP config
4. **Reconciler not running?** It auto-runs every 5 min. Check container logs for `quarry.stripe_reconciler`
5. **Nuclear option:** Pause Stripe checkout URLs (toggle `is_purchasable_online=false` in admin) until issue is diagnosed
