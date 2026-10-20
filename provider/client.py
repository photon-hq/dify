"""Allowlisted Photon API access, input validation, and stable output shapes."""

import hashlib
import json
import re
from datetime import datetime
from typing import Any

import requests

TIMEOUT = (5, 15)
ALLOWED_ORIGINS = ("https://api.photon.codes", "https://api.staging.photon.codes")
MAX_TEXT_LENGTH = 10_000  # Plugin safety cap; Photon specifies only minLength: 1.
MAX_EMAIL_SUBJECT_LENGTH = 4096
PLATFORMS = ("imessage", "sms", "whatsapp", "whatsapp_business", "email", "telegram")
SEND_TYPES = ("text", "attachment")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
STATUSES = {"received", "dispatched", "accepted", "delivered", "failed"}
ID_SUFFIX = r"[0-7][0-9a-hjkmnp-tv-z]{25}"
ROUTES = (
    ("GET", "/spaces"),
    ("GET", "/messages"),
    ("POST", "/messages"),
    ("GET", "/messages/pho_msg_" + ID_SUFFIX),
    ("POST", "/attachments"),
    ("GET", "/attachments/pho_att_" + ID_SUFFIX),
    ("GET", "/attachments/pho_att_" + ID_SUFFIX + "/content"),
)


class PhotonError(ValueError):
    """An actionable error that never embeds raw HTTP or credential data."""


def optional_string(value: Any, name: str, limit: int) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > limit or not value.strip():
        raise PhotonError(f"{name} must be a non-blank string of at most {limit} characters.")
    return value


def photon_id(value: Any, name: str, prefix: str, *, required: bool = True) -> str | None:
    if not required and (value is None or value == ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + ID_SUFFIX, value):
        raise PhotonError(f"{name} must be a Photon ID starting with {prefix} followed by its 26-character lowercase ID.")
    return value


def page_size(value: Any, maximum: int) -> int:
    if value is None or value == "":
        return 20
    message = f"page_size must be a positive integer; the maximum used is {maximum}."
    try:
        size = int(value)
    except (ValueError, TypeError, OverflowError):
        raise PhotonError(message) from None
    if isinstance(value, bool) or size < 1 or (isinstance(value, float) and value != size):
        raise PhotonError(message)
    return min(size, maximum)


def platform_filter(value: Any) -> dict[str, str]:
    if value is None or value == "":
        return {}
    if value not in PLATFORMS:
        raise PhotonError(f"platform must be one of {', '.join(PLATFORMS)}, or omitted for all platforms.")
    return {"platform": value}


def sort_order(value: Any) -> str:
    if value is None or value == "":
        return "desc"
    if value not in ("asc", "desc"):
        raise PhotonError("order must be asc or desc.")
    return value


def pagination(parameters: dict[str, Any], maximum: int) -> dict[str, Any]:
    query: dict[str, Any] = {"pageSize": page_size(parameters.get("page_size"), maximum)}
    cursor = optional_string(parameters.get("page_token"), "page_token", 4096)
    if cursor is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", cursor):
            raise PhotonError("page_token must be the unchanged next_page_token from the previous response.")
        query["pageToken"] = cursor
    return query


def time_bounds(parameters: dict[str, Any]) -> dict[str, str]:
    query = {}
    parsed = {}
    for name, api_name in [("created_since", "createdSince"), ("created_before", "createdBefore")]:
        value = optional_string(parameters.get(name), name, 64)
        if value is None:
            continue
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
                raise ValueError
            parsed[name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise PhotonError(f"{name} must be RFC 3339 with a timezone, for example 2026-10-19T00:00:00Z.") from None
        query[api_name] = value
    if len(parsed) == 2 and parsed["created_since"] >= parsed["created_before"]:
        raise PhotonError("created_since must be earlier than created_before.")
    return query


def page_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise PhotonError("Photon returned an invalid page; expected an items array.")
    return items


def snake_case(value: Any) -> Any:
    if isinstance(value, list):
        return [snake_case(item) for item in value]
    if isinstance(value, dict):
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): snake_case(item) for key, item in value.items()}
    return value


