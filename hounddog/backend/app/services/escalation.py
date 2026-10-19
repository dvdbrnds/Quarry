"""
Escalation service — checks ticket thresholds and triggers
conduct referrals (Maxient) and registration holds.

Integration points are pluggable:
- Maxient: defaults to email-based intake referral
- SIS holds: defaults to logging + admin notification (wire up API later)
"""
import logging
import re
from app import error_reporting
from uuid import uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.permit import Permit

logger = logging.getLogger("quarry.escalation")

# Permits (alias p) whose plates count against student :student_id — real permits,
# plus vehicle tags only once staff have verified the owner.
_OWNED_BY_STUDENT = """(
    (p.is_tag_only = false AND p.student_id = :student_id)
    OR (p.is_tag_only = true AND p.deleted_at IS NULL
        AND p.owner_verified_at IS NOT NULL AND p.owner_student_id = :student_id)
)"""


_PLACEHOLDER_SID = re.compile(r"^[a-z_]+:")
PLACEHOLDER_SID_SQL = "^[a-z_]+:"


def is_person_student_id(student_id: str | None) -> bool:
    """False for blanks and metadata stuffed into student_id (visitor permits store
    'company_name:...|...', legacy-imported tags store 'plate_state:XX'). Those pool
    unrelated people under one key and must never drive a hold."""
    return bool(student_id) and not _PLACEHOLDER_SID.match(student_id)


def escalation_student_id(permit) -> str | None:
    """The student a permit's tickets count against, or None if they shouldn't count."""
    if permit is None:
        return None
    if getattr(permit, "is_tag_only", False):
        if getattr(permit, "owner_verified_at", None) and getattr(permit, "owner_student_id", None):
            sid = permit.owner_student_id
        else:
            return None
    else:
        sid = getattr(permit, "student_id", None)
    return sid if is_person_student_id(sid) else None


async def _get_moravian_id(db: AsyncSession, student_id: str) -> str | None:
    """Resolve the Jenzabar numeric ID from the Okta sub stored on permits."""
    result = await db.execute(
        select(Permit.moravian_id).where(
            or_(
                Permit.student_id == student_id,
                and_(Permit.is_tag_only.is_(True), Permit.owner_student_id == student_id),
            ),
            Permit.moravian_id.isnot(None),
            Permit.moravian_id != "",
        ).limit(1)
    )
    return result.scalar()


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

    if not is_person_student_id(student_id):
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

    actions.update(await apply_registration_hold_if_needed(
        db, student_id, student_name, student_email, plate, unpaid_count
    ))
    return actions


async def apply_registration_hold_if_needed(
    db: AsyncSession,
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    unpaid_count: int | None = None,
) -> dict:
    """Place a registration hold (Quarry + Jenzabar) if the student is at/over threshold."""
    actions: dict = {}
    if not is_person_student_id(student_id):
        actions["not_a_person"] = True
        return actions
    if unpaid_count is None:
        unpaid_count = await _count_unpaid_tickets_for_student(db, student_id)
    actions["unpaid_count"] = unpaid_count

    if unpaid_count < settings.registration_hold_threshold:
        return actions
    if await is_hold_exempt(db, student_id):
        actions["exempt"] = True
        logger.info("Registration hold skipped for %s — active hold exemption", student_id)
        return actions
    if await _has_active_escalation(db, student_id, "registration_hold"):
        actions["already_held"] = True
        return actions

    moravian_id = await _get_moravian_id(db, student_id)
    await _create_registration_hold(
        db, student_id, student_name, student_email, plate, unpaid_count
    )
    if moravian_id:
        from .sis_hold_service import set_jenzabar_hold
        ok = await set_jenzabar_hold(moravian_id, apply=True)
        actions["jenzabar_hold_set"] = ok
    else:
        logger.warning(
            "Registration hold triggered for %s but no moravian_id — "
            "Jenzabar hold NOT set (manual action needed)",
            student_id,
        )
    actions["registration_hold"] = True
    logger.info(
        "Registration hold triggered for student %s (%d tickets)",
        student_id, unpaid_count,
    )
    return actions


