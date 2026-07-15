"""
Lottery runner — orchestrates a complete lottery draw with full audit trail.

Usage:
    result = await run_lottery(db, permit_type_id, run_by="admin@moravian.edu")
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.lottery import get_strategy, assign_lots, distribute_capacity
from app.services.email import send_email, send_lottery_selection_email, email_shell

logger = logging.getLogger(__name__)


class LotteryResult:
    """Result of a lottery draw, suitable for API response and audit log."""

    def __init__(self):
        self.permit_type_id: str = ""
        self.permit_type_name: str = ""
        self.strategy: str = ""
        self.seed: str = ""
        self.seed_hash: str = ""
        self.total_applicants: int = 0
        self.eligible_applicants: int = 0
        self.spots_available: int = 0
        self.selected_count: int = 0
        self.waitlisted_count: int = 0
        self.filtered_test_entries: int = 0
        self.filtered_unpaid_citations: int = 0
        self.lot_assignment_warnings: list[str] = []
        self.run_at: datetime | None = None
        self.run_by: str = ""


async def run_lottery(
    db: AsyncSession,
    permit_type_id: str,
    run_by: str,
    force: bool = False,
    seed_override: str | None = None,
) -> LotteryResult:
    """
    Execute a complete lottery draw for a permit type.

    Args:
        db: Database session
        permit_type_id: UUID of the permit type to run lottery for
        run_by: Email of the admin running the lottery
        force: If True, allow re-running a lottery that has already been run
        seed_override: Optional seed for deterministic testing. In production,
                       a cryptographically random seed is generated.

    Returns:
        LotteryResult with full audit details

    Raises:
        ValueError: If the lottery has already been run (and force=False),
                    or if the application window is still open
    """
    result = LotteryResult()
    result.run_by = run_by

    # ── Load permit type ──
    pt_result = await db.execute(
        text("SELECT * FROM permit_types WHERE id = :id"),
        {"id": permit_type_id},
    )
    permit_type = pt_result.mappings().one_or_none()
    if not permit_type:
        raise ValueError(f"Permit type {permit_type_id} not found")

    result.permit_type_id = permit_type_id
    result.permit_type_name = permit_type["name"] if "name" in permit_type else permit_type.get("label", "")
    result.strategy = permit_type.get("lottery_strategy") or "seniority_timestamp"
    result.spots_available = permit_type.get("max_capacity") or 0

    # ── Idempotency guard ──
    if permit_type.get("lottery_run_at") and not force:
        raise ValueError(
            f"Lottery for '{result.permit_type_name}' was already run at "
            f"{permit_type['lottery_run_at']}. Pass force=True to re-run."
        )

    # ── Check application window is closed ──
    closes_at = permit_type.get("application_closes_at")
    if closes_at and closes_at > datetime.now(timezone.utc):
        raise ValueError(
            f"Application window for '{result.permit_type_name}' is still open "
            f"until {closes_at}. Close it first or wait."
        )

    # ── Load all applications ──
    apps_result = await db.execute(
        text("""
            SELECT * FROM permit_applications
            WHERE permit_type_id = :ptid
              AND status = 'pending'
            ORDER BY created_at
        """),
        {"ptid": permit_type_id},
    )
    all_apps = apps_result.mappings().all()
    result.total_applicants = len(all_apps)

    # ── Filter test entries ──
    eligible = [a for a in all_apps if not a.get("is_test_entry")]
    result.filtered_test_entries = result.total_applicants - len(eligible)

    # ── Filter students with unpaid citations ──
    filtered_for_citations = []
    for app in eligible:
        plate = app.get("plate", "")
        if plate:
            citation_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM tickets
                    WHERE UPPER(plate) = UPPER(:plate)
                      AND status NOT IN ('paid', 'voided', 'resolved_permit')
                """),
                {"plate": plate},
            )
            unpaid_count = citation_result.scalar() or 0
            if unpaid_count > 0:
                await db.execute(
                    text("""
                        UPDATE permit_applications
                        SET status = 'ineligible',
                            admin_notes = 'Blocked: ' || :count || ' unpaid citation(s). Pay outstanding fines to become eligible.'
                        WHERE id = :id
                    """),
                    {"id": str(app["id"]), "count": str(unpaid_count)},
                )
                result.filtered_unpaid_citations += 1
                continue
        filtered_for_citations.append(app)

    eligible = filtered_for_citations
    result.eligible_applicants = len(eligible)

    if not eligible:
        logger.warning("No eligible applicants for lottery %s", permit_type_id)
        await _stamp_lottery_run(db, permit_type_id, result)
        return result

    # ── Generate seed ──
    seed = seed_override or secrets.token_hex(32)
    result.seed = seed
    result.seed_hash = hashlib.sha256(seed.encode()).hexdigest()

    # ── Convert DB rows to lightweight objects for the strategy engine ──
    class AppProxy:
        def __init__(self, row):
            self.id = row["id"]
            self.class_year = row.get("class_year") or 9999
            self.created_at = row.get("created_at") or datetime.now(timezone.utc)
            self.lot_preferences = row.get("lot_preferences") or []
            self.assigned_lot = None
            self._row = row

    proxies = [AppProxy(a) for a in eligible]

    # ── Run the strategy ──
    strategy = get_strategy(result.strategy)
    selected, waitlisted = strategy.rank(proxies, result.spots_available, seed=seed)
    result.selected_count = len(selected)
    result.waitlisted_count = len(waitlisted)

    # ── Assign lots ──
    lot_names = permit_type.get("lot_assignments") or []
    if lot_names and selected:
        lot_caps = distribute_capacity(result.spots_available, lot_names)
        result.lot_assignment_warnings = assign_lots(selected, lot_caps)

    # ── Update application statuses ──
    offer_days = permit_type.get("offer_window_days") or 5
    offer_expires = datetime.now(timezone.utc) + timedelta(days=offer_days)

    for rank, app in enumerate(selected, 1):
        await db.execute(
            text("""
                UPDATE permit_applications
                SET status = 'selected',
                    lottery_rank = :rank,
                    assigned_lot = :lot,
                    offer_expires_at = :expires
                WHERE id = :id
            """),
            {
                "id": str(app.id),
                "rank": rank,
                "lot": app.assigned_lot,
                "expires": offer_expires,
            },
        )

    for position, app in enumerate(waitlisted, 1):
        await db.execute(
            text("""
                UPDATE permit_applications
                SET status = 'waitlisted',
                    waitlist_position = :pos,
                    lottery_rank = :rank
                WHERE id = :id
            """),
            {
                "id": str(app.id),
                "pos": position,
                "rank": len(selected) + position,
            },
        )

    # ── Stamp the permit type ──
    await _stamp_lottery_run(db, permit_type_id, result)

    # ── Send notifications (failures logged, not raised) ──
    await _notify_selected(selected, permit_type, offer_expires)
    await _notify_waitlisted(waitlisted, permit_type)

    # ── Log the audit record ──
    await _log_lottery_audit(db, result)

    logger.info(
        "Lottery complete for '%s': %d selected, %d waitlisted, %d filtered "
        "(seed_hash=%s)",
        result.permit_type_name,
        result.selected_count,
        result.waitlisted_count,
        result.filtered_test_entries + result.filtered_unpaid_citations,
        result.seed_hash,
    )

    return result


