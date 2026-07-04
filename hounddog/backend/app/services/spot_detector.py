"""
AI-powered parking spot detection using satellite imagery.

Uses Google Maps Static API to capture a satellite view of a lot,
then sends it to Google Gemini for vision-based spot identification.
Swap the _call_gemini() function to use a different AI provider.
"""

import json
import logging
import math
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import types

from ..config import settings

log = logging.getLogger(__name__)

# Static Maps returns IMAGE_SIZE x IMAGE_SIZE logical pixels.
# scale=2 doubles the actual pixel count to give Gemini more detail,
# but the coordinate math still uses the logical size.
IMAGE_SIZE = 640
SCALE = 1
TILE_SIZE = 256


@dataclass
class DetectedSpot:
    number: int
    latitude: float
    longitude: float
    spot_type: str


def _bbox(boundary: list[dict]) -> tuple[float, float, float, float]:
    """Return (min_lat, min_lng, max_lat, max_lng) from boundary coords."""
    lats = [p["latitude"] for p in boundary]
    lngs = [p["longitude"] for p in boundary]
    return min(lats), min(lngs), max(lats), max(lngs)


def _fit_zoom(min_lat: float, min_lng: float, max_lat: float, max_lng: float) -> int:
    """Calculate the best zoom level so the lot fills most of the image."""
    lat_range = max_lat - min_lat
    lng_range = max_lng - min_lng

    for zoom in range(21, 0, -1):
        world_size = TILE_SIZE * (2 ** zoom)
        deg_per_px_lng = 360 / world_size
        mid_lat = (min_lat + max_lat) / 2
        deg_per_px_lat = 360 / (world_size * math.cos(math.radians(mid_lat)))
        pixels_lng = lng_range / deg_per_px_lng
        pixels_lat = lat_range / deg_per_px_lat
        if pixels_lng < IMAGE_SIZE * 0.85 and pixels_lat < IMAGE_SIZE * 0.85:
            return zoom
    return 15


def _latLng_from_pixel(
    px_x: float, px_y: float,
    center_lat: float, center_lng: float,
    zoom: int,
) -> tuple[float, float]:
    """Convert a logical pixel coordinate to lat/lng using Mercator projection."""
    scale = 2 ** zoom
    world_size = TILE_SIZE * scale

    center_x_world = (center_lng + 180) / 360 * world_size
    sin_lat = math.sin(math.radians(center_lat))
    center_y_world = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * world_size

    dx = px_x - IMAGE_SIZE / 2
    dy = px_y - IMAGE_SIZE / 2

    target_x = center_x_world + dx
    target_y = center_y_world + dy

    lng = target_x / world_size * 360 - 180
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * target_y / world_size)))
    lat = math.degrees(lat_rad)

    return lat, lng


async def _fetch_satellite_image(
    center_lat: float, center_lng: float, zoom: int,
) -> bytes:
    """Download a high-res satellite image from Google Maps Static API."""
    url = "https://maps.googleapis.com/maps/api/staticmap"
    params = {
        "center": f"{center_lat},{center_lng}",
        "zoom": str(zoom),
        "size": f"{IMAGE_SIZE}x{IMAGE_SIZE}",
        "scale": str(SCALE),
        "maptype": "satellite",
        "key": settings.google_maps_static_key or settings.google_maps_api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.content


DETECTION_PROMPT = """\
You are analyzing a high-resolution satellite image of a parking lot.

Your task is to identify every individual parking bay (space) visible in the
image by looking for the painted white or yellow line markings that delineate
each bay. Place your coordinate at the CENTER of each bay, not on the lines.

For each spot return a JSON object with:
- "number": integer, sequential starting at 1
- "x": fractional horizontal position (0.0 = left edge, 1.0 = right edge)
- "y": fractional vertical position (0.0 = top edge, 1.0 = bottom edge)
- "spot_type": one of "standard", "ev", "handicap", "reserved", "loading"
  Use "handicap" for any spot with the wheelchair symbol or blue paint.
  Use "ev" for spots near charging stations.
  Default to "standard" if unsure.

Number the spots row by row, starting from the top-left of the lot, moving
left to right within each row, then top to bottom across rows.

Return ONLY a valid JSON array with no markdown fences and no commentary.
Example: [{"number":1,"x":0.12,"y":0.15,"spot_type":"standard"}]

If no parking bays are visible, return: []"""


async def _call_gemini(image_bytes: bytes) -> list[dict]:
    """Send the satellite image to Gemini and parse the spot positions."""
    client = genai.Client(api_key=settings.gemini_api_key)

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            DETECTION_PROMPT,
        ],
    )

    raw = (response.text or "").strip()
    if not raw:
        raise ValueError("Gemini returned an empty response")

    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    spots = json.loads(raw)
    if not isinstance(spots, list):
        raise ValueError("Gemini did not return a JSON array")
    return spots


async def detect_spots(boundary: list[dict]) -> list[DetectedSpot]:
    """Full pipeline: fetch satellite image, run AI detection, convert coords."""
    if len(boundary) < 3:
        raise ValueError("Lot must have a boundary with at least 3 points")

    min_lat, min_lng, max_lat, max_lng = _bbox(boundary)
    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2
    zoom = _fit_zoom(min_lat, min_lng, max_lat, max_lng)

    log.info(
        "Fetching satellite image: center=(%.6f, %.6f) zoom=%d scale=%d",
        center_lat, center_lng, zoom, SCALE,
    )
    image_bytes = await _fetch_satellite_image(center_lat, center_lng, zoom)

    log.info("Sending %d bytes to Gemini for spot detection", len(image_bytes))
    raw_spots = await _call_gemini(image_bytes)
    log.info("Gemini detected %d spots", len(raw_spots))

    results: list[DetectedSpot] = []
    for s in raw_spots:
        px_x = s["x"] * IMAGE_SIZE
        px_y = s["y"] * IMAGE_SIZE
        lat, lng = _latLng_from_pixel(px_x, px_y, center_lat, center_lng, zoom)
        spot_type = s.get("spot_type", "standard")
        if spot_type not in ("standard", "ev", "handicap", "reserved", "loading"):
            spot_type = "standard"
        results.append(DetectedSpot(
            number=s.get("number", len(results) + 1),
            latitude=lat,
            longitude=lng,
            spot_type=spot_type,
        ))

    return results
