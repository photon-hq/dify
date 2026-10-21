from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import (
    MAX_ATTACHMENT_BYTES,
    PhotonClient,
    PhotonError,
    normalize_attachment,
    tool_messages,
)


class GetAttachmentTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        path = {"attachmentId": tool_parameters.get("attachment_id")}
        result = normalize_attachment(client.call("get_attachment", path=path))
        if result["size_bytes"] > MAX_ATTACHMENT_BYTES:
            raise PhotonError(
                "The attachment is larger than 50 MB, "
                "Dify's default limit for files returned by plugins."
            )
        data = client.call("download_attachment", path=path)
        yield from tool_messages(self, result)
        yield self.create_blob_message(
            data, meta={"mime_type": result["content_type"], "filename": result["filename"]}
        )
