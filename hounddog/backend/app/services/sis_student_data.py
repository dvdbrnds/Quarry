"""Query Moravian SIS (Jenzabar SQL Server) for student parking data.

Uses the Mor_CUS_ParkingData stored procedure via the svc_parking user.
Returns housing status, division code, class code, accelerated nursing flag,
ResLife staff status, and employee status.
"""

import asyncio
import logging
import time
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

# In-memory cache: email → (moravian_id, timestamp)
_okta_id_cache: dict[str, tuple[str | None, float]] = {}
_OKTA_CACHE_TTL = 600  # 10 minutes


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
            login_timeout=5,
            timeout=10,
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


async def _resolve_moravian_ids_batch(emails: list[str]) -> dict[str, str]:
    """Resolve Moravian numeric IDs from Okta for a batch of emails.

    Uses an in-memory cache and concurrent HTTP requests (max 20 at a time).
    Returns {lowercase_email: moravian_id} for those found.
    """
    if not settings.okta_domain or not settings.okta_api_token:
        return {}

    now = time.monotonic()
    result: dict[str, str] = {}
    uncached: list[str] = []

    for email in emails:
        em = (email or "").strip().lower()
        if not em or em in result:
            continue
        cached = _okta_id_cache.get(em)
        if cached and (now - cached[1]) < _OKTA_CACHE_TTL:
            if cached[0]:
                result[em] = cached[0]
        else:
            uncached.append(em)

    if not uncached:
        return result

    import httpx

    sem = asyncio.Semaphore(20)

    async def _lookup_one(client: httpx.AsyncClient, em: str) -> None:
        async with sem:
            try:
                res = await client.get(
                    f"https://{settings.okta_domain}/api/v1/users/{em}",
                    headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                    timeout=10,
                )
                if res.status_code == 200:
                    profile = res.json().get("profile", {})
                    for field in ("altId", "studentId", "employeeNumber", "moravianId"):
                        val = profile.get(field)
                        if val:
                            mid = str(val).split("@")[0].strip()
                            _okta_id_cache[em] = (mid, time.monotonic())
                            result[em] = mid
                            return
                _okta_id_cache[em] = (None, time.monotonic())
            except Exception as e:
                logger.debug("Okta altId lookup failed for %s: %s", em, e)
                _okta_id_cache[em] = (None, time.monotonic())

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_lookup_one(client, em) for em in uncached])

    logger.info("Okta batch resolve: %d emails → %d IDs (%d cached, %d looked up)",
                len(emails), len(result), len(emails) - len(uncached), len(uncached))
    return result


async def lookup_batch_by_emails(emails: list[str]) -> dict[str, StudentParkingData]:
    """Resolve Moravian IDs from Okta emails, then batch-query SIS.

    Returns a dict keyed by lowercase email for those found.
    """
    email_to_id = await _resolve_moravian_ids_batch(emails)
    if not email_to_id:
        return {}

    unique_ids = list(set(email_to_id.values()))
    sis_by_id = await lookup_student_parking_data_batch(unique_ids)

    result: dict[str, StudentParkingData] = {}
    for em, mid in email_to_id.items():
        data = sis_by_id.get(mid)
        if data:
            result[em] = data
    return result