async def _stamp_lottery_run(db, permit_type_id, result):
    """Record when the lottery was run."""
    result.run_at = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE permit_types
            SET lottery_run_at = :run_at
            WHERE id = :id
        """),
        {"id": permit_type_id, "run_at": result.run_at},
    )


async def _notify_selected(selected, permit_type, offer_expires):
    """Email all selected applicants using the branded lottery selection template."""
    pt_label = permit_type.get("label") or permit_type.get("name") or ""
    pt_price = str(permit_type.get("price", "0"))

    for app in selected:
        email = app._row.get("student_email") or app._row.get("email")
        name = app._row.get("student_name") or app._row.get("name") or "Student"
        if not email:
            continue
        try:
            portal_url = f"{settings.student_facing_url.rstrip('/')}/student/permits"
            await send_lottery_selection_email(
                recipient_email=email,
                student_name=name,
                permit_type_label=pt_label,
                price=pt_price,
                deadline=offer_expires.strftime("%B %d, %Y"),
                portal_url=portal_url,
                assigned_lot=app.assigned_lot,
            )
        except Exception as e:
            logger.error("Failed to notify selected applicant %s: %s", app.id, e)


async def _notify_waitlisted(waitlisted, permit_type):
    """Email all waitlisted applicants with their position."""
    pt_label = permit_type.get("label") or permit_type.get("name") or ""
    school = settings.school_name or "Campus"

    for idx, app in enumerate(waitlisted):
        email = app._row.get("student_email") or app._row.get("email")
        name = app._row.get("student_name") or app._row.get("name") or "Student"
        if not email:
            continue
        try:
            position = idx + 1
            first_name = name.split()[0] if name else "Student"

            inner = (
                f'<h2 style="color:{settings.brand_primary_color};margin:0 0 8px;font-size:20px;">Waitlisted &mdash; {pt_label}</h2>'
                f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name}, '
                f'thank you for applying for the <strong>{pt_label}</strong> parking permit.</p>'
                '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;margin:20px 0;">'
                '<tr><td colspan="2" style="padding:12px 16px 4px;font-size:11px;color:#999;'
                'text-transform:uppercase;letter-spacing:1px;">Waitlist Status</td></tr>'
                '<tr style="border-bottom:1px solid #eee;">'
                '<td style="padding:10px 16px;color:#666;font-size:14px;">Your Position</td>'
                f'<td style="padding:10px 16px;font-weight:600;font-size:16px;color:{settings.brand_primary_color};">#{position}</td></tr>'
                '<tr>'
                '<td style="padding:10px 16px;color:#666;font-size:14px;">Total Waitlisted</td>'
                f'<td style="padding:10px 16px;font-size:14px;">{len(waitlisted)}</td></tr>'
                '</table>'
                '<p style="color:#333;font-size:14px;line-height:1.6;">You were not selected in '
                'the initial lottery draw, but you have been placed on the waitlist. If a selected '
                'student declines or does not pay by the deadline, you will be notified by email '
                'with an offer to claim the spot.</p>'
                '<div style="background:#f8f9fa;border-radius:8px;padding:14px 20px;margin:20px 0;text-align:center;">'
                '<p style="font-size:14px;color:#666;margin:0;">No action is required at this time.</p>'
                '</div>'
            )
            body_html = email_shell(school, inner)
            body_text = (
                f"WAITLISTED — {pt_label}\n\n"
                f"Dear {first_name},\n\n"
                f"Thank you for applying for the {pt_label} parking permit.\n\n"
                f"You were not selected in the initial lottery draw, but you have been "
                f"placed on the waitlist at position #{position} out of {len(waitlisted)}.\n\n"
                f"If a selected student declines or does not pay by the deadline, you will "
                f"be notified by email with an offer to claim the spot.\n\n"
                f"You do not need to take any action at this time.\n\n"
                f"{school} Parking Services"
            )
            await send_email(
                to=[email],
                subject=f"Parking Permit Waitlisted — {pt_label}",
                body_html=body_html,
                body_text=body_text,
            )
        except Exception as e:
            logger.error("Failed to notify waitlisted applicant %s: %s", app.id, e)


async def _log_lottery_audit(db, result: LotteryResult):
    """Write an audit record of the lottery draw."""
    await db.execute(
        text("""
            INSERT INTO lottery_audit_log
                (permit_type_id, strategy, seed_hash, total_applicants,
                 eligible_applicants, spots_available, selected_count,
                 waitlisted_count, filtered_test_entries,
                 filtered_unpaid_citations, run_at, run_by, warnings)
            VALUES
                (:ptid, :strategy, :seed_hash, :total, :eligible, :spots,
                 :selected, :waitlisted, :test, :citations, :run_at, :run_by,
                 :warnings)
        """),
        {
            "ptid": result.permit_type_id,
            "strategy": result.strategy,
            "seed_hash": result.seed_hash,
            "total": result.total_applicants,
            "eligible": result.eligible_applicants,
            "spots": result.spots_available,
            "selected": result.selected_count,
            "waitlisted": result.waitlisted_count,
            "test": result.filtered_test_entries,
            "citations": result.filtered_unpaid_citations,
            "run_at": result.run_at,
            "run_by": result.run_by,
            "warnings": "\n".join(result.lot_assignment_warnings) if result.lot_assignment_warnings else None,
        },
    )


async def verify_lottery(
    db: AsyncSession,
    permit_type_id: str,
    seed: str,
) -> dict:
    """
    Verify a previous lottery draw by re-running with the same seed.

    Loads the audit record and confirms the provided seed matches the
    stored hash. Returns a verification report.
    """
    audit_result = await db.execute(
        text("""
            SELECT * FROM lottery_audit_log
            WHERE permit_type_id = :ptid
            ORDER BY run_at DESC LIMIT 1
        """),
        {"ptid": permit_type_id},
    )
    audit = audit_result.mappings().one_or_none()
    if not audit:
        return {"verified": False, "error": "No lottery audit record found"}

    seed_hash = hashlib.sha256(seed.encode()).hexdigest()
    if seed_hash != audit["seed_hash"]:
        return {
            "verified": False,
            "error": "Seed hash does not match",
            "expected_hash": audit["seed_hash"],
            "provided_hash": seed_hash,
        }

    return {
        "verified": True,
        "seed_hash": seed_hash,
        "strategy": audit["strategy"],
        "selected_count": audit["selected_count"],
        "waitlisted_count": audit["waitlisted_count"],
        "run_at": str(audit["run_at"]),
        "run_by": audit["run_by"],
    }
