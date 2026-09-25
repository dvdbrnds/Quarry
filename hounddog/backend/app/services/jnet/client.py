"""
JNET web service client.

Handles communication with Pennsylvania's Justice Network (JNET) for
license plate and registered owner lookups.

CRITICAL: CJI response data is NEVER logged. Only query metadata
(timestamp, user, plate, success/failure, response time) is recorded.
"""

import ssl
import time

import httpx
import structlog

from .config import jnet_settings
from .models import (
    JNETPlateResult,
    JNETOwnerResult,
    JNETVehicleInfo,
    JNETOwnerInfo,
    JNETError,
)

logger = structlog.get_logger("quarry.jnet.client")


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context enforcing TLS 1.2+ with mTLS client cert."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if jnet_settings.jnet_ca_bundle_path:
        ctx.load_verify_locations(jnet_settings.jnet_ca_bundle_path)

    if jnet_settings.jnet_client_cert_path and jnet_settings.jnet_client_key_path:
        ctx.load_cert_chain(
            certfile=jnet_settings.jnet_client_cert_path,
            keyfile=jnet_settings.jnet_client_key_path,
        )

    return ctx


class JNETClient:
    """Async client for JNET web services with mTLS authentication."""

    def __init__(self) -> None:
        self._base_url = jnet_settings.jnet_base_url
        self._ori = jnet_settings.jnet_ori
        self._timeout = jnet_settings.jnet_timeout_seconds
        self._mock_mode = not self._base_url

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._mock_mode:
            return httpx.AsyncClient(timeout=self._timeout)

        ssl_ctx = _build_ssl_context()
        return httpx.AsyncClient(
            verify=ssl_ctx,
            timeout=self._timeout,
        )

    async def plate_lookup(
        self, plate_number: str, state: str = "PA"
    ) -> tuple[JNETPlateResult, int]:
        """
        Look up a license plate via JNET.

        Returns (result, response_time_ms).
        Raises JNETError on failure.
        """
        start = time.monotonic()

        if self._mock_mode:
            return self._mock_plate_response(plate_number, state), int(
                (time.monotonic() - start) * 1000
            )

        try:
            async with self._get_http_client() as client:
                resp = await client.post(
                    f"{self._base_url}/plate-inquiry",
                    json={
                        "ori": self._ori,
                        "plateNumber": plate_number,
                        "plateState": state,
                    },
                    headers={"Content-Type": "application/json"},
                )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code != 200:
                # Log failure metadata only — never CJI content
                logger.warning(
                    "jnet_plate_lookup_failed",
                    plate=plate_number,
                    state=state,
                    status_code=resp.status_code,
                    elapsed_ms=elapsed_ms,
                )
                raise JNETError(
                    f"JNET returned status {resp.status_code}",
                    status_code=resp.status_code,
                )

            data = resp.json()
            result = self._parse_plate_response(data, plate_number, state)

            logger.info(
                "jnet_plate_lookup_success",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
            )

            return result, elapsed_ms

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "jnet_plate_lookup_timeout",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
            )
            raise JNETError("JNET request timed out")
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "jnet_plate_lookup_error",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
            raise JNETError(f"JNET communication error: {exc}")

    async def registered_owner_lookup(
        self, plate_number: str, state: str = "PA"
    ) -> tuple[JNETOwnerResult, int]:
        """
        Look up registered owner via JNET.

        Returns (result, response_time_ms).
        Raises JNETError on failure.
        """
        start = time.monotonic()

        if self._mock_mode:
            return self._mock_owner_response(plate_number, state), int(
                (time.monotonic() - start) * 1000
            )

        try:
            async with self._get_http_client() as client:
                resp = await client.post(
                    f"{self._base_url}/owner-inquiry",
                    json={
                        "ori": self._ori,
                        "plateNumber": plate_number,
                        "plateState": state,
                    },
                    headers={"Content-Type": "application/json"},
                )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code != 200:
                logger.warning(
                    "jnet_owner_lookup_failed",
                    plate=plate_number,
                    state=state,
                    status_code=resp.status_code,
                    elapsed_ms=elapsed_ms,
                )
                raise JNETError(
                    f"JNET returned status {resp.status_code}",
                    status_code=resp.status_code,
                )

            data = resp.json()
            result = self._parse_owner_response(data, plate_number, state)

            logger.info(
                "jnet_owner_lookup_success",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
            )

            return result, elapsed_ms

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "jnet_owner_lookup_timeout",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
            )
            raise JNETError("JNET request timed out")
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "jnet_owner_lookup_error",
                plate=plate_number,
                state=state,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
            raise JNETError(f"JNET communication error: {exc}")

    # -- Response parsing (real JNET) ------------------------------------------

    @staticmethod
    def _parse_plate_response(
        data: dict, plate_number: str, state: str
    ) -> JNETPlateResult:
        vehicle = data.get("vehicle", {})
        owner = data.get("owner", {})
        return JNETPlateResult(
            vehicle=JNETVehicleInfo(
                plate_number=plate_number,
                plate_state=state,
                vin=vehicle.get("vin"),
                year=vehicle.get("year"),
                make=vehicle.get("make"),
                model=vehicle.get("model"),
                color=vehicle.get("color"),
                body_style=vehicle.get("bodyStyle"),
                registration_status=vehicle.get("registrationStatus"),
                registration_expiry=vehicle.get("registrationExpiry"),
            ),
            owner=JNETOwnerInfo(
                first_name=owner.get("firstName"),
                last_name=owner.get("lastName"),
                middle_name=owner.get("middleName"),
                address_line1=owner.get("addressLine1"),
                address_line2=owner.get("addressLine2"),
                city=owner.get("city"),
                state=owner.get("state"),
                zip_code=owner.get("zipCode"),
                date_of_birth=owner.get("dateOfBirth"),
                drivers_license=owner.get("driversLicense"),
            ) if owner else None,
        )

    @staticmethod
    def _parse_owner_response(
        data: dict, plate_number: str, state: str
    ) -> JNETOwnerResult:
        owner = data.get("owner", {})
        vehicle = data.get("vehicle", {})
        return JNETOwnerResult(
            owner=JNETOwnerInfo(
                first_name=owner.get("firstName"),
                last_name=owner.get("lastName"),
                middle_name=owner.get("middleName"),
                address_line1=owner.get("addressLine1"),
                address_line2=owner.get("addressLine2"),
                city=owner.get("city"),
                state=owner.get("state"),
                zip_code=owner.get("zipCode"),
                date_of_birth=owner.get("dateOfBirth"),
                drivers_license=owner.get("driversLicense"),
            ) if owner else None,
            vehicle=JNETVehicleInfo(
                plate_number=plate_number,
                plate_state=state,
                vin=vehicle.get("vin"),
                year=vehicle.get("year"),
                make=vehicle.get("make"),
                model=vehicle.get("model"),
                color=vehicle.get("color"),
                body_style=vehicle.get("bodyStyle"),
                registration_status=vehicle.get("registrationStatus"),
                registration_expiry=vehicle.get("registrationExpiry"),
            ) if vehicle else None,
        )

    # -- Mock responses (used when JNET_BASE_URL is empty) ---------------------

    @staticmethod
    def _mock_plate_response(plate_number: str, state: str) -> JNETPlateResult:
        return JNETPlateResult(
            vehicle=JNETVehicleInfo(
                plate_number=plate_number,
                plate_state=state,
                vin="1HGBH41JXMN109186",
                year=2021,
                make="Honda",
                model="Civic",
                color="Blue",
                body_style="Sedan",
                registration_status="Valid",
                registration_expiry="2027-03-15",
            ),
            owner=JNETOwnerInfo(
                first_name="John",
                last_name="Doe",
                middle_name="Q",
                address_line1="123 Main St",
                city="Bethlehem",
                state="PA",
                zip_code="18018",
            ),
        )

    @staticmethod
    def _mock_owner_response(plate_number: str, state: str) -> JNETOwnerResult:
        return JNETOwnerResult(
            owner=JNETOwnerInfo(
                first_name="John",
                last_name="Doe",
                middle_name="Q",
                address_line1="123 Main St",
                city="Bethlehem",
                state="PA",
                zip_code="18018",
            ),
            vehicle=JNETVehicleInfo(
                plate_number=plate_number,
                plate_state=state,
                vin="1HGBH41JXMN109186",
                year=2021,
                make="Honda",
                model="Civic",
                color="Blue",
            ),
        )
