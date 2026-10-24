#!/usr/bin/env python3
"""Upload a finished video to YouTube with OAuth 2.0 and resumable upload.

Design choices:

* Desktop-app OAuth flow with PKCE, offline access and a refresh token.
* One least-privilege scope by default (``youtube.force-ssl`` because this
  script also sets the thumbnail and captions).  ``--minimal-scope`` requests
  only ``youtube.upload`` when you do not need those extras.
* Client secrets and tokens live outside the repository (default:
  ``~/.config/podcast-youtuber-agent/``), with mode 0600 on the token.
* Videos upload as **private** unless you explicitly pass
  ``--privacy unlisted|public``.  Review first; publish deliberately.
* Resumable uploads with bounded exponential backoff on 429/5xx errors.
* YouTube's synthetic-media disclosure is set with
  ``status.containsSyntheticMedia=true`` for cloned-voice narration.

Setup is documented in SKILL.md.  This script never prints or commits tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "podcast-youtuber-agent"
DEFAULT_CLIENT_SECRETS = DEFAULT_CONFIG_DIR / "client_secret.json"
DEFAULT_TOKEN_FILE = DEFAULT_CONFIG_DIR / "token.json"
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
RETRIABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 6
CHUNK_SIZE = 8 * 1024 * 1024
REVOKE_URI = "https://oauth2.googleapis.com/revoke"


def _google():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "YouTube dependencies are not installed. Run:\n"
            "  uv sync --extra youtube\n"
            "or:\n"
            "  uv pip install google-api-python-client google-auth-oauthlib"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _ensure_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _warn_permissions(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        print(
            f"warning: {path} is readable by group/others (mode {mode:o}); "
            "run chmod 600 on it",
            file=sys.stderr,
        )


def _load_credentials(args, scopes: list[str], allow_login: bool):
    Request, Credentials, InstalledAppFlow, _, _, _ = _google()
    from google.auth.exceptions import RefreshError

    token_path = Path(args.token_file).expanduser()
    credentials = None
    if token_path.exists():
        _warn_permissions(token_path)
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
        except (ValueError, OSError) as exc:
            print(f"warning: could not read token file: {exc}", file=sys.stderr)
            credentials = None

    if credentials is not None:
        if getattr(credentials, "scopes", None):
            missing = set(scopes) - set(credentials.scopes)
            if missing:
                print(
                    "warning: token is missing requested scopes; re-authenticating",
                    file=sys.stderr,
                )
                credentials = None
        if credentials is not None and credentials.valid:
            return credentials
        if credentials is not None and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                _save_token(token_path, credentials)
                return credentials
            except RefreshError as exc:
                print(f"warning: token refresh failed: {exc}", file=sys.stderr)
                credentials = None

    if not allow_login:
        raise RuntimeError(
            f"no usable credentials at {token_path}; run this script with --auth first"
        )
    client_secrets = Path(args.client_secrets).expanduser()
    if not client_secrets.exists():
        raise RuntimeError(
            f"OAuth client secrets not found: {client_secrets}\n"
            "Create a Desktop-app OAuth client in Google Cloud, download the JSON, "
            "and place it there (never commit it)."
        )
    _warn_permissions(client_secrets)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets),
        scopes,
        autogenerate_code_verifier=True,
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message=(
            "Open this URL in your browser to authorize YouTube upload:\n{url}"
        ),
        success_message="Authorization complete. You can close this window.",
    )
    _save_token(token_path, credentials)
    return credentials


def _save_token(path: Path, credentials) -> None:
    _secure_dir(path.parent)
    payload = credentials.to_json()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload)
    _ensure_private_file(temp)
    temp.replace(path)
    _ensure_private_file(path)


def _youtube(args, scopes: list[str], allow_login: bool):
    _, _, _, build, _, _ = _google()
    credentials = _load_credentials(args, scopes, allow_login)
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def _revoke(args) -> int:
    path = Path(args.token_file).expanduser()
    if not path.exists():
        print(f"no token file at {path}")
        return 0
    try:
        token_data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read token: {exc}", file=sys.stderr)
        return 1
    token = token_data.get("refresh_token") or token_data.get("token")
    if token:
        data = urllib.parse.urlencode({"token": token}).encode()
        request = urllib.request.Request(
            REVOKE_URI,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                print(f"revocation HTTP {response.status}")
        except Exception as exc:  # noqa: BLE001 - network errors vary
            print(f"warning: revocation request failed: {exc}", file=sys.stderr)
    path.unlink(missing_ok=True)
    print(f"deleted {path}")
    return 0


def _channel(youtube) -> dict:
    response = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = response.get("items") or []
    if not items:
        raise RuntimeError("the authorized account has no YouTube channel")
    item = items[0]
    return {
        "id": item.get("id"),
        "title": item.get("snippet", {}).get("title"),
        "subscribers": item.get("statistics", {}).get("subscriberCount"),
    }


def _load_metadata(args) -> dict:
    data: dict = {}
    if args.metadata:
        path = Path(args.metadata).expanduser()
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read metadata {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("metadata must be a JSON object")

    if args.title:
        data["title"] = args.title
    if args.description:
        data["description"] = args.description
    if args.description_file:
        data["description"] = Path(args.description_file).expanduser().read_text()
    if args.tags is not None:
        data["tags"] = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    if args.category_id:
        data["categoryId"] = str(args.category_id)

    data.setdefault("title", Path(args.video).stem.replace("_", " ").replace("-", " ").title())
    data.setdefault("description", "")
    data.setdefault("tags", [])
    data.setdefault("categoryId", "28")
    if args.privacy:
        data["privacyStatus"] = args.privacy
    data.setdefault("privacyStatus", "private")
    if args.made_for_kids:
        data["selfDeclaredMadeForKids"] = True
    else:
        data.setdefault("selfDeclaredMadeForKids", False)
    if args.no_synthetic_media:
        data["containsSyntheticMedia"] = False
    else:
        data.setdefault("containsSyntheticMedia", True)
    data.setdefault("defaultLanguage", "en")
    data.setdefault("defaultAudioLanguage", "en")

    title = str(data["title"]).strip()
    description = str(data["description"])
    tags = data.get("tags") or []
    if not title or len(title) > 100:
        raise ValueError("title must be 1-100 characters")
    if len(description) > 5000:
        raise ValueError("description must be at most 5000 characters")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of strings")
    if sum(len(tag) for tag in tags) + max(0, len(tags) - 1) > 500:
        raise ValueError("tags exceed YouTube's 500-character limit")
    if not str(data["categoryId"]).isdigit():
        raise ValueError("categoryId must be numeric")
    if data["privacyStatus"] not in ("private", "unlisted", "public"):
        raise ValueError("privacyStatus must be private, unlisted or public")
    if not data["description"].strip():
        raise ValueError(
            "description is empty; include the source links, chapters and AI disclosure"
        )
    if args.publish_at:
        when = _parse_publish_at(args.publish_at)
        data["publishAt"] = when
        data["privacyStatus"] = "private"
    return data


def _parse_publish_at(value: str) -> str:
    raw = value.strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("--publish-at must be ISO 8601, e.g. 2026-11-01T18:00:00Z") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise ValueError("--publish-at must be in the future")
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _body(data: dict) -> dict:
    snippet = {
        "title": data["title"],
        "description": data["description"],
        "tags": data.get("tags") or [],
        "categoryId": str(data["categoryId"]),
        "defaultLanguage": data.get("defaultLanguage", "en"),
        "defaultAudioLanguage": data.get("defaultAudioLanguage", "en"),
    }
    status = {
        "privacyStatus": data.get("privacyStatus", "private"),
        "selfDeclaredMadeForKids": bool(data.get("selfDeclaredMadeForKids", False)),
        "containsSyntheticMedia": bool(data.get("containsSyntheticMedia", True)),
        "license": "youtube",
        "embeddable": True,
        "publicStatsViewable": True,
    }
    if data.get("publishAt"):
        status["publishAt"] = data["publishAt"]
    return {"snippet": snippet, "status": status}


def _sleep_backoff(attempt: int) -> None:
    time.sleep(min(60.0, (2 ** attempt) + 0.35 * attempt))


def _upload(youtube, args, data: dict, HttpError, MediaFileUpload) -> dict:
    video = Path(args.video)
    if not video.exists() or video.stat().st_size == 0:
        raise FileNotFoundError(f"video not found: {video}")
    media = MediaFileUpload(
        str(video),
        mimetype="video/mp4",
        chunksize=CHUNK_SIZE,
        resumable=True,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=_body(data),
        media_body=media,
        notifySubscribers=not args.no_notify,
    )
    response = None
    attempt = 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress:
                total = progress.total_size if progress.total_size is not None else "?"
                print(
                    f"upload: {progress.progress() * 100:5.1f}% "
                    f"({progress.resumable_progress}/{total} bytes)"
                )
            attempt = 0
        except HttpError as exc:
            status = getattr(exc.resp, "status", 0)
            if status in RETRIABLE_STATUS:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise
                print(
                    f"upload: HTTP {status}; retry {attempt}/{MAX_RETRIES}",
                    file=sys.stderr,
                )
                _sleep_backoff(attempt)
                continue
            if status == 401 and getattr(youtube, "_http", None):
                raise RuntimeError(
                    "upload authorization expired; run --auth again and retry"
                ) from exc
            raise
        except (socket.timeout, ConnectionError, TimeoutError) as exc:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            print(f"upload: network error; retry {attempt}/{MAX_RETRIES}: {exc}", file=sys.stderr)
            _sleep_backoff(attempt)
    return response


def _add_extras(youtube, args, video_id: str, HttpError, MediaFileUpload) -> list[str]:
    warnings: list[str] = []
    if args.thumbnail:
        thumbnail = Path(args.thumbnail).expanduser()
        if not thumbnail.exists():
            warnings.append(f"thumbnail not found: {thumbnail}")
        else:
            mime = "image/jpeg" if thumbnail.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumbnail), mimetype=mime),
                ).execute()
                print(f"thumbnail: {thumbnail}")
            except Exception as exc:  # noqa: BLE001 - keep the upload
                warnings.append(f"thumbnail failed: {exc}")
    if args.captions:
        captions = Path(args.captions).expanduser()
        if not captions.exists():
            warnings.append(f"captions not found: {captions}")
        else:
            try:
                youtube.captions().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "language": args.caption_language,
                            "name": args.caption_name,
                            "isDraft": False,
                        }
                    },
                    media_body=MediaFileUpload(
                        str(captions), mimetype="application/octet-stream"
                    ),
                ).execute()
                print(f"captions: {captions}")
            except Exception as exc:  # noqa: BLE001 - keep the upload
                warnings.append(f"captions failed: {exc}")
    if args.playlist:
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": args.playlist,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            print(f"playlist: {args.playlist}")
        except Exception as exc:  # noqa: BLE001 - keep the upload
            warnings.append(f"playlist failed: {exc}")
    return warnings


def _receipt_path(args, data: dict) -> Path:
    if args.receipt:
        return Path(args.receipt)
    return Path(args.video).parent / "youtube-upload.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", help="finished MP4")
    parser.add_argument("--metadata", help="JSON with title, description, tags, categoryId, privacyStatus")
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--description-file")
    parser.add_argument("--tags", help="comma-separated tags")
    parser.add_argument("--category-id", default=None, help="YouTube category id (default 28)")
    parser.add_argument("--privacy", default=None, choices=["private", "unlisted", "public"])
    parser.add_argument("--publish-at", help="ISO 8601 schedule; forces privacyStatus=private")
    parser.add_argument("--thumbnail")
    parser.add_argument("--captions", help="SRT or VTT sidecar")
    parser.add_argument("--caption-language", default="en")
    parser.add_argument("--caption-name", default="English")
    parser.add_argument("--playlist", help="playlist id")
    parser.add_argument("--made-for-kids", action="store_true")
    parser.add_argument(
        "--no-synthetic-media",
        action="store_true",
        help="do not set status.containsSyntheticMedia (not recommended for cloned voice)",
    )
    parser.add_argument("--minimal-scope", action="store_true", help="request youtube.upload only")
    parser.add_argument("--client-secrets", default=os.environ.get("YOUTUBE_CLIENT_SECRETS", str(DEFAULT_CLIENT_SECRETS)))
    parser.add_argument("--token-file", default=os.environ.get("YOUTUBE_TOKEN_FILE", str(DEFAULT_TOKEN_FILE)))
    parser.add_argument("--receipt", help="write upload receipt JSON here")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auth", action="store_true", help="authorize and print the channel")
    parser.add_argument("--check-auth", action="store_true", help="check the saved token")
    parser.add_argument("--revoke", action="store_true", help="revoke and delete the saved token")
    args = parser.parse_args(argv)

    if args.revoke:
        return _revoke(args)
    if args.auth or args.check_auth:
        scopes = [SCOPE_UPLOAD if args.minimal_scope else SCOPE_FORCE_SSL]
        try:
            youtube = _youtube(args, scopes, allow_login=args.auth)
            if args.minimal_scope:
                print("authorized with youtube.upload scope; channel read skipped")
            else:
                print(json.dumps(_channel(youtube), indent=2))
        except Exception as exc:  # noqa: BLE001 - user-facing auth errors
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.video:
        parser.error("--video is required unless --auth, --check-auth or --revoke is used")
    if args.minimal_scope and (args.thumbnail or args.captions or args.playlist):
        parser.error("--minimal-scope cannot be combined with thumbnail, captions or playlist")
    try:
        data = _load_metadata(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    body = _body(data)
    if args.dry_run:
        video_path = Path(args.video).expanduser()
        if not video_path.exists() or video_path.stat().st_size == 0:
            print(f"error: video not found: {video_path}", file=sys.stderr)
            return 1
        for label, value in (("thumbnail", args.thumbnail), ("captions", args.captions)):
            if value and not Path(value).expanduser().exists():
                print(f"warning: {label} not found: {Path(value).expanduser()}", file=sys.stderr)
        print(json.dumps({"video": str(video_path), "body": body}, indent=2))
        return 0

    scopes = [SCOPE_UPLOAD if args.minimal_scope else SCOPE_FORCE_SSL]
    _, _, _, _, HttpError, MediaFileUpload = _google()
    try:
        youtube = _youtube(args, scopes, allow_login=True)
        if not args.minimal_scope:
            print(f"channel: {_channel(youtube).get('title')}")
        response = _upload(youtube, args, data, HttpError, MediaFileUpload)
        video_id = response["id"]
        print(f"uploaded: https://youtu.be/{video_id}")
        warnings = _add_extras(youtube, args, video_id, HttpError, MediaFileUpload)
        receipt = {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "privacyStatus": body["status"]["privacyStatus"],
            "publishAt": body["status"].get("publishAt"),
            "containsSyntheticMedia": body["status"]["containsSyntheticMedia"],
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "warnings": warnings,
        }
        receipt_path = _receipt_path(args, data)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"receipt: {receipt_path}")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing upload errors
        print(f"error: upload failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
