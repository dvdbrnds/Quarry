#!/usr/bin/env python3
"""
Test PlateRecognizer API against Bird Dog video footage.
Extracts frames, sends to API, deduplicates, and outputs comparison CSV.

Usage:
    python3 test_platerecognizer.py --api-key YOUR_TOKEN --video /path/to/video.mp4
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("Installing requests...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

API_URL = "https://api.platerecognizer.com/v1/plate-reader/"
FRAME_RATE = 2  # frames per second to extract


def extract_frames(video_path: str, output_dir: str, fps: int = FRAME_RATE) -> list[str]:
    """Extract frames from video at given fps using ffmpeg."""
    pattern = os.path.join(output_dir, "frame_%05d.jpg")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "2",  # high quality JPEG
        pattern,
        "-y", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


def recognize_plate(image_path: str, api_key: str, regions: list[str] = None) -> dict:
    """Send a single frame to PlateRecognizer API."""
    headers = {"Authorization": f"Token {api_key}"}
    with open(image_path, "rb") as fp:
        data = {}
        if regions:
            data["regions"] = json.dumps(regions)
        response = requests.post(API_URL, headers=headers, files={"upload": fp}, data=data)

    if response.status_code == 429:
        print("  Rate limited, waiting 2s...")
        time.sleep(2)
        return recognize_plate(image_path, api_key, regions)

    if response.status_code == 403:
        print(f"ERROR: API returned 403 Forbidden. Check your API key.")
        sys.exit(1)

    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Test PlateRecognizer API on video")
    parser.add_argument("--api-key", required=True, help="PlateRecognizer API token")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--fps", type=int, default=FRAME_RATE, help="Frames per second to extract")
    parser.add_argument("--regions", nargs="+", default=["us-pa", "us-nj"], help="Region hints")
    parser.add_argument("--output", default=None, help="Output CSV path")
    args = parser.parse_args()

    video_path = os.path.expanduser(args.video)
    if not os.path.exists(video_path):
        print(f"Video not found: {video_path}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"platerecognizer_results_{timestamp}.csv"
    )

    print(f"Video:   {video_path}")
    print(f"FPS:     {args.fps}")
    print(f"Regions: {args.regions}")
    print(f"Output:  {output_path}")
    print()

    with tempfile.TemporaryDirectory(prefix="birddog_frames_") as tmpdir:
        print("Extracting frames...")
        frames = extract_frames(video_path, tmpdir, args.fps)
        print(f"Extracted {len(frames)} frames\n")

        all_reads: list[dict] = []
        seen_plates: dict[str, dict] = {}  # plate -> best read info

        for i, frame_path in enumerate(frames):
            frame_time = i / args.fps
            mins, secs = divmod(frame_time, 60)
            time_str = f"{int(mins)}:{secs:05.2f}"

            sys.stdout.write(f"\rProcessing frame {i+1}/{len(frames)} ({time_str})...")
            sys.stdout.flush()

            try:
                result = recognize_plate(frame_path, args.api_key, args.regions)
            except Exception as e:
                print(f"\n  Error on frame {i+1}: {e}")
                continue

            for r in result.get("results", []):
                plate_text = r["plate"].upper()
                confidence = r["dscore"]  # detection score
                ocr_conf = r["score"]     # OCR score
                region = r.get("region", {}).get("code", "unknown")

                candidates = [c["plate"].upper() for c in r.get("candidates", [])[:5]]

                read = {
                    "frame": i + 1,
                    "time": time_str,
                    "plate": plate_text,
                    "ocr_confidence": round(ocr_conf, 4),
                    "detection_confidence": round(confidence, 4),
                    "region": region,
                    "candidates": ", ".join(candidates),
                    "vehicle_type": r.get("vehicle", {}).get("type", ""),
                }
                all_reads.append(read)

                if plate_text not in seen_plates or ocr_conf > seen_plates[plate_text]["ocr_confidence"]:
                    seen_plates[plate_text] = read

            time.sleep(0.05)  # gentle rate limiting

        print(f"\n\nDone! {len(all_reads)} total reads, {len(seen_plates)} unique plates\n")

        # Write detailed CSV (every read)
        detail_path = output_path.replace(".csv", "_detail.csv")
        with open(detail_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "frame", "time", "plate", "ocr_confidence",
                "detection_confidence", "region", "candidates", "vehicle_type"
            ])
            writer.writeheader()
            writer.writerows(all_reads)

        # Write summary CSV (unique plates, best confidence)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "plate", "ocr_confidence", "detection_confidence",
                "region", "candidates", "vehicle_type", "first_seen"
            ])
            writer.writeheader()
            for plate_text in sorted(seen_plates.keys()):
                row = seen_plates[plate_text]
                writer.writerow({
                    "plate": row["plate"],
                    "ocr_confidence": row["ocr_confidence"],
                    "detection_confidence": row["detection_confidence"],
                    "region": row["region"],
                    "candidates": row["candidates"],
                    "vehicle_type": row["vehicle_type"],
                    "first_seen": row["time"],
                })

        print(f"Summary: {output_path}")
        print(f"Detail:  {detail_path}")
        print()

        # Print summary table
        print(f"{'PLATE':<12} {'OCR':>6} {'DET':>6} {'REGION':<10} CANDIDATES")
        print("-" * 70)
        for plate_text in sorted(seen_plates.keys()):
            r = seen_plates[plate_text]
            print(f"{r['plate']:<12} {r['ocr_confidence']:>6.3f} {r['detection_confidence']:>6.3f} {r['region']:<10} {r['candidates']}")


if __name__ == "__main__":
    main()
