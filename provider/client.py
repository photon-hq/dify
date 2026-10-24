"""Photon API access through Photon's official client."""

import hashlib
import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from photon_api import ApiError, Photon, TransportError
from photon_api import PhotonError as ClientError
from photon_api.rpc_generated import (
    CreateOrGetSpaceInput,
    CreateOrGetUserInput,
    DownloadAttachmentInput,
    GetAttachmentInput,
    GetMessageInput,
    GetUserInput,
    ListMessagesInput,
    ListSpacesInput,
    SendMessageInput,
    UploadAttachmentInput,
)
from pydantic import ValidationError

ORIGIN = "https://api.photon.codes"
SEND_TYPES = ("text", "attachment")
TEXT_FORMATS = ("plain", "markdown")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
DEFAULT_PAGE_SIZE = 20
INPUTS = {
    "list_spaces": ListSpacesInput,
    "create_or_get_space": CreateOrGetSpaceInput,
    "list_messages": ListMessagesInput,
    "get_message": GetMessageInput,
    "get_user": GetUserInput,
    "create_or_get_user": CreateOrGetUserInput,
    "send_message": SendMessageInput,
    "upload_attachment": UploadAttachmentInput,
    "get_attachment": GetAttachmentInput,
    "download_attachment": DownloadAttachmentInput,
}


class PhotonError(ValueError):
    """An error to show the Dify user."""


class UnknownOutcome(PhotonError):
    """Photon may have handled the request, but no readable response came back."""


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
    """Photon's result as one JSON message, then each top-level field as a named variable."""
    yield tool.create_json_message(result)
    for name, value in result.items():
        yield tool.create_variable_message(name, value)


class PhotonClient:
    def __init__(self, credentials: dict[str, Any]):
        self.project_id = credentials["project_id"]
        self.api = Photon(
            base_url=ORIGIN, headers={"Authorization": f"Bearer {credentials['api_key']}"}
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
            raise UnknownOutcome(
                f"Cannot reach Photon at {ORIGIN}, or the request timed out."
            ) from None
        except ClientError as error:
            raise UnknownOutcome(f"{error}.") from None
        if isinstance(result, bytes):
            return result
        # Photon's field names, such as an email address's from, not the client's Python names.
        return result.model_dump(mode="json", by_alias=True)

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
        return self.call("upload_attachment", headers=headers, body=body)
