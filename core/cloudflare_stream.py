"""Server-side client for the Cloudflare Stream API.

Video bytes never pass through Django. This module only:

* asks Cloudflare for a one-time tus upload URL (so the browser can PUT the
  file straight to Cloudflare),
* reads a video's processing status as a fallback for delayed webhooks,
* registers the webhook and reports webhook signature verification.

The API token is read from the environment and never leaves the server.
"""

import base64
import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger('core')

API_BASE = "https://api.cloudflare.com/client/v4"

# Cloudflare webhook signatures older than this are rejected outright, which
# bounds the window in which a captured request could be replayed.
WEBHOOK_SIGNATURE_TOLERANCE_SECONDS = 300


class CloudflareStreamError(Exception):
    """Cloudflare rejected the request, or answered with something unusable."""


def is_configured():
    """True when both the account id and an API token are available."""
    return bool(settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_STREAM_API_TOKEN)


def _require_configured():
    if not is_configured():
        raise CloudflareStreamError(
            "Video uploads are not configured on this server."
        )


def _headers():
    return {
        "Authorization": f"Bearer {settings.CLOUDFLARE_STREAM_API_TOKEN}",
        "Content-Type": "application/json",
    }


def build_upload_metadata(**kwargs):
    """Build a tus ``Upload-Metadata`` header value.

    Each entry is ``key <base64(value)>``, joined by commas, per the tus
    spec. ``None`` values are skipped so callers can pass optional fields
    without filtering them first.
    """
    parts = []
    for key, value in kwargs.items():
        if value is None:
            continue
        encoded = base64.b64encode(str(value).encode()).decode()
        parts.append(f"{key} {encoded}")
    return ",".join(parts)


def create_tus_upload_url(user_id, filesize, filename=None, max_duration_seconds=None):
    """Reserve a video on Cloudflare and return ``(upload_url, stream_uid)``.

    ``direct_user=true`` makes Cloudflare hand back a single-use URL that the
    browser can tus-upload to directly. The URL is only valid for the file we
    declared here, which is why the file size is fixed up front.
    """
    _require_configured()

    url = f"{API_BASE}/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/stream?direct_user=true"
    headers = {
        "Authorization": f"Bearer {settings.CLOUDFLARE_STREAM_API_TOKEN}",
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(int(filesize)),
        "Upload-Creator": str(user_id),
        "Upload-Metadata": build_upload_metadata(
            name=filename,
            maxdurationseconds=max_duration_seconds,
        ),
    }

    try:
        resp = requests.post(url, headers=headers, timeout=15)
    except requests.RequestException as exc:
        logger.warning("Cloudflare Stream create-upload request failed: %s", exc)
        raise CloudflareStreamError("Could not reach the video provider.")

    if resp.status_code not in (200, 201):
        logger.warning(
            "Cloudflare Stream create-upload rejected: %s %s",
            resp.status_code, resp.text[:500],
        )
        raise CloudflareStreamError("The video provider refused the upload.")

    upload_url = resp.headers.get("Location")
    stream_uid = resp.headers.get("stream-media-id")
    if not upload_url or not stream_uid:
        logger.warning(
            "Cloudflare Stream create-upload returned no Location/stream-media-id: %s",
            resp.text[:500],
        )
        raise CloudflareStreamError("Unexpected response from the video provider.")

    return upload_url, stream_uid


def get_video(uid):
    """Return the current state of a Cloudflare Stream video, or None.

    None means Cloudflare could not be reached or does not know the video yet
    — the caller should keep the existing status rather than overwrite it.
    """
    _require_configured()

    url = f"{API_BASE}/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/stream/{uid}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
    except requests.RequestException as exc:
        logger.warning("Cloudflare Stream get-video request failed: %s", exc)
        return None

    if resp.status_code != 200:
        return None
    try:
        return resp.json().get("result") or {}
    except ValueError:
        return None


def delete_video(uid):
    """Delete a video from Cloudflare. Returns True on success."""
    _require_configured()

    url = f"{API_BASE}/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/stream/{uid}"
    try:
        resp = requests.delete(url, headers=_headers(), timeout=15)
    except requests.RequestException as exc:
        logger.warning("Cloudflare Stream delete request failed: %s", exc)
        return False
    return resp.status_code in (200, 204)


def register_webhook(notification_url):
    """Register (or replace) the Stream webhook. Returns the response body.

    Cloudflare answers with a ``secret`` used to sign every callback. That
    secret belongs in ``CLOUDFLARE_STREAM_WEBHOOK_SECRET`` and nowhere else.
    """
    _require_configured()

    url = f"{API_BASE}/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/stream/webhook"
    try:
        resp = requests.put(
            url, headers=_headers(), json={"notificationUrl": notification_url}, timeout=15
        )
    except requests.RequestException as exc:
        raise CloudflareStreamError("Could not reach Cloudflare.") from exc

    if resp.status_code != 200:
        raise CloudflareStreamError(
            f"Cloudflare refused to register the webhook ({resp.status_code})."
        )
    return resp.json()


def verify_webhook_signature(header_value, body):
    """Verify Cloudflare's ``Webhook-Signature`` header against the body.

    Fails closed: with no secret configured nothing can be verified, so every
    request is rejected rather than trusted.
    """
    secret = settings.CLOUDFLARE_STREAM_WEBHOOK_SECRET
    if not secret or not header_value:
        return False

    try:
        parts = dict(
            part.split("=", 1) for part in header_value.split(",") if "=" in part
        )
        timestamp = int(parts["time"])
        signature = parts["sig1"]
    except (KeyError, TypeError, ValueError):
        return False

    if abs(time.time() - timestamp) > WEBHOOK_SIGNATURE_TOLERANCE_SECONDS:
        return False

    source = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), source, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def apply_stream_result(video, result):
    """Copy a Cloudflare ``result`` payload onto a local Video row.

    Returns True when the row was changed. Shared by the webhook handler and
    the status endpoint so both paths store identical data.
    """
    if not result:
        return False

    status = (result.get("status") or {})
    state = status.get("state")
    changed = False

    if state == "ready" and result.get("readyToStream"):
        if video.status != "ready":
            video.status = "ready"
            changed = True
        if result.get("error") is None and not video.error_message:
            video.error_message = ""
    elif state == "error":
        video.status = "error"
        video.error_message = status.get("errReasonText") or "Processing failed."
        changed = True
    elif state in ("uploading", "queued", "processing", "waitingForPackage"):
        if video.status == "pending":
            video.status = "processing"
            changed = True

    # duration
    if result.get("duration") and video.duration_seconds != result["duration"]:
        video.duration_seconds = result["duration"]
        changed = True

    # thumbnail — Cloudflare returns a timestamped path, not an absolute URL
    thumbnail = result.get("thumbnail")
    if thumbnail:
        if not thumbnail.startswith("http"):
            thumbnail = (
                f"https://{settings.CLOUDFLARE_STREAM_CUSTOMER_SUBDOMAIN}"
                f"/{video.cloudflare_uid}/thumbnails/{thumbnail.lstrip('/')}"
            )
        if video.thumbnail_url != thumbnail:
            video.thumbnail_url = thumbnail
            changed = True

    playback = result.get("playback") or {}
    for field, key in (
        ("playback_hls_url", "hls"),
        ("playback_dash_url", "dash"),
    ):
        url = playback.get(key)
        if url and getattr(video, field) != url:
            setattr(video, field, url)
            changed = True

    if result.get("meta", {}).get("name") and not video.title:
        video.title = result["meta"]["name"][:255]
        changed = True

    return changed