def normalize_message(data: dict[str, Any]) -> dict[str, Any]:
    space = data.get("space")
    content = data.get("content")
    milestones = data.get("timestamps")
    status = data.get("status")
    if not data.get("id") or not isinstance(data.get("platform"), str) or not isinstance(status, str) or status not in STATUSES or not isinstance(space, dict) or not space.get("id") or not isinstance(content, dict) or not isinstance(content.get("type"), str) or not isinstance(milestones, dict):
        raise PhotonError("Photon returned an incomplete message; check its status in Photon before resending.")
    parts = [part for part in (content.get("parts") or [] if content["type"] == "group" else [content]) if isinstance(part, dict)]
    texts = [part["text"] for part in parts if part.get("type") == "text" and isinstance(part.get("text"), str)]
    failure = data.get("failure")
    return {
        "id": data["id"],
        "platform": data["platform"],
        "space_id": space["id"],
        "direction": "received" if status == "received" else "sent",
        "type": content["type"],
        "text": "\n".join(texts) if texts else None,
        "attachment_ids": [part["attachmentId"] for part in parts if part.get("type") in ("attachment", "voice") and isinstance(part.get("attachmentId"), str)],
        "content": snake_case(content),
        "parent_message_id": data.get("parentMessageId"),
        "status": status,
        "delivery_confirmed": status == "delivered",
        "timestamps": {
            "created_at": data.get("createdAt"),
            "updated_at": data.get("updatedAt"),
            **{public: milestones.get(api) for public, api in [
                ("received_at", "receivedAt"), ("dispatched_at", "dispatchedAt"),
                ("accepted_at", "acceptedAt"), ("delivered_at", "deliveredAt"), ("failed_at", "failedAt"),
            ]},
        },
        "failure": {
            "code": failure.get("code"),
            "message": failure.get("message"),
            "confirmed_recipient_count": failure.get("confirmedRecipientCount"),
        } if isinstance(failure, dict) else None,
    }


def normalize_space(data: dict[str, Any]) -> dict[str, Any]:
    if not data.get("id") or not isinstance(data.get("participantIds"), list):
        raise PhotonError("Photon returned an incomplete space.")
    return {
        "id": data["id"],
        "platform": data.get("platform"),
        "kind": data.get("kind"),
        "participant_ids": data["participantIds"],
        "created_at": data.get("createdAt"),
        "updated_at": data.get("updatedAt"),
    }


def normalize_attachment(data: dict[str, Any]) -> dict[str, Any]:
    if not data.get("id") or not isinstance(data.get("contentType"), str):
        raise PhotonError("Photon returned an incomplete attachment.")
    return {
        "id": data["id"],
        "filename": data.get("filename"),
        "content_type": data["contentType"],
        "size_bytes": data.get("sizeBytes"),
        "created_at": data.get("createdAt"),
    }


