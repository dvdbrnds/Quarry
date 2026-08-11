"""Query Moravian SIS (Jenzabar SQL Server) for student parking data.

Uses the Mor_CUS_ParkingData stored procedure via the svc_parking user.
"""

import asyncio
import logging
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)

HOUSING_LABELS = {
    "R": "Resident",
    "C": "Commuter",
    "O": "Off Campus Release",
}

CLASS_CODE_LABELS = {
    "FR": "Freshman",
    "SO": "Sophomore",
    "JR": "Junior",
    "SR": "Senior",
}


@dataclass
class StudentParkingData:
    id_num: str
    division_code: str
    housing_status: str
    housing_label: str
    class_code: str
    class_label: str
    accel_nursing: bool
    res_life_staff: bool
    employee: bool


def _parse_row(row: dict, id_num: str) -> StudentParkingData:
    housing = str(row.get("HousingStatus", "")).strip()
    class_code = str(row.get("ClassCode", "")).strip().upper()
    return StudentParkingData(
        id_num=str(row.get("id_num", id_num)).strip(),
        division_code=str(row.get("DivisionCode", "")).strip(),
        housing_status=housing,
        housing_label=HOUSING_LABELS.get(housing, housing),
        class_code=class_code,
        class_label=CLASS_CODE_LABELS.get(class_code, class_code),
        accel_nursing=str(row.get("AccelNursing", "No")).strip().lower() == "yes",
        res_life_staff=str(row.get("ResLifeStaff", "No")).strip().lower() == "yes",
        employee=str(row.get("Employee", "No")).strip().lower() == "yes",
    )


async def lookup_student_parking_data(id_num: str) -> StudentParkingData | None:
    """Call Mor_CUS_ParkingData for a single student ID."""
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        return None
    import pymssql  # type: ignore
    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host, port=settings.sis_mssql_port,
            user=settings.sis_mssql_user, password=settings.sis_mssql_password,
            database=settings.sis_mssql_database, login_timeout=5, timeout=10,
        )
        cur = conn.cursor(as_dict=True)
        cur.execute("EXEC Mor_CUS_ParkingData @id_num=%s", (id_num,))
        row = cur.fetchone()
        conn.close()
        return _parse_row(row, id_num) if row else None
    except Exception as e:
        logger.error("SIS lookup failed for %s: %s", id_num, e)
        return None


def _sis_batch_query(id_nums: list[str]) -> dict[str, StudentParkingData]:
    """Query SIS for multiple IDs on a single connection (runs in thread)."""
    import pymssql  # type: ignore
    results: dict[str, StudentParkingData] = {}
    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host, port=settings.sis_mssql_port,
            user=settings.sis_mssql_user, password=settings.sis_mssql_password,
            database=settings.sis_mssql_database, login_timeout=5, timeout=30,
        )
        cur = conn.cursor(as_dict=True)
        for id_num in id_nums:
            try:
                cur.execute("EXEC Mor_CUS_ParkingData @id_num=%s", (id_num,))
                row = cur.fetchone()
                if row:
                    data = _parse_row(row, id_num)
                    results[data.id_num] = data
            except Exception as e:
                logger.debug("SIS query failed for %s: %s", id_num, e)
        conn.close()
    except Exception as e:
        logger.error("SIS batch connection failed: %s", e)
    return results


async def lookup_batch_by_moravian_ids(id_nums: list[str]) -> dict[str, StudentParkingData]:
    """Look up multiple students by Moravian ID. Single connection, runs in thread.

    Returns dict keyed by id_num.
    """
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        return {}
    unique = list({n for n in id_nums if n and n.strip()})
    if not unique:
        return {}
    return await asyncio.to_thread(_sis_batch_query, unique)


async def is_res_life_staff(id_num: str) -> bool:
    """Check if a student is ResLife staff according to SIS."""
    data = await lookup_student_parking_data(id_num)
    return data.res_life_staff if data else False
