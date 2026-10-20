"""Call the Jenzabar stored procedure to set or remove a registration hold.

Paul Edinger's stored procedure accepts a student ID number and a Y/N flag.
A scheduled process inside Jenzabar applies or removes the actual hold
based on that flag.
"""

import asyncio
import logging

from ..config import settings

logger = logging.getLogger("quarry.sis_hold")


def _call_hold_proc(id_num: str, hold_flag: str) -> bool:
    """Synchronous pymssql call — meant to run in a thread."""
    import pymssql  # type: ignore

    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host,
            port=settings.sis_mssql_port,
            user=settings.sis_mssql_user,
            password=settings.sis_mssql_password,
            database=settings.sis_mssql_database,
            login_timeout=5,
            timeout=10,
        )
        cur = conn.cursor()
        proc = settings.sis_hold_procedure
        cur.execute(
            f"EXEC {proc} @id_num=%s, @flag=%s",
            (id_num, hold_flag),
        )
        conn.commit()
        conn.close()
        logger.info(
            "Jenzabar hold proc called: id_num=%s hold=%s", id_num, hold_flag
        )
        return True
    except Exception as e:
        logger.error(
            "Jenzabar hold proc FAILED: id_num=%s hold=%s error=%s",
            id_num, hold_flag, e,
        )
        return False


def _check_hold(id_num: str) -> bool | None:
    """Check if a parking hold currently exists in Jenzabar. Returns True/False/None (error)."""
    import pymssql  # type: ignore

    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host,
            port=settings.sis_mssql_port,
            user=settings.sis_mssql_user,
            password=settings.sis_mssql_password,
            database=settings.sis_mssql_database,
            login_timeout=5,
            timeout=10,
        )
        cur = conn.cursor(as_dict=True)
        # View provided by Paul Edinger; the parking hold code is TK.
        hold_code = settings.sis_hold_type or "TK"
        cur.execute(
            """
            SELECT TOP 1 1 AS has_hold
            FROM Mor_CUS_Active_TK_Hold
            WHERE id_num = %s
              AND hold_cde = %s
              AND (end_dte IS NULL OR end_dte > GETDATE())
            """,
            (id_num, hold_code),
        )
        row = cur.fetchone()
        conn.close()
        has_hold = row is not None
        logger.debug("Jenzabar hold check: id_num=%s has_hold=%s", id_num, has_hold)
        return has_hold
    except Exception as e:
        logger.error("Jenzabar hold check FAILED: id_num=%s error=%s", id_num, e)
        return None


def _list_active_holds() -> list[str] | None:
    import pymssql  # type: ignore

    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host,
            port=settings.sis_mssql_port,
            user=settings.sis_mssql_user,
            password=settings.sis_mssql_password,
            database=settings.sis_mssql_database,
            login_timeout=5,
            timeout=30,
        )
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT id_num
            FROM Mor_CUS_Active_TK_Hold
            WHERE hold_cde = %s
              AND (end_dte IS NULL OR end_dte > GETDATE())
            """,
            (settings.sis_hold_type or "TK",),
        )
        ids = [str(r[0]).strip() for r in cur.fetchall() if r[0] is not None]
        conn.close()
        return ids
    except Exception as e:
        logger.error("Jenzabar active hold list FAILED: %s", e)
        return None


async def list_active_jenzabar_holds() -> list[str] | None:
    """Every Moravian ID with an active parking hold in Jenzabar, or None if the query failed."""
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        return None
    try:
        return await asyncio.wait_for(asyncio.to_thread(_list_active_holds), timeout=45)
    except asyncio.TimeoutError:
        logger.error("Jenzabar active hold list timed out")
        return None


async def check_jenzabar_hold(id_num: str) -> bool | None:
    """Check if a parking hold exists in Jenzabar.

    Returns:
        True if hold is active, False if no hold, None if check failed.
    """
    if not settings.sis_hold_enabled:
        return None
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        return None
    if not id_num or not id_num.strip().isdigit():
        return None
    try:
        return await asyncio.wait_for(asyncio.to_thread(_check_hold, id_num), timeout=15)
    except asyncio.TimeoutError:
        logger.error("Jenzabar hold check timed out: id_num=%s", id_num)
        return None


async def set_jenzabar_hold(id_num: str, apply: bool) -> bool:
    """Set or remove a registration hold in Jenzabar.

    Args:
        id_num: The student's Moravian/Jenzabar numeric ID.
        apply: True to set the hold, False to remove it.

    Returns:
        True if the stored procedure call succeeded.
    """
    if not settings.sis_hold_enabled:
        logger.debug("SIS hold disabled — skipping for %s", id_num)
        return False

    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        logger.warning(
            "SIS hold requested but MSSQL credentials not configured"
        )
        return False

    if not id_num or not id_num.strip().isdigit():
        logger.warning(
            "SIS hold skipped — non-numeric id_num: %s", id_num
        )
        return False

    hold_flag = "Y" if apply else "N"
    return await asyncio.to_thread(_call_hold_proc, id_num, hold_flag)
