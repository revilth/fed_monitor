"""
Google Drive integration. Mirrors the local data/ structure into
/FedMonitor/ on the user's Drive.

Auth supports two modes:
  - Service account: set GOOGLE_DRIVE_CREDENTIALS_FILE to a service account JSON
  - OAuth (user account): set GOOGLE_DRIVE_CREDENTIALS_FILE to an OAuth client
    secrets JSON; a token.json is created on first run via browser flow.
"""
import logging
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _DRIVE_AVAILABLE = True
except ImportError:
    _DRIVE_AVAILABLE = False
    logger.warning("google-api-python-client not installed; Drive upload disabled.")


_service = None
_folder_cache: dict[str, str] = {}  # path -> folder_id


def _get_service():
    global _service
    if _service:
        return _service
    if not _DRIVE_AVAILABLE:
        return None

    creds_file = config.GOOGLE_DRIVE_CREDENTIALS_FILE
    if not creds_file or not Path(creds_file).exists():
        logger.warning("No Google Drive credentials file configured.")
        return None

    creds = None
    token_file = config.GOOGLE_DRIVE_TOKEN_FILE

    # Try loading existing token
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), config.GOOGLE_DRIVE_SCOPES)
        except Exception:
            pass

    if creds and creds.valid:
        pass
    elif creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    else:
        # Check if it's a service account
        import json
        with open(creds_file) as f:
            key_data = json.load(f)
        if key_data.get("type") == "service_account":
            creds = service_account.Credentials.from_service_account_file(
                creds_file, scopes=config.GOOGLE_DRIVE_SCOPES
            )
        else:
            # OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, config.GOOGLE_DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json())

    _service = build("drive", "v3", credentials=creds)
    return _service


def _get_or_create_folder(name: str, parent_id: str | None = None) -> str:
    cache_key = f"{parent_id or 'root'}/{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    svc = _get_service()
    if not svc:
        return ""

    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    results = svc.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])

    if files:
        folder_id = files[0]["id"]
    else:
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            meta["parents"] = [parent_id]
        folder = svc.files().create(body=meta, fields="id").execute()
        folder_id = folder["id"]

    _folder_cache[cache_key] = folder_id
    return folder_id


def _ensure_path(parts: list[str]) -> str:
    """Ensure nested folder path exists; return leaf folder ID."""
    parent_id = None
    for part in parts:
        parent_id = _get_or_create_folder(part, parent_id)
    return parent_id or ""


def upload_file(local_path: Path, drive_path_parts: list[str]) -> str:
    """Upload a local file to Drive; return the file ID."""
    svc = _get_service()
    if not svc:
        logger.debug("Drive not configured; skipping upload.")
        return ""

    folder_id = _ensure_path(drive_path_parts[:-1])
    filename = drive_path_parts[-1]

    # Check if file already exists
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    existing = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    if existing:
        logger.debug(f"Drive file already exists: {filename}")
        return existing[0]["id"]

    meta = {"name": filename, "parents": [folder_id]}
    media = MediaFileUpload(str(local_path), mimetype="text/plain")
    file = svc.files().create(body=meta, media_body=media, fields="id").execute()
    logger.info(f"Uploaded to Drive: {'/'.join(drive_path_parts)}")
    return file["id"]


def upload_raw_speech(local_path: Path, speaker: str, year: str, filename: str) -> str:
    parts = [config.GOOGLE_DRIVE_ROOT_FOLDER, "raw", "speeches", year, speaker, filename]
    return upload_file(local_path, parts)


def upload_scored_speech(local_path: Path, filename: str) -> str:
    parts = [config.GOOGLE_DRIVE_ROOT_FOLDER, "scored", "speeches", filename]
    return upload_file(local_path, parts)


def upload_report(local_path: Path, report_type: str, filename: str) -> str:
    parts = [config.GOOGLE_DRIVE_ROOT_FOLDER, "reports", report_type, filename]
    return upload_file(local_path, parts)


def upload_fomc_doc(local_path: Path, doc_type: str, filename: str) -> str:
    folder_map = {
        "statement": "statements",
        "minutes": "minutes",
        "testimony": "testimony",
        "pressconf": "pressconferences",
    }
    subfolder = folder_map.get(doc_type, doc_type)
    parts = [config.GOOGLE_DRIVE_ROOT_FOLDER, "raw", subfolder, filename]
    return upload_file(local_path, parts)
