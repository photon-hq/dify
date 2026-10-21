"""Photon API access through Photon's official client, and the plugin's output shapes."""

import hashlib
import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from photon_api import ApiError, Photon, TransportError
from photon_api import PhotonError as ClientError
from photon_api.rpc_generated import (
    DownloadAttachmentInput,
    GetAttachmentInput,
    GetMessageInput,
    ListMessagesInput,
    ListSpacesInput,
    SendMessageInput,
    UploadAttachmentInput,
)
from pydantic import ValidationError

SEND_TYPES = ("text", "attachment")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
DEFAULT_PAGE_SIZE = 20
DIFY_RESERVED_NAMES = {"text", "files", "json"}
INPUTS = {
    "list_spaces": ListSpacesInput,
    "list_messages": ListMessagesInput,
    "get_message": GetMessageInput,
    "send_message": SendMessageInput,
    "upload_attachment": UploadAttachmentInput,
    "get_attachment": GetAttachmentInput,
    "download_attachment": DownloadAttachmentInput,
}


class PhotonError(ValueError):
    """An error to show the Dify user."""


def query_params(parameters: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """Photon query parameters for the tool parameters that are set."""
    return {
        api: parameters[name]
        for name, api in names.items()
        if parameters.get(name) not in (None, "")
    }


def issue_reason(issue: dict[str, Any]) -> str:
    """One validation issue, prefixed with the field it is about."""
    field = (issue.get("path") or "").lstrip("/")
    return f"{field}: {issue['message']}" if field else issue["message"]


def api_error_message(error: ApiError) -> str:
    """HTTP status, Photon's error code, and the problem's detail, issues, or title."""
    problem = error.body if isinstance(error.body, dict) else {}
    code = f" ({problem['code']})" if isinstance(problem.get("code"), str) else ""
    issues = [
        issue_reason(issue)
        for issue in problem.get("issues") or []
        if isinstance(issue, dict) and isinstance(issue.get("message"), str)
    ]
    reason = problem.get("detail") or "; ".join(dict.fromkeys(issues)) or problem.get("title")
    if isinstance(reason, str) and reason:
        return f"Photon API HTTP {error.status}{code}: {reason}"
    return f"Photon API HTTP {error.status}{code}."


def tool_messages(tool: Tool, result: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
    """The result as one JSON message, then each top-level field as a named variable.

    Fields with Dify's reserved names stay in the JSON message only.
    """
    yield tool.create_json_message(result)
    for name, value in result.items():
        if name not in DIFY_RESERVED_NAMES:
            yield tool.create_variable_message(name, value)


def normalize_message(data: dict[str, Any]) -> dict[str, Any]:
    content = data["content"]
    parts = content["parts"] if content["type"] == "group" else [content]
    texts = [part["text"] for part in parts if part["type"] == "text"]
    milestones = data["timestamps"]
    failure = data.get("failure")
    status = data["status"]
    return {
        "id": data["id"],
        "platform": data["platform"],
        "space_id": data["space"]["id"],
        "direction": "received" if status == "received" else "sent",
        "type": content["type"],
        "text": "\n".join(texts) if texts else None,
        "attachment_ids": [
            part["attachmentId"] for part in parts if part["type"] in ("attachment", "voice")
        ],
        "content": content,
        "parent_message_id": data.get("parentMessageId"),
        "status": status,
        "delivery_confirmed": status == "delivered",
        "timestamps": {
            "created_at": data["createdAt"],
            "updated_at": data["updatedAt"],
            **{
                public: milestones.get(api)
                for public, api in [
                    ("received_at", "receivedAt"),
                    ("dispatched_at", "dispatchedAt"),
                    ("accepted_at", "acceptedAt"),
                    ("delivered_at", "deliveredAt"),
                    ("failed_at", "failedAt"),
                ]
            },
        },
        "failure": {
            "code": failure["code"],
            "message": failure["message"],
            "confirmed_recipient_count": failure.get("confirmedRecipientCount"),
        }
        if failure
        else None,
    }


def normalize_space(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data["id"],
        "platform": data["platform"],
        "kind": data["kind"],
        "participant_ids": data["participantIds"],
        "created_at": data["createdAt"],
        "updated_at": data["updatedAt"],
    }


def normalize_attachment(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data["id"],
        "filename": data.get("filename"),
        "content_type": data["contentType"],
        "size_bytes": data["sizeBytes"],
        "created_at": data["createdAt"],
    }


class PhotonClient:
    def __init__(self, credentials: dict[str, Any]):
        self.origin = credentials["api_origin"]
        self.project_id = credentials["project_id"]
        self.default_sender_id = credentials.get("default_sender_id") or None
        self.api = Photon(
            base_url=self.origin, headers={"Authorization": f"Bearer {credentials['api_key']}"}
        )

    def call(
        self,
        operation: str,
        *,
        path: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        """Run one Photon operation on this project; return its JSON, or bytes for a download."""
        payload: dict[str, Any] = {"path": {"id": self.project_id, **(path or {})}}
        for name, value in (("query", query), ("headers", headers), ("body", body)):
            if value is not None:
                payload[name] = value
        try:
            result = getattr(self.api.projects, operation)(
                INPUTS[operation].model_validate(payload)
            )
        except ValidationError as error:
            fields = "; ".join(
                f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
                for issue in error.errors()
            )
            raise PhotonError(f"Invalid input for Photon: {fields}") from None
        except ApiError as error:
            raise PhotonError(api_error_message(error)) from None
        except TransportError:
            raise PhotonError(
                f"Cannot reach Photon at {self.origin}, or the request timed out. If sending, "
                "check the message history and reuse the same idempotency_key for any retry."
            ) from None
        except ClientError as error:
            raise PhotonError(
                f"{error}. If sending, check the message history before resending."
            ) from None
        return result if isinstance(result, bytes) else result.model_dump(mode="json")

    def upload_attachment(
        self, data: bytes, content_type: str, filename: str | None, idempotency: str
    ) -> dict[str, Any]:
        # The upload takes one multipart/related body: a JSON declaration, then the file.
        boundary = "photon-" + hashlib.sha256(idempotency.encode()).hexdigest()[:32]
        declaration = json.dumps(
            {
                "contentType": content_type,
                "sizeBytes": len(data),
                **({"filename": filename} if filename else {}),
            }
        )
        head = (
            f"--{boundary}\r\ncontent-type: application/json\r\n\r\n{declaration}\r\n"
            f"--{boundary}\r\ncontent-type: {content_type}\r\n\r\n"
        )
        body = head.encode() + data + f"\r\n--{boundary}--\r\n".encode()
        headers = {
            "content-type": f"multipart/related; boundary={boundary}",
            "content-length": str(len(body)),
            "idempotency-key": idempotency,
        }
        return normalize_attachment(self.call("upload_attachment", headers=headers, body=body))
