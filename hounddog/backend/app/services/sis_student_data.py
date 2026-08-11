"""Query Moravian SIS (Jenzabar SQL Server) for student parking data.

Uses the Mor_CUS_ParkingData stored procedure via the svc_parking user.
Returns housing status, division code, class code, accelerated nursing flag,
ResLife staff status, and employee status.
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
    housing_status: str  # R, C, or O
    housing_label: str
    class_code: str  # FR, SO, JR, SR for undergrads
    class_label: str
    accel_nursing: bool
    res_life_staff: bool
    employee: bool


async def lookup_student_parking_data(id_num: str) -> StudentParkingData | None:
    """Call Mor_CUS_ParkingData stored procedure for a student ID.

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
        cursor.execute("EXEC Mor_CUS_ParkingData @id_num=%s", (id_num,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            logger.info("SIS lookup: no data for id_num=%s", id_num)
            return None

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
    except Exception as e:
        logger.error("SIS MSSQL lookup failed for id_num=%s: %s", id_num, e)
        return None


async def lookup_student_parking_data_batch(id_nums: list[str]) -> dict[str, StudentParkingData]:
    """Look up multiple students. Returns a dict keyed by id_num for those found."""
    results: dict[str, StudentParkingData] = {}
    for id_num in id_nums:
        if not id_num or id_num in results:
            continue
        data = await lookup_student_parking_data(id_num)
        if data:
            results[data.id_num] = data
    return results


async def is_res_life_staff(id_num: str) -> bool:
    """Check if a student is ResLife staff according to SIS."""
    data = await lookup_student_parking_data(id_num)
    return data.res_life_staff if data else False


async def _resolve_moravian_id(email: str) -> str | None:
    """Look up a user's Moravian numeric ID (altId) from Okta by email."""
    if not settings.okta_domain or not settings.okta_api_token:
        return None
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"https://{settings.okta_domain}/api/v1/users/{email}",
                headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                timeout=10,
            )
            if res.status_code != 200:
                return None
            profile = res.json().get("profile", {})
            for field in ("altId", "studentId", "employeeNumber", "moravianId"):
                val = profile.get(field)
                if val:
                    return str(val).split("@")[0].strip()
    except Exception as e:
        logger.debug("Okta altId lookup failed for %s: %s", email, e)
    return None


async def lookup_batch_by_emails(emails: list[str]) -> dict[str, StudentParkingData]:
    """Resolve Moravian IDs from Okta emails, then batch-query SIS.

    Returns a dict keyed by lowercase email for those found.
    """
    email_to_id: dict[str, str] = {}
    for email in emails:
        em = (email or "").strip().lower()
        if not em or em in email_to_id:
            continue
        mid = await _resolve_moravian_id(em)
        if mid:
            email_to_id[em] = mid

    if not email_to_id:
        return {}

    sis_by_id = await lookup_student_parking_data_batch(list(email_to_id.values()))

    result: dict[str, StudentParkingData] = {}
    for em, mid in email_to_id.items():
        data = sis_by_id.get(mid)
        if data:
            result[em] = data
    return result
