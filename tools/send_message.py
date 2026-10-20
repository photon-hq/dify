import hashlib
import re
from collections.abc import Generator
from typing import Any
from uuid import uuid4

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import IMAGE_TYPES, MAX_EMAIL_SUBJECT_LENGTH, MAX_IMAGE_BYTES, MAX_TEXT_LENGTH, SEND_TYPES, PhotonClient, PhotonError, normalize_message, optional_string, photon_id


class SendMessageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        space = photon_id(tool_parameters.get("space_id"), "space_id", "pho_spc_")
        sender = tool_parameters.get("sender_id")
        if sender is None or sender == "":
            sender = client.default_sender_id
        if not sender:
            raise PhotonError("Provide sender_id or configure default_sender_id with a project-owned Photon agent user ID.")
        sender = photon_id(sender, "sender_id", "pho_usr_")
        parent = photon_id(tool_parameters.get("parent_message_id"), "parent_message_id", "pho_msg_", required=False)
        kind = tool_parameters.get("type")
        if kind is None or kind == "":
            kind = "text"
        if kind not in SEND_TYPES:
            raise PhotonError(f"type must be one of {', '.join(SEND_TYPES)}.")
        text = tool_parameters.get("text")
        if text is None or text == "":
            text = None
        elif not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
            raise PhotonError(f"text must contain 1-{MAX_TEXT_LENGTH} characters and cannot be blank; split longer messages explicitly.")
        files = tool_parameters.get("attachments") or []
        if not isinstance(files, list):
            files = [files]
        if kind == "text" and text is None:
            raise PhotonError("type text requires text.")
        if kind == "text" and files:
            raise PhotonError("type text does not take attachments; use type attachment to send images.")
        if kind == "attachment" and not files:
            raise PhotonError("type attachment requires at least one image in attachments.")
        if any(getattr(file, "mime_type", None) not in IMAGE_TYPES for file in files):
            raise PhotonError("attachments must be JPEG, PNG, GIF, or WebP images; other file types are not supported yet.")
        subject = optional_string(tool_parameters.get("email_subject"), "email_subject", MAX_EMAIL_SUBJECT_LENGTH)
        key = tool_parameters.get("idempotency_key")
        generated = key is None or key == ""
        if generated:
            key = str(uuid4())
        if not isinstance(key, str) or not re.fullmatch(r"[\x21-\x7e]{1,255}", key):
            raise PhotonError("idempotency_key must be 1-255 visible ASCII characters without spaces; use a UUID or stable operation ID.")
        images = [(file, file.blob) for file in files]
        if any(len(data) > MAX_IMAGE_BYTES for _, data in images):
            raise PhotonError("Each image in attachments must be at most 10 MB.")
        try:
            parts = []
            for index, (file, data) in enumerate(images):
                upload_key = f"{hashlib.sha256(key.encode()).hexdigest()}.attachment.{index}"
                attachment = client.upload_attachment(data, file.mime_type, file.filename, upload_key)
                parts.append({"type": "attachment", "attachmentId": attachment["id"]})
            if text is not None:
                parts.append({"type": "text", "format": "plain", "text": text})
            body = {"spaceId": space, "senderId": sender, "content": parts[0] if len(parts) == 1 else {"type": "group", "parts": parts}}
            if parent is not None:
                body["parentMessageId"] = parent
            if subject is not None:
                body["email"] = {"subject": subject}
            result = normalize_message(client.request("POST", "/messages", body=body, idempotency=key))
        except PhotonError as error:
            if generated:
                raise PhotonError(f"{error} Generated idempotency_key: {key}") from None
            raise
        result["idempotency_key"] = key
        result = client.sanitize(result)
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
