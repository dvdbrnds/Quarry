"""
Escalation service — checks ticket thresholds and triggers
conduct referrals (Maxient) and registration holds.

Integration points are pluggable:
- Maxient: defaults to email-based intake referral
- SIS holds: defaults to logging + admin notification (wire up API later)
"""
import logging
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger("quarry.escalation")


async def check_and_escalate(
    db: AsyncSession,
    plate: str,
    student_id: str | None,
    student_name: str | None,
    student_email: str | None,
) -> dict:
    """
    Called after a new ticket is created. Counts unpaid tickets for this
    plate/student and triggers escalations if thresholds are crossed.
    """
    actions = {}

    if not student_id:
        return actions

    unpaid_count = await _count_unpaid_tickets_for_student(db, student_id)

    if unpaid_count >= settings.conduct_referral_threshold:
        already_referred = await _has_active_escalation(db, student_id, "conduct_referral")
        if not already_referred:
            await _create_conduct_referral(
                db, student_id, student_name, student_email, plate, unpaid_count
            )
            actions["conduct_referral"] = True
            logger.info(
                "Conduct referral triggered for student %s (%d tickets)",
                student_id, unpaid_count,
            )

    if unpaid_count >= settings.registration_hold_threshold:
        already_held = await _has_active_escalation(db, student_id, "registration_hold")
        if not already_held:
            await _create_registration_hold(
                db, student_id, student_name, student_email, plate, unpaid_count
            )
            actions["registration_hold"] = True
            logger.info(
                "Registration hold triggered for student %s (%d tickets)",
                student_id, unpaid_count,
            )

    return actions


async def _count_unpaid_tickets_for_student(db: AsyncSession, student_id: str) -> int:
    result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT t.id)
            FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
            WHERE p.student_id = :student_id
              AND t.status NOT IN ('paid', 'voided', 'resolved_permit')
        """),
        {"student_id": student_id},
    )
    return result.scalar() or 0


async def _has_active_escalation(db: AsyncSession, student_id: str, escalation_type: str) -> bool:
    result = await db.execute(
        text("""
            SELECT 1 FROM escalation_log
            WHERE student_id = :student_id
              AND escalation_type = :etype
              AND resolved_at IS NULL
            LIMIT 1
        """),
        {"student_id": student_id, "etype": escalation_type},
    )
    return result.scalar() is not None


async def _get_ticket_ids_for_student(db: AsyncSession, student_id: str) -> list[str]:
    result = await db.execute(
        text("""
            SELECT t.id::text
            FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
            WHERE p.student_id = :student_id
              AND t.status NOT IN ('paid', 'voided', 'resolved_permit')
            ORDER BY t.issued_at DESC
        """),
        {"student_id": student_id},
    )
    return [row[0] for row in result.fetchall()]


async def _create_conduct_referral(
    db: AsyncSession,
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
):
    ticket_ids = await _get_ticket_ids_for_student(db, student_id)

    esc_id = str(uuid4())
    await db.execute(
        text("""
            INSERT INTO escalation_log
                (id, student_id, student_name, student_email, plate,
                 escalation_type, ticket_count, ticket_ids, status)
            VALUES
                (:id, :sid, :sname, :semail, :plate,
                 'conduct_referral', :count, :tids, 'sent')
        """),
        {
            "id": esc_id,
            "sid": student_id,
            "sname": student_name,
            "semail": student_email,
            "plate": plate,
            "count": ticket_count,
            "tids": ",".join(ticket_ids),
        },
    )

    if settings.maxient_referral_enabled and settings.maxient_intake_email:
        await _send_maxient_email_referral(
            student_id, student_name, student_email, plate, ticket_count, ticket_ids
        )
    elif settings.maxient_api_url:
        logger.info("Maxient API integration not yet implemented")
    else:
        logger.warning(
            "Conduct referral triggered but no Maxient integration configured. "
            "Set QUARRY_MAXIENT_INTAKE_EMAIL or QUARRY_MAXIENT_API_URL."
        )


async def _send_maxient_email_referral(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
    ticket_ids: list[str],
):
    from app.services.email import send_email

    subject = f"Parking Conduct Referral \u2014 {student_name or student_id} ({ticket_count} violations)"
    body = f"""<div style="font-family: sans-serif; max-width: 600px;">
