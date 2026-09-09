"""Plate normalization — strips dashes, spaces, and special characters.

Used everywhere plates are stored or compared so that 'MRM-8565' and 'MRM8565'
always match, regardless of how the student entered the plate.
"""

import re

_STRIP_RE = re.compile(r"[\s\-\.•·]+")


def normalize_plate(plate: str) -> str:
    """Normalize a license plate string for storage and comparison.

    Uppercases, strips dashes, spaces, dots, and other separators.
    """
    return _STRIP_RE.sub("", plate.strip().upper())
