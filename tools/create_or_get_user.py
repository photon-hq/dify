from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, tool_messages


class CreateOrGetUserTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        body = {
            "platform": tool_parameters.get("platform"),
            "handle": tool_parameters.get("handle"),
        }
        yield from tool_messages(self, client.call("create_or_get_user", body=body))
