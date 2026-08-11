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

# Cache: email → (StudentParkingData | None, timestamp)
_sis_cache: dict[str, tuple[StudentParkingData | None, float]] = {}
# Cache: email → (moravian_id | None, timestamp)
_okta_id_cache: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL = 600  # 10 minutes


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
    """Call Mor_CUS_ParkingData stored procedure for a single student ID."""
    if not settings.sis_mssql_host or not settings.sis_mssql_password:
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
            return None
        return _parse_row(row, id_num)
    except Exception as e:
        logger.error("SIS MSSQL lookup failed for id_num=%s: %s", id_num, e)
        return None


def _sis_batch_query(id_nums: list[str]) -> dict[str, StudentParkingData]:
    """Query SIS for multiple IDs using a single DB connection (sync, run in thread)."""
    import pymssql  # type: ignore

    results: dict[str, StudentParkingData] = {}
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
        cursor = conn.cursor(as_dict=True)
        for id_num in id_nums:
            try:
                cursor.execute("EXEC Mor_CUS_ParkingData @id_num=%s", (id_num,))
                row = cursor.fetchone()
                if row:
                    data = _parse_row(row, id_num)
                    results[data.id_num] = data
            except Exception as e:
                logger.debug("SIS query failed for id_num=%s: %s", id_num, e)
        conn.close()
    except Exception as e:
        logger.error("SIS MSSQL batch connection failed: %s", e)
    return results


async def lookup_student_parking_data_batch(id_nums: list[str]) -> dict[str, StudentParkingData]:
    """Look up multiple students using a single connection. Returns dict keyed by id_num."""
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


async def _resolve_moravian_ids_batch(emails: list[str]) -> dict[str, str]:
    """Resolve Moravian numeric IDs from Okta for a batch of emails.

    Uses an in-memory cache and concurrent HTTP requests (max 20 at a time).
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
        if cached and (now - cached[1]) < _CACHE_TTL:
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

    Returns a dict keyed by lowercase email. Uses a result cache so repeated
    calls within 10 minutes are instant.
    """
    now = time.monotonic()
    result: dict[str, StudentParkingData] = {}
    need_resolve: list[str] = []

    for email in emails:
        em = (email or "").strip().lower()
        if not em or em in result:
            continue
        cached = _sis_cache.get(em)
        if cached and (now - cached[1]) < _CACHE_TTL:
            if cached[0]:
                result[em] = cached[0]
        else:
            need_resolve.append(em)

    if not need_resolve:
        logger.info("SIS batch: %d emails, all from cache", len(emails))
        return result

    email_to_id = await _resolve_moravian_ids_batch(need_resolve)

    unique_ids = list(set(email_to_id.values()))
    sis_by_id = await lookup_student_parking_data_batch(unique_ids) if unique_ids else {}

    for em in need_resolve:
        mid = email_to_id.get(em)
        data = sis_by_id.get(mid) if mid else None
        _sis_cache[em] = (data, time.monotonic())
        if data:
            result[em] = data

    logger.info("SIS batch: %d emails, %d resolved, %d with SIS data",
                len(emails), len(email_to_id), len(result))
    return result
