"""Tests for JNET input validation — plate number regex, injection protection."""

import re
import pytest
from pydantic import ValidationError

from app.routers.jnet import PlateLookupRequest, PLATE_REGEX


class TestPlateRegex:
    """Verify the plate number regex enforces 1-8 alphanumeric characters."""

    def test_valid_plates(self):
        valid = ["ABC1234", "XYZ789", "A", "12345678", "PA1234", "Z"]
        for plate in valid:
            assert PLATE_REGEX.match(plate), f"{plate} should be valid"

    def test_invalid_plates(self):
        invalid = ["", "ABC12345678", "abc-123", "ABC 123", "ABC!@#", "ABC\n123"]
        for plate in invalid:
            assert not PLATE_REGEX.match(plate), f"{plate} should be invalid"


class TestPlateLookupRequest:
    """Test Pydantic model validation."""

    def test_valid_request(self):
        req = PlateLookupRequest(plate_number="ABC1234")
        assert req.plate_number == "ABC1234"
        assert req.state == "PA"

    def test_normalizes_lowercase(self):
        req = PlateLookupRequest(plate_number="abc1234")
        assert req.plate_number == "ABC1234"

    def test_strips_dashes(self):
        req = PlateLookupRequest(plate_number="ABC-1234")
        assert req.plate_number == "ABC1234"

    def test_strips_spaces(self):
        req = PlateLookupRequest(plate_number="ABC 1234")
        assert req.plate_number == "ABC1234"

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            PlateLookupRequest(plate_number="ABCDEFGHIJKLM")

    def test_rejects_special_characters(self):
        with pytest.raises(ValidationError):
            PlateLookupRequest(plate_number="ABC!@#$")

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            PlateLookupRequest(plate_number="")

    def test_sql_injection_rejected(self):
        with pytest.raises(ValidationError):
            PlateLookupRequest(plate_number="'; DROP TABLE--")

    def test_xss_rejected(self):
        with pytest.raises(ValidationError):
            PlateLookupRequest(plate_number="<script>alert(1)</script>")

    def test_state_normalization(self):
        req = PlateLookupRequest(plate_number="ABC1234", state="pa")
        assert req.state == "PA"

    def test_state_truncation(self):
        req = PlateLookupRequest(plate_number="ABC1234", state="PENN")
        assert req.state == "PE"
