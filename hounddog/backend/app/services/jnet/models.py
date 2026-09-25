"""
Pydantic models for JNET responses.

These are transit-only — they are NEVER written to the database.
CJI fields are annotated with Field(json_schema_extra={"cji": True})
for downstream awareness.
"""

from pydantic import BaseModel, Field
from typing import Any


class JNETVehicleInfo(BaseModel):
    """Vehicle registration data from JNET."""
    plate_number: str = Field(..., json_schema_extra={"cji": True})
    plate_state: str = Field("PA", json_schema_extra={"cji": True})
    vin: str | None = Field(None, json_schema_extra={"cji": True})
    year: int | None = Field(None, json_schema_extra={"cji": True})
    make: str | None = Field(None, json_schema_extra={"cji": True})
    model: str | None = Field(None, json_schema_extra={"cji": True})
    color: str | None = Field(None, json_schema_extra={"cji": True})
    body_style: str | None = Field(None, json_schema_extra={"cji": True})
    registration_status: str | None = Field(None, json_schema_extra={"cji": True})
    registration_expiry: str | None = Field(None, json_schema_extra={"cji": True})


class JNETOwnerInfo(BaseModel):
    """Registered owner data from JNET."""
    first_name: str | None = Field(None, json_schema_extra={"cji": True})
    last_name: str | None = Field(None, json_schema_extra={"cji": True})
    middle_name: str | None = Field(None, json_schema_extra={"cji": True})
    address_line1: str | None = Field(None, json_schema_extra={"cji": True})
    address_line2: str | None = Field(None, json_schema_extra={"cji": True})
    city: str | None = Field(None, json_schema_extra={"cji": True})
    state: str | None = Field(None, json_schema_extra={"cji": True})
    zip_code: str | None = Field(None, json_schema_extra={"cji": True})
    date_of_birth: str | None = Field(None, json_schema_extra={"cji": True})
    drivers_license: str | None = Field(None, json_schema_extra={"cji": True})


class JNETPlateResult(BaseModel):
    """Result of a JNET plate lookup. Transit-only — never persisted."""
    vehicle: JNETVehicleInfo | None = None
    owner: JNETOwnerInfo | None = None
    cjis_notice: str = (
        "This information is from JNET/CJIS and is for authorized law enforcement use only. "
        "Unauthorized access or disclosure is a federal offense."
    )


class JNETOwnerResult(BaseModel):
    """Result of a JNET registered owner lookup. Transit-only — never persisted."""
    owner: JNETOwnerInfo | None = None
    vehicle: JNETVehicleInfo | None = None
    cjis_notice: str = (
        "This information is from JNET/CJIS and is for authorized law enforcement use only. "
        "Unauthorized access or disclosure is a federal offense."
    )


class JNETError(Exception):
    """Raised on JNET communication failures."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)
