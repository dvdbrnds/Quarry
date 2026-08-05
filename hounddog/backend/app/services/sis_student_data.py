"""Query Moravian SIS (Colleague SQL Server) for student parking data.

Uses the Mor_CUS_ParkingStudentData stored procedure via the svc_parking user.
Returns housing status, division code, and accelerated nursing flag.
"""

import logging
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)

HOUSING_LABELS = {
    "R": "Resident",
    "C": "Commuter",
    "O": "Off Campus Release",
}


@dataclass
class StudentParkingData:
    id_num: str
    division_code: str
    housing_status: str  # R, C, or O
    housing_label: str
    accel_nursing: bool


async def lookup_student_parking_data(id_num: str) -> StudentParkingData | None:
    """Call Mor_CUS_ParkingStudentData stored procedure for a student ID.

    Returns None if SIS is not configured or student not found.
    """
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
        logger.debug("SIS MSSQL not configured — skipping student data lookup")
        return None

    import pymssql  # type: ignore

    try:
        conn = pymssql.connect(
            server=settings.sis_mssql_host,
            port=settings.sis_mssql_port,
            user=settings.sis_mssql_user,
            password=settings.sis_mssql_password,
            database=settings.sis_mssql_database,
        )
        cursor = conn.cursor(as_dict=True)
        cursor.execute("EXEC Mor_CUS_ParkingStudentData @id_num=%s", (id_num,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            logger.info("SIS lookup: no data for id_num=%s", id_num)
            return None

        housing = str(row.get("HousingStatus", "")).strip()
        return StudentParkingData(
            id_num=str(row.get("id_num", id_num)).strip(),
            division_code=str(row.get("DivisionCode", "")).strip(),
            housing_status=housing,
            housing_label=HOUSING_LABELS.get(housing, housing),
            accel_nursing=str(row.get("AccelNursing", "No")).strip().lower() == "yes",
        )
    except Exception as e:
        logger.error("SIS MSSQL lookup failed for id_num=%s: %s", id_num, e)
        return None


async def lookup_student_parking_data_batch(id_nums: list[str]) -> list[StudentParkingData]:
    """Look up multiple students. Returns results for those found."""
    results = []
    for id_num in id_nums:
        data = await lookup_student_parking_data(id_num)
        if data:
            results.append(data)
    return results
