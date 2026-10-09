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