class PhotonClient:
    def __init__(self, credentials: dict[str, Any]):
        origin = credentials.get("api_origin", ALLOWED_ORIGINS[0])
        if not isinstance(origin, str) or origin not in ALLOWED_ORIGINS:
            raise PhotonError("api_origin must be exactly https://api.photon.codes (production) or https://api.staging.photon.codes (staging), without a trailing slash or path.")
        self.origin = origin
        value = credentials.get("api_key")
        if not isinstance(value, str) or not re.fullmatch(r"pho_(?:ask|sk)_[\x21-\x7e]+", value):
            raise PhotonError("Configure api_key with a Photon Account Service Key or Project API key (pho_ask_ or pho_sk_); omit the Bearer prefix.")
        self._key = value
        self.project_id = photon_id(credentials.get("project_id"), "project_id", "pho_prj_")
        self.default_sender_id = photon_id(credentials.get("default_sender_id"), "default_sender_id", "pho_usr_", required=False)

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            return re.sub(r"pho_(?:ask|sk)_[A-Za-z0-9_-]+", "[REDACTED]", value.replace(self._key, "[REDACTED]"))
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        if isinstance(value, dict):
            return {self.sanitize(key): self.sanitize(item) for key, item in value.items()}
        return value

    def upload_attachment(self, data: bytes, content_type: str, filename: str | None, idempotency: str) -> dict[str, Any]:
        boundary = "photon-" + hashlib.sha256(idempotency.encode()).hexdigest()[:32]
        declaration = json.dumps({"contentType": content_type, "sizeBytes": len(data), **({"filename": filename} if filename else {})})
        body = f"--{boundary}\r\ncontent-type: application/json\r\n\r\n{declaration}\r\n--{boundary}\r\ncontent-type: {content_type}\r\n\r\n".encode() + data + f"\r\n--{boundary}--\r\n".encode()
        return normalize_attachment(self.request("POST", "/attachments", content=(body, f"multipart/related; boundary={boundary}"), idempotency=idempotency))

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None, content: tuple[bytes, str] | None = None, idempotency: str | None = None, binary: bool = False) -> Any:
        if not any(method == allowed and re.fullmatch(pattern, path) for allowed, pattern in ROUTES):
            raise PhotonError("Unsupported Photon operation.")
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "*/*" if binary else "application/json, application/problem+json"}
        if idempotency is not None:
            headers["Idempotency-Key"] = idempotency
        data = None
        if content is not None:
            data, headers["Content-Type"] = content
        try:
            with requests.Session() as session:
                # Ignore ambient proxies and .netrc; use only the selected allowlisted origin.
                session.trust_env = False
                with session.request(
                    method,
                    f"{self.origin}/v1/projects/{self.project_id}{path}",
                    headers=headers, params=params, json=body, data=data,
                    timeout=TIMEOUT, verify=True, allow_redirects=False, stream=binary,
                ) as response:
                    expected = {("POST", "/messages"): (202,), ("POST", "/attachments"): (200, 201)}.get((method, path), (200,))
                    if response.status_code not in expected:
                        self._raise_api_error(response)
                    if binary:
                        data = bytearray()
                        for chunk in response.iter_content(65536):
                            data += chunk
                            if len(data) > MAX_ATTACHMENT_BYTES:
                                raise PhotonError("The attachment is larger than 50 MB, Dify's default limit for files returned by plugins.")
                        return bytes(data)
                    try:
                        result = response.json()
                    except ValueError:
                        raise PhotonError("Photon returned invalid JSON. If sending, check history before resending.") from None
                    if not isinstance(result, dict):
                        raise PhotonError("Photon returned an invalid response. If sending, check history before resending.")
                    return self.sanitize(result)
        except requests.Timeout:
            raise PhotonError("Photon request timed out (5s connect / 15s read). If sending, the outcome is unknown; check history and reuse the same idempotency_key for any retry.") from None
        except requests.RequestException:
            raise PhotonError(f"Cannot reach Photon over verified HTTPS. Check outbound access to {self.origin} on port 443. If sending, check history before retrying with the same idempotency_key.") from None

    @staticmethod
    def _raise_api_error(response: requests.Response) -> None:
        # Parse problem+json but never echo arbitrary title/detail/headers/body.
        code = None
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == "application/problem+json":
            try:
                problem = response.json()
                code = problem.get("code") if isinstance(problem, dict) else None
            except ValueError:
                pass
        hints = {
            400: "Check parameters and keep pagination filters unchanged.",
            401: "Check the API key and selected Photon environment in the provider credentials.",
            402: "Photon billing for this project is suspended; resolve it in Photon before sending.",
            403: "Check key permissions, project ownership, and sender access.",
            404: "Check the project, space, sender, message, or attachment ID and its project ownership.",
            409: "Photon cannot send in this space right now; check the space, sender, and channel setup in Photon.",
            413: "The request is too large; shorten the text or send a smaller file.",
            422: "Check IDs, sender, type, text, attachments, email_subject, and filters against the tool instructions.",
            429: "Rate limited; wait before an explicit retry using the same send idempotency key.",
        }
        code_hints = {
            "IDEMPOTENCY_KEY_REUSED": "This idempotency_key was already used with a different send body; reuse a key only for an identical retry.",
            "MESSAGE_TOO_LONG": "The text is longer than this channel accepts; split it into shorter messages.",
            "SENDER_NOT_FOUND": "Use a project-owned agent user ID (pho_usr_) on the same channel as the space.",
            "SENDER_NOT_SENDABLE": "This sender cannot send right now; use a project-owned agent on the same channel as the space.",
            "SPACE_NOT_SENDABLE": "Photon cannot send this message in this space; check the channel setup in Photon, and omit parent_message_id where the space does not support replies.",
            "SMS_CAMPAIGN_NOT_ELIGIBLE": "SMS needs campaign eligibility unless every recipient is in-network; check the sending line's campaign in Photon.",
            "SHARED_LINE_NOT_ASSIGNED": "The recipient has no active assignment on this shared line.",
            "SHARED_LINE_INBOUND_REQUIRED": "A shared iMessage line can reply only after the recipient has messaged it since the assignment.",
            "SHARED_LINE_GROUP_UNSUPPORTED": "Shared iMessage lines send only in direct spaces, not groups.",
            "UNSUPPORTED_CONTENT": "This space cannot accept this content; some channels take text and attachments only as separate messages, and some take no attachments.",
            "PAYLOAD_TOO_LARGE": "The file is larger than Photon accepts; send a smaller file.",
            "INVALID_ATTACHMENT_REQUEST": "Photon rejected the attachment request; check the attachment ID, or the image type and size when sending.",
            "ATTACHMENT_CONFLICT": "This idempotency_key was already used to upload a different file; use a new key.",
            "ATTACHMENT_UPLOAD_NOT_READY": "The upload is still being committed; retry with the same idempotency_key.",
            "ATTACHMENT_NOT_READY": "The attachment is still processing; retry shortly.",
            "ATTACHMENT_NOT_FOUND": "Check the attachment ID (pho_att_) and its project ownership.",
        }
        known_codes = {"NOT_AUTHENTICATED", "FORBIDDEN", "INSUFFICIENT_SCOPE", "RESOURCE_MISMATCH", "BILLING_SUSPENDED", "PROJECT_NOT_FOUND", "SPACE_NOT_FOUND", "MESSAGE_NOT_FOUND", "INVALID_PAGE_TOKEN", "VALIDATION_FAILED", "INVALID_CONTENT", "RATE_LIMITED", *code_hints}
        label = f" ({code})" if isinstance(code, str) and code in known_codes else ""
        hint = code_hints.get(code) if label else None
        hint = hint or hints.get(response.status_code, "Check Photon availability. If sending, check history before retrying with the same idempotency key.")
        raise PhotonError(f"Photon API HTTP {response.status_code}{label}. {hint}")