# hold_exemptions (alias e) rows that apply to permit p, by plate or email.
_EXEMPTION_MATCHES_PERMIT = """(
    (e.plate IS NOT NULL AND e.plate = ANY(SELECT UPPER(unnest(p.plates))))
    OR (e.email IS NOT NULL AND LOWER(p.email) = LOWER(e.email))
)"""


async def is_hold_exempt(db: AsyncSession, student_id: str) -> bool:
    result = await db.execute(
        text(f"""
            SELECT 1 FROM hold_exemptions e
            JOIN permits p ON {_EXEMPTION_MATCHES_PERMIT}
            WHERE e.expires_at > NOW() AND {_OWNED_BY_STUDENT}
            LIMIT 1
        """),
        {"student_id": student_id},
    )
    return result.scalar() is not None


async def _exemption_student_ids(db: AsyncSession, where: str) -> tuple[list[str], set[str]]:
    """Student ids matched by the exemptions selected by `where`, plus those exemption ids."""
    rows = (await db.execute(text(f"""
        SELECT e.id::text AS eid,
               CASE WHEN p.is_tag_only THEN p.owner_student_id ELSE p.student_id END AS sid
        FROM hold_exemptions e
        LEFT JOIN permits p ON {_EXEMPTION_MATCHES_PERMIT}
          AND ((p.is_tag_only = false AND COALESCE(p.student_id, '') <> '')
               OR (p.is_tag_only = true AND p.owner_verified_at IS NOT NULL
                   AND p.owner_student_id IS NOT NULL))
        WHERE {where}
    """))).mappings().all()
    exemption_ids = {r["eid"] for r in rows}
    sids = {r["sid"] for r in rows if is_person_student_id(r["sid"])}

    # Holds recorded against an exempt plate even if the permit link is gone
    if exemption_ids:
        extra = await db.execute(text(f"""
            SELECT DISTINCT l.student_id FROM escalation_log l
            JOIN hold_exemptions e
              ON UPPER(REPLACE(REPLACE(COALESCE(l.plate, ''), ' ', ''), '-', '')) = e.plate
              OR (e.email IS NOT NULL AND LOWER(l.student_email) = LOWER(e.email))
            WHERE l.escalation_type = 'registration_hold' AND l.resolved_at IS NULL
              AND COALESCE(l.student_id, '') <> '' AND {where}
        """))
        sids |= {r[0] for r in extra.fetchall() if is_person_student_id(r[0])}
    return sorted(sids), exemption_ids


async def process_hold_exemptions(db: AsyncSession) -> dict:
    """Lift holds for newly exempt students; re-apply holds once exemptions expire."""
    got_lock = (await db.execute(text("SELECT pg_try_advisory_xact_lock(4747)"))).scalar()
    if not got_lock:
        return {}
    summary = {"lifted": 0, "reapplied": 0}

    sids, eids = await _exemption_student_ids(
        db, "e.expires_at > NOW() AND e.lifted_existing_at IS NULL"
    )
    for sid in sids:
        if not await resolve_escalation(db, sid, "registration_hold", "exemption:hold-grace"):
            continue
        summary["lifted"] += 1
        moravian_id = await _get_moravian_id(db, sid)
        if moravian_id and settings.sis_hold_enabled and settings.sis_mssql_host:
            from .sis_hold_service import set_jenzabar_hold
            if not await set_jenzabar_hold(moravian_id, apply=False):
                error_reporting.capture_message(
                    f"Hold exemption: Jenzabar hold removal failed for moravian_id={moravian_id}",
                    level="error",
                )
                logger.error("Hold exemption: Jenzabar removal FAILED for %s (moravian_id=%s) — remove manually", sid, moravian_id)
        logger.info("Hold exemption: lifted registration hold for %s", sid)
    if eids:
        await db.execute(
            text("UPDATE hold_exemptions SET lifted_existing_at = NOW() WHERE id::text = ANY(:ids)"),
            {"ids": list(eids)},
        )

    sids, eids = await _exemption_student_ids(
        db, "e.expires_at <= NOW() AND e.expiry_processed_at IS NULL"
    )
    for sid in sids:
        if await is_hold_exempt(db, sid):
            continue
        permit = (await db.execute(
            select(Permit).where(
                or_(
                    and_(Permit.is_tag_only.is_(False), Permit.student_id == sid),
                    and_(Permit.is_tag_only.is_(True), Permit.owner_student_id == sid),
                ),
                Permit.deleted_at.is_(None),
            ).order_by(Permit.is_tag_only.asc()).limit(1)
        )).scalar()
        actions = await apply_registration_hold_if_needed(
            db, sid,
            permit.name if permit else None,
            permit.email if permit else None,
            (permit.plates[0] if permit and permit.plates else ""),
        )
        if actions.get("registration_hold"):
            summary["reapplied"] += 1
    if eids:
        await db.execute(
            text("UPDATE hold_exemptions SET expiry_processed_at = NOW() WHERE id::text = ANY(:ids)"),
            {"ids": list(eids)},
        )

    if summary["lifted"] or summary["reapplied"]:
        logger.info("Hold exemptions processed: %s", summary)
    return summary


