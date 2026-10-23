import hashlib
from collections.abc import Generator
from typing import Any
from uuid import uuid4

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import (
    IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    SEND_TYPES,
    TEXT_FORMATS,
    PhotonClient,
    PhotonError,
    UnknownOutcome,
    tool_messages,
)


class SendMessageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        kind = tool_parameters.get("type") or "text"
        if kind not in SEND_TYPES:
            raise PhotonError(f"type must be one of {', '.join(SEND_TYPES)}.")
        text = tool_parameters.get("text") or None
        text_format = tool_parameters.get("format") or "plain"
        if text_format not in TEXT_FORMATS:
            raise PhotonError(f"format must be one of {', '.join(TEXT_FORMATS)}.")
        files = tool_parameters.get("attachments") or []
        if not isinstance(files, list):
            files = [files]
        if kind == "text" and text is None:
            raise PhotonError("type text requires text.")
        if kind == "text" and files:
            raise PhotonError(
                "type text does not take attachments; use type attachment to send images."
            )
        if kind == "attachment" and not files:
            raise PhotonError("type attachment requires at least one image in attachments.")
        if any(getattr(file, "mime_type", None) not in IMAGE_TYPES for file in files):
            raise PhotonError(
                "attachments must be JPEG, PNG, GIF, or WebP images; "
                "other file types are not supported yet."
            )
        key = tool_parameters.get("idempotency_key") or None
        generated = key is None
        if generated:
            key = str(uuid4())
        images = [(file, file.blob) for file in files]
        if any(len(data) > MAX_IMAGE_BYTES for _, data in images):
            raise PhotonError("Each image in attachments must be at most 10 MB.")
        body: dict[str, Any] = {
            "spaceId": tool_parameters.get("space_id"),
            "senderId": tool_parameters.get("sender_id"),
        }
        if tool_parameters.get("parent_message_id"):
            body["parentMessageId"] = tool_parameters["parent_message_id"]
        if tool_parameters.get("email_subject"):
            body["email"] = {"subject": tool_parameters["email_subject"]}
        try:
            parts = [] if text is None else [{"type": "text", "format": text_format, "text": text}]
            for index, (file, data) in enumerate(images):
                upload_key = f"{hashlib.sha256(key.encode()).hexdigest()}.attachment.{index}"
                attachment = client.upload_attachment(
                    data, file.mime_type, file.filename, upload_key
                )
                parts.append({"type": "attachment", "attachmentId": attachment["id"]})
            body["content"] = parts[0] if len(parts) == 1 else {"type": "group", "parts": parts}
            result = client.call("send_message", headers={"idempotency-key": key}, body=body)
        except PhotonError as error:
            reason = str(error)
            if isinstance(error, UnknownOutcome):
                reason += (
                    " Check the message history before resending, "
                    "and reuse the same idempotency_key for any retry."
                )
            if generated:
                reason += f" Generated idempotency_key: {key}"
            raise PhotonError(reason) from None
        result["idempotency_key"] = key
        yield from tool_messages(self, result)