<h2>Automatic Parking Conduct Referral</h2>
<table>
<tr><td><strong>Student:</strong></td><td>{student_name or 'Unknown'} ({student_id})</td></tr>
<tr><td><strong>Email:</strong></td><td>{student_email or 'Unknown'}</td></tr>
<tr><td><strong>License Plate:</strong></td><td>{plate}</td></tr>
<tr><td><strong>Total Unpaid Violations:</strong></td><td>{ticket_count}</td></tr>
<tr><td><strong>Threshold:</strong></td><td>{settings.conduct_referral_threshold}</td></tr>
</table>
<p><strong>Ticket IDs:</strong></p>
<ul>{''.join(f'<li>{tid}</li>' for tid in ticket_ids)}</ul>
<p>This referral was generated automatically by the Quarry parking system
when the student exceeded {settings.conduct_referral_threshold} unpaid parking violations.</p>
<p><a href="{settings.public_url}/admin/tickets?student={student_id}">View details</a></p>
</div>"""

    try:
        await send_email(
            to=[settings.maxient_intake_email],
            subject=subject,
            body_html=body,
        )
    except Exception as e:
        logger.error("Failed to send Maxient referral email: %s", e)


async def _create_registration_hold(
    db: AsyncSession,
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
):
    ticket_ids = await _get_ticket_ids_for_student(db, student_id)

    esc_id = str(uuid4())
    await db.execute(
        text("""
            INSERT INTO escalation_log
                (id, student_id, student_name, student_email, plate,
                 escalation_type, ticket_count, ticket_ids, status)
            VALUES
                (:id, :sid, :sname, :semail, :plate,
                 'registration_hold', :count, :tids, 'sent')
        """),
        {
            "id": esc_id,
            "sid": student_id,
            "sname": student_name,
            "semail": student_email,
            "plate": plate,
            "count": ticket_count,
            "tids": ",".join(ticket_ids),
        },
    )

    if settings.sis_hold_api_url:
        logger.info("SIS hold API integration not yet implemented for %s", student_id)
    else:
        logger.warning(
            "Registration hold triggered for %s but no SIS API configured. "
            "Notifying admin for manual hold placement.", student_id
        )

    await _notify_student_of_hold(student_name, student_email, ticket_count)
    await _notify_admin_of_hold(student_id, student_name, student_email, plate, ticket_count)


async def _notify_student_of_hold(
    student_name: str | None,
    student_email: str | None,
    ticket_count: int,
):
    if not student_email:
        return

    from app.services.email import send_email

    subject = "Registration Hold \u2014 Unpaid Parking Violations"
    body = f"""<div style="font-family: sans-serif; max-width: 600px;">
<h2>Registration Hold Notice</h2>
<p>Dear {student_name or 'Student'},</p>
<p>A hold has been placed on your university account due to <strong>{ticket_count} unpaid
parking violations</strong>. You will be unable to register for classes until all
outstanding parking fines are paid.</p>
<p><a href="{settings.public_url}/pay" style="display:inline-block;padding:12px 24px;background:#1a2744;color:#fff;text-decoration:none;border-radius:4px;">Pay Citations Now</a></p>
<p>If you believe this is in error, please contact the Parking Office.</p>
<hr style="border:none;border-top:1px solid #ddd;margin:24px 0;">
<p style="font-size:12px;color:#888;">Moravian University Parking Services &mdash; Quarry</p>
</div>"""

    try:
        await send_email(to=[student_email], subject=subject, body_html=body)
    except Exception as e:
        logger.error("Failed to send hold notification to %s: %s", student_email, e)


async def _notify_admin_of_hold(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
):
    from app.services.email import send_email

    admin_email = settings.smtp_from_address
    if not admin_email:
        return

    subject = f"Registration Hold Triggered \u2014 {student_name or student_id}"
    manual_note = (
        "<p><strong>The SIS API is not configured \u2014 please place the hold manually in Banner/Workday.</strong></p>"
        if not settings.sis_hold_api_url
        else "<p>The hold has been placed via the SIS API.</p>"
    )
    body = f"""<div style="font-family: sans-serif; max-width: 600px;">
<h2>Registration Hold Triggered</h2>
<table>
<tr><td><strong>Student:</strong></td><td>{student_name or 'Unknown'} ({student_id})</td></tr>
<tr><td><strong>Email:</strong></td><td>{student_email or 'Unknown'}</td></tr>
<tr><td><strong>Plate:</strong></td><td>{plate}</td></tr>
<tr><td><strong>Unpaid Violations:</strong></td><td>{ticket_count}</td></tr>
</table>
{manual_note}
<p><a href="{settings.public_url}/admin/tickets?student={student_id}">View details</a></p>
</div>"""

    try:
        await send_email(to=[admin_email], subject=subject, body_html=body)
    except Exception as e:
        logger.error("Failed to send admin hold notification: %s", e)


async def check_and_resolve_on_payment(db: AsyncSession, plate: str):
    """After a ticket is paid, check if any student associated with this plate
    has dropped below escalation thresholds and auto-resolve."""
    result = await db.execute(
        text("""
            SELECT DISTINCT p.student_id
            FROM permits p
            WHERE UPPER(:plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
              AND p.student_id IS NOT NULL
        """),
        {"plate": plate},
    )
    for (student_id,) in result.fetchall():
        remaining = await _count_unpaid_tickets_for_student(db, student_id)
        if remaining < settings.registration_hold_threshold:
            await resolve_escalation(db, student_id, "registration_hold", "system:payment")
        if remaining < settings.conduct_referral_threshold:
            await resolve_escalation(db, student_id, "conduct_referral", "system:payment")


async def resolve_escalation(
    db: AsyncSession,
    student_id: str,
    escalation_type: str,
    resolved_by: str,
) -> bool:
    """Mark an escalation as resolved (e.g., after tickets are paid)."""
    result = await db.execute(
        text("""
            UPDATE escalation_log
            SET resolved_at = NOW(), resolved_by = :resolved_by, status = 'resolved'
            WHERE student_id = :student_id
              AND escalation_type = :etype
              AND resolved_at IS NULL
        """),
        {
            "student_id": student_id,
            "etype": escalation_type,
            "resolved_by": resolved_by,
        },
    )
    return result.rowcount > 0
