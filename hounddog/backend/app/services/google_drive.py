"""
Google Drive backup upload service.

Uses a service account to upload backup files to a user-specified folder.
The service account must be granted Editor access to the target folder.
"""

import json
import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger("quarry.google_drive")


def _get_credentials():
    """Build Google credentials from the configured service account JSON."""
    from google.oauth2.service_account import Credentials

    creds_value = settings.google_drive_credentials_json
    if not creds_value:
        return None

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    # Support both inline JSON and a file path
    if creds_value.strip().startswith("{"):
        info = json.loads(creds_value)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        path = Path(creds_value)
        if path.exists():
            return Credentials.from_service_account_file(str(path), scopes=SCOPES)

    logger.error("GOOGLE_DRIVE_CREDENTIALS_JSON is set but not valid JSON or a readable path")
    return None


def upload_to_drive(filepath: Path, folder_id: str) -> str | None:
    """Upload a file to Google Drive in the specified folder.

    Returns the Drive file ID on success, None on failure.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _get_credentials()
    if not creds:
        logger.warning("Google Drive credentials not configured — skipping upload")
        return None

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        file_metadata = {
            "name": filepath.name,
            "parents": [folder_id],
        }

        media = MediaFileUpload(
            str(filepath),
            mimetype="application/json",
            resumable=True,
        )

        result = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,webViewLink",
        ).execute()

        logger.info(
            "Uploaded backup to Google Drive: %s (id=%s)",
            result.get("name"),
            result.get("id"),
        )
        return result.get("id")

    except Exception as e:
        logger.error("Google Drive upload failed: %s", e, exc_info=True)
        return None


def test_drive_connection(folder_id: str) -> dict:
    """Test that the service account can write to the specified folder.

    Returns {"ok": True, "folder_name": "..."} or {"ok": False, "error": "..."}.
    """
    from googleapiclient.discovery import build

    creds = _get_credentials()
    if not creds:
        return {"ok": False, "error": "Google Drive credentials not configured. Set GOOGLE_DRIVE_CREDENTIALS_JSON in environment."}

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        folder = service.files().get(
            fileId=folder_id,
            fields="id,name,mimeType",
        ).execute()

        if folder.get("mimeType") != "application/vnd.google-apps.folder":
            return {"ok": False, "error": f"'{folder.get('name')}' is not a folder"}

        return {"ok": True, "folder_name": folder.get("name")}

    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "notFound" in error_msg:
            return {"ok": False, "error": "Folder not found. Make sure the folder is shared with the service account email."}
        return {"ok": False, "error": f"Connection failed: {error_msg}"}
