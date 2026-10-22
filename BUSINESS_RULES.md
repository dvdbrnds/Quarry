# Business Rules — Quarry Parking

Last updated: 2026-10-16

**Before changing any of these rules in code, update this file FIRST.**

## Office Roles

- Operators (Quarry-Staff) run day-to-day work: create, edit, cancel, renew, and bulk-change permits; convert vehicle tags; approve vehicle requests; manage classification overrides; place and remove registration holds.
- Admin-only: lottery cycles, permit type and violation type setup, enforcement settings, finance (revenue, refunds, exports, bursar import), backups/restore, duplicate merges, renewal campaigns, appeals committee membership.

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
- Who can self-register a faculty/staff vehicle: anyone in an Okta faculty/staff group (checked against the Okta directory when the sign-in token doesn't list the group — some accounts sign in with a cut-down group list), OR with an office Faculty/Staff classification override, OR who has ever been issued a faculty/staff permit (active, expired, or removed), OR whom Jenzabar marks as an employee (unless Jenzabar also shows them as a current resident/commuter student).
- On sign-in, employees go to the faculty/staff parking page and students to the student page. A person who is both is treated as a student only while they are a current student: a class year marks someone current through May 31 of that year (later years always), or Jenzabar shows them as a current resident/commuter. Jenzabar keeps the last housing flag after graduation, so the Jenzabar flag is ignored for employees whom Okta lists as graduated (Okta_All_Students_Graduated_Within_One_Year). An office Faculty/Staff classification override always makes someone an employee (and a Resident/Commuter override a student). Past student permits, applications, or lottery entries do not make someone a current student. Recent graduates who now work at Moravian are employees. The same rule decides which page office staff see when they view as (impersonate) someone.
- A person's faculty/staff vehicles share one permit. Removing a vehicle removes only that plate; the permit is removed only when its last plate is.
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
- Admin impersonation is view-only for citations: a plate lookup on My Citations while impersonating shows matches but never links them to the impersonated student.
- The Pay page (plate lookup and "my tickets") lists every payable citation: issued, overdue, past_due, escalated, appealed, and pending_payment. pending_payment covers abandoned Stripe checkouts and upheld/denied appeals; it must stay payable.
- When an officer tickets a plate whose permit is valid for the lot on the ticket (or that is flagged Never Ticket), BirdDog re-checks at submit and requires a written reason before it will issue. The reason is stored on the ticket and shown under the "may be legally parked" warning. Warnings and moving violations are exempt.
- Owner mailing addresses are entered as separate fields (street number and name, optional apt/unit, city, state, ZIP) and must be a well-formed US address: house number + street name (or PO Box), letters-only city, valid two-letter state, 5-digit ZIP or ZIP+4. The server rejects anything else. This is a format check, not a postal lookup.
- The bulk "Print Notices" button in Mail Notices prints letters only for pending citations that have an owner name and an address that passes the format check; the rest are skipped and show "No address"/"Invalid address" in the list. "Mark Printed as Mailed" marks only those same citations, recording the address on file. Printing is enabled only after all photos have loaded.
- Printing a single letter (Print for Mail) saves the entered owner name and address to the ticket, which propagates to all tickets for that plate.
- If a pending ticket has no owner address, Mail Notices uses the most recent owner name/address saved on another ticket for the same plate. Addresses on file in other layouts (no commas, spelled-out state, apartment numbers) are split into fields automatically; ones that still fail the format check show as "Invalid address" with the text on file.
- "Print for Mail" (office staff, per ticket; available in the ticket details and on each row of the Mail Notices list) prints a letter-size citation notice from the Moravian University Parking Authority for a #10 window envelope: the registered owner's name and address (looked up by MUPD and entered under Registered Owner), all citation details including GPS coordinates (lat, long) when recorded, the evidence photo, and a payment QR code and link. Payment is online only: no mail-in instructions or return stub. Printing does not charge any fee. Staff confirm afterwards to record it as mailed (date and address).
- Evidence photo orientation is fixed in Quarry, never in BirdDog (changing capture orientation in BirdDog breaks plate scanning). Orientation varies by device, so the Print for Mail letter opens with a "Flip photo" button (on-screen only) that staff use before printing, and each evidence photo on the Appeals Committee voting page has a "Flip" button. Flipping is on-screen only: nothing is saved and the ticket view, case report Print, and stored photo are unchanged.

## Escalation (Conduct Referral + Registration Hold)

Implemented in `backend/app/services/escalation.py`.

- Unpaid = any status except paid, voided, resolved_permit, warning, and only tickets with a fine above $0. Warnings never count toward a referral or hold, even after an appeal changes their status.
- At 3+ unpaid tickets (configurable thresholds), a student gets a conduct referral and a registration hold (Jenzabar stored procedure).
- The hold is removed only when unpaid tickets drop below the threshold (payment, void, or approved appeal).
- On removal Quarry calls the Jenzabar flag procedure (`Mor_CUS_Set_Parking_Ticket_Flag`, flag N) when it has an open hold record, or when Jenzabar's live check (`Mor_CUS_Active_TK_Hold`, code TK) shows an active parking hold that Quarry didn't place.
- The "Registration Hold Triggered" email to the parking office is sent after Quarry calls Jenzabar and states the real result: hold sent, Jenzabar refused it, or no Moravian ID on file (place by hand).
- Admins and operators can look up any student by name, email, or Moravian ID (Tickets page, "Registration Holds" tab, and the Conduct page) to see the Quarry hold, Jenzabar hold, and unpaid count, and send the hold (Y) or removal (N) flag by hand. Placing a hold by hand also opens a Quarry hold record if none exists, and works even under the ticket threshold (staff confirm first). Students are found through their own permits and through vehicle tags tied to them (see the vehicle tag rule below). Conduct officers can look up but not place or remove. Every manual placement and removal is logged with who did it.
- "Find holds to clear" on the Conduct page reads every active parking hold in Jenzabar and lists students Quarry knows who are under the threshold; an admin or operator can remove them all at once. Holds on IDs Quarry has no permit for are listed for manual review, never cleared automatically.
- Resolving a conduct case in the Conduct Portal closes the referral only. It never clears tickets or the hold.
- Tickets count toward a student when the plate is on one of their real permits.
- Holds only ever apply to a real person (Okta sub, Moravian ID, or email). Placeholder values stored in `student_id` — visitor permit metadata (`company_name:...|...`) and legacy-import tags (`plate_state:XX`) — never create, count toward, or lift a hold. Older holds filed under placeholders are listed under Tickets → Enforcement Audit.
- Vehicle tags act like permits (except they are unpaid and may have no lots): their tickets count toward the owner's holds, balances, notices, and lookups as soon as the tag is tied to a student. A tag is tied to a student when (a) staff verified the owner via "Verify owner" in the Conduct Portal, (b) the tag has a Moravian ID, or (c) the tag was created on or after Oct 12, 2026 and has an email. Tags created before Oct 12, 2026 with only an email still need "Verify owner" — before that date BirdDog's student search could put the wrong student's email on a tag. A tag is matched to the student by verified owner, Moravian ID, or email, including the Moravian ID or email on that student's own permit, so permit and tag tickets add up under one person.
- Verifying a tag owner immediately applies the registration hold if the student is at or over the threshold. It does not open a new conduct referral.
- Hold exemptions (`hold_exemptions` table, by plate or email) block new registration holds until they expire. When an exemption starts, existing holds for matching students are lifted in Quarry and Jenzabar. When it expires, students still at or over the threshold get the hold back automatically.
- Current exemption: the 180 plates on the Oct 16, 2026 unsent-citation contact list (citation email outage, Sep 18 to Oct 15) are exempt through Oct 26, 2026 11:59 PM ET.

## Citation Policy v2 (Timeline, Late Fees, Barnacle)

Implemented in `backend/app/services/citation_policy/`. Every number below is a setting on Enforcement Settings, not hard-coded.

**Rollout**
- Nothing changes until an admin sets the policy effective date. Citations issued on or after that date (America/New_York) are `v2`.
- Citations issued before it are `legacy`. They never get retroactive fees. They stay on the old 5/10-day status flow until the legacy resolution deadline, then enter the v2 timeline as if issued on the deadline date.
- Once the legacy deadline is set, everyone with an unpaid legacy citation gets one rollout notice explaining the deadline.
- Only parking citations with a fine above $0 are on the timeline. Warnings and moving violations are not.

**Timeline** (calendar days from issuance, counted as *effective elapsed days*, which skip paused time)
- Day 0 issued. Due (paid or appealed) by end of day 10.
- Day 7: reminder notice.
- Day 11: DELINQUENT. LATE_FEE_1 ($15) plus first delinquency notice.
- Day 31: LATE_FEE_2 ($20) plus final delinquency notice.
- Late fees are capped at $35 per citation. The cap is re-checked against existing fees before every insert, not just by schedule.
- `status` stays the payment state. The new `stage` field (current / delinquent / final) tracks the timeline. `overdue` and `past_due` are no longer set on v2 citations.
- Citations on the Oct 2026 hold-exemption list get no v2 fees or notices while the exemption is active.

**Appeals**
- v2 citations can be appealed through the end of day 10 (local). Legacy citations keep the old window.
- The appeal window starts when the student was actually notified. For citations issued on or after Sep 18, 2026 with an email address on file: if the citation email went out more than an hour after issuance (e.g. resent after the Sep 18 – Oct 16 email failures), the full window counts from the send time; if it was never sent, the window stays open until it is.
- A pending appeal pauses the clock. A denied appeal starts a 10-day grace period from the decision date. If still unpaid when it ends, the citation is delinquent immediately (day-11 stage) and later stages follow on the normal schedule.
- Every appeal decision path (approve/deny, quick deny, bulk deny, committee) goes through one shared function so they behave the same.
- Appeals Committee cases have a discussion thread: committee members and admins can post comments or questions on any case without voting, and everyone on the committee page sees them with author and time. Authors can delete their own comments. Comments with a vote are separate and stay on the vote.
- Committee work is internal. Students never see votes, vote counts, comments, discussion, escalation notes, or committee member emails; the student-facing appeal pages show only the appeal status (pending, approved, denied) and do not include who decided it.
- Dismissal (approved appeal or void) voids every open fee on the citation. A fee shared with other citations (owner notification, deployment) is voided only once all of its citations are dismissed.

**Payment plans**
- Staff create a plan covering specific citations, with scheduled installments. Covered citations are paused while the plan is current. New citations are not covered unless staff add them.
- An unpaid installment past its due date defaults the plan. Each covered citation's clock resumes where it was paused.
- Installments are recorded by staff (cash, check, bursar). They are applied oldest item first; a citation is paid once its fine is fully covered.

**Fees** — each its own line item, never folded into `fine_amount`
- LATE_FEE_1 $15 (day 11), LATE_FEE_2 $20 (day 31), automatic.
- BARNACLE_DEPLOYMENT $100, only when an officer records a deployment.
- BARNACLE_DAMAGE (staff amount, documentation required), OWNER_NOTIFICATION $25 (one per mailed registered-owner letter, covering all that vehicle's outstanding citations), COLLECTION_COST (staff amount, reason required).
- Every fee records type, amount, creator (system or user), time and linked citations. Staff can waive or void with a reason.
- The online processing fee applies to the whole online total (fines plus fees).

**Barnacle** — behind a feature flag, off until counsel approves
- On only when the `BARNACLE_ENABLED` env var AND the Enforcement Settings toggle are both on. While off: no final warnings, no eligibility runs, Barnacle endpoints return 404, Barnacle fees can't be created, and notices leave out Barnacle wording.
- A vehicle is plate + issuing state. Citations without a state never count; staff fill the state in first.
- Eligible only when all are true: (1) 3+ delinquent citations not under a pending appeal or current plan; (2) the oldest has been delinquent 30+ effective days; (3) a final warning was sent (mailed warnings count once staff mark them mailed); (4) 10+ days have passed since that warning and the balance is unresolved.
- The final warning is generated when conditions 1 and 2 are met or will be within 10 days. Earliest date = the later of the day conditions 1 and 2 are met and warning date + 10. It includes, word for word: "Your vehicle may be immobilized with a Barnacle on or after [date] if your qualifying unpaid citations remain unresolved. Actual deployment will result in an additional $100 fee."
- A warning stays valid while it covers at least 3 of the vehicle's currently qualifying citations; otherwise a new one is generated.
- Officers must run a live checklist and confirm the location is authorized property. Deployment is refused if eligibility fails at that moment.
- Removal requires a zero balance across all of the person's parking citations and fees, or an admin (supervisor) release override with a reason.

**Non-affiliated vehicles (MUPD review)**
- Non-affiliated = no non-visitor, non-tag permit on the plate and no vehicle tag tied to a student (see the vehicle tag rule).
- A delinquent citation on a non-affiliated vehicle opens a MUPD review. Nothing is filed automatically.
- The review keeps registered owner and responsible-person evidence as separate fields. Court fines live only on the review and are never recorded as payments.

**Notices and audit**
- Every notice records type, channel, recipient, sent time, and an HTML/text snapshot. Recipients without an email go to the notice mail queue and count as sent only when staff mark them mailed.
- The daily job runs once per local day after the configured hour, under an advisory lock. Each fee and notice has a unique idempotency key, so a rerun can never double-charge or double-send.
- Every policy state change (fee added/waived, pause opened/closed, plan created/defaulted, warning, deployment, removal, override) is written to `audit_log` with the actor (`system` for the job) and reason.

## Sponsor Permits

- Deletion uses POST /revoke (not HTTP DELETE — WAF blocks it).
- Revocation is soft-delete (recoverable).