async def _count_unpaid_tickets_for_student(db: AsyncSession, student_id: str) -> int:
    result = await db.execute(
        text(f"""
            SELECT COUNT(DISTINCT t.id)
            FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
            WHERE {_OWNED_BY_STUDENT}
              AND t.status NOT IN ('paid', 'voided', 'resolved_permit', 'warning')
              AND COALESCE(t.fine_amount, 0) > 0
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
        text(f"""
            SELECT DISTINCT t.id::text, t.issued_at
            FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
            WHERE {_OWNED_BY_STUDENT}
              AND t.status NOT IN ('paid', 'voided', 'resolved_permit', 'warning')
              AND COALESCE(t.fine_amount, 0) > 0
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
            "Set MAXIENT_INTAKE_EMAIL or MAXIENT_API_URL."
        )

    # Notify designated conduct officer(s)
    await _notify_conduct_officers(
        db, student_name, student_email, plate, ticket_count
    )


async def _send_maxient_email_referral(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
    ticket_ids: list[str],
):
    from app.services.email import send_email, _load_branding
    from app.services.email_templates import render_conduct_referral_email

    b = await _load_branding()
    school = settings.school_name or "Campus"
    subject = f"Parking Conduct Referral \u2014 {student_name or student_id} ({ticket_count} violations)"
    detail_url = f"{settings.public_url}/admin/tickets?student={student_id}"

    body_html, body_text = render_conduct_referral_email(
        student_id, student_name, student_email, plate,
        ticket_count, ticket_ids, settings.conduct_referral_threshold, detail_url,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )

    try:
        await send_email(
            to=[settings.maxient_intake_email],
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )
    except Exception as e:
        error_reporting.capture_exception(e)
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

    # The actual Jenzabar stored procedure call happens in check_and_escalate()
    # after this function returns, so we only log + notify here.

    await _notify_student_of_hold(student_name, student_email, ticket_count)
    await _notify_admin_of_hold(student_id, student_name, student_email, plate, ticket_count)


async def _notify_student_of_hold(
    student_name: str | None,
    student_email: str | None,
    ticket_count: int,
):
    if not student_email:
        return

    from app.services.email import send_email, _load_branding
    from app.services.email_templates import render_hold_student_email

    b = await _load_branding()
    school = settings.school_name or "Campus"
    subject = "Registration Hold \u2014 Unpaid Parking Violations"
    pay_url = f"{settings.student_facing_url}/pay"

    body_html, body_text = render_hold_student_email(
        student_name, ticket_count, pay_url,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )

    try:
        await send_email(to=[student_email], subject=subject, body_html=body_html, body_text=body_text)
    except Exception as e:
        error_reporting.capture_exception(e)
        logger.error("Failed to send hold notification to %s: %s", student_email, e)


async def _notify_admin_of_hold(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
):
    from app.services.email import send_email, _load_branding
    from app.services.email_templates import render_hold_admin_email

    admin_email = settings.smtp_from_address
    if not admin_email:
        return

    b = await _load_branding()
    school = settings.school_name or "Campus"
    subject = f"Registration Hold Triggered \u2014 {student_name or student_id}"
    detail_url = f"{settings.public_url}/admin/tickets?student={student_id}"

    body_html, body_text = render_hold_admin_email(
        student_id, student_name, student_email, plate, ticket_count,
        sis_configured=bool(settings.sis_hold_api_url),
        detail_url=detail_url, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )

    try:
        await send_email(to=[admin_email], subject=subject, body_html=body_html, body_text=body_text)
    except Exception as e:
        error_reporting.capture_exception(e)
        logger.error("Failed to send admin hold notification: %s", e)


async def check_and_resolve_on_payment(db: AsyncSession, plate: str):
    """After a ticket is paid, check if any student associated with this plate
    has dropped below escalation thresholds and auto-resolve."""
    result = await db.execute(
        text("""
            SELECT DISTINCT
                CASE WHEN p.is_tag_only THEN p.owner_student_id ELSE p.student_id END AS sid
            FROM permits p
            WHERE UPPER(:plate) = ANY(
                SELECT UPPER(unnest(p.plates))
            )
              AND (
                (p.is_tag_only = false AND p.student_id IS NOT NULL)
                OR (p.is_tag_only = true AND p.owner_verified_at IS NOT NULL
                    AND p.owner_student_id IS NOT NULL)
              )
        """),
        {"plate": plate},
    )
    for (student_id,) in result.fetchall():
        if not student_id:
            continue
        await release_if_below_threshold(db, student_id, "system:payment")


async def clear_tag_verification(db: AsyncSession, tag: Permit, cleared_by: str) -> None:
    """Un-verify a tag's owner and lift any hold that depended on it."""
    old_sid, old_mid = tag.owner_student_id, tag.moravian_id
    if not tag.owner_verified_at and not old_sid:
        return
    tag.owner_student_id = None
    tag.owner_verified_at = None
    tag.owner_verified_by = None
    tag.moravian_id = None
    await db.flush()
    if old_sid:
        await release_if_below_threshold(db, old_sid, f"unverified:{cleared_by}", old_mid)
    logger.info("Tag owner verification cleared: tag=%s student=%s by=%s", tag.id, old_sid, cleared_by)


async def release_if_below_threshold(
    db: AsyncSession, student_id: str, resolved_by: str, moravian_id: str | None = None,
) -> None:
    """Lift the hold (Quarry + Jenzabar) and close the referral once under threshold."""
    remaining = await _count_unpaid_tickets_for_student(db, student_id)
    if remaining < settings.registration_hold_threshold:
        resolved = await resolve_escalation(db, student_id, "registration_hold", resolved_by)
        if resolved:
            moravian_id = moravian_id or await _get_moravian_id(db, student_id)
            if moravian_id:
                from .sis_hold_service import set_jenzabar_hold
                await set_jenzabar_hold(moravian_id, apply=False)
                logger.info(
                    "Jenzabar hold removed for %s (moravian_id=%s, %d tickets remaining < threshold %d)",
                    student_id, moravian_id, remaining, settings.registration_hold_threshold,
                )
    if remaining < settings.conduct_referral_threshold:
        await resolve_escalation(db, student_id, "conduct_referral", resolved_by)


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


async def _notify_conduct_officers(
    db: AsyncSession,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
):
    """Send an email to all designated conduct officers when a referral is triggered."""
    # Load conduct officer emails from enforcement_settings
    try:
        result = await db.execute(
            text("SELECT conduct_officer_emails FROM enforcement_settings WHERE id = 1")
        )
        raw = result.scalar() or ""
    except Exception:
        await db.rollback()
        raw = ""

    recipients = [e.strip() for e in raw.split(",") if e.strip()]
    if not recipients:
        logger.warning(
            "Conduct referral triggered but no conduct officer emails configured. "
            "Set them in Tickets → Enforcement settings."
        )
        return

    from app.services.email import send_email, _load_branding
    from app.services.email_templates import render_conduct_officer_notification

    b = await _load_branding()
    school = settings.school_name or "Campus"
    subject = (
        f"Conduct Escalation — {student_name or 'Unknown Student'} "
        f"({ticket_count} unpaid violations)"
    )
    detail_url = f"{settings.public_url}/conduct"

    body_html, body_text = render_conduct_officer_notification(
        student_name, student_email, plate, ticket_count,
        settings.conduct_referral_threshold,
        detail_url,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )

    try:
        await send_email(
            to=recipients,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )
        logger.info(
            "Conduct officer notification sent to %s for student %s",
            ", ".join(recipients), student_name or student_email or plate,
        )
    except Exception as e:
        error_reporting.capture_exception(e)
        logger.error("Failed to send conduct officer notification: %s", e)
