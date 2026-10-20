from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, normalize_attachment, photon_id


class GetAttachmentTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        attachment = photon_id(tool_parameters.get("attachment_id"), "attachment_id", "pho_att_")
        result = normalize_attachment(client.request("GET", f"/attachments/{attachment}"))
        data = client.request("GET", f"/attachments/{attachment}/content", binary=True)
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
        yield self.create_blob_message(data, meta={"mime_type": result["content_type"], "filename": result["filename"]})
