from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, tool_messages


class GetUserTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        path = {"userId": tool_parameters.get("user_id")}
        yield from tool_messages(self, client.call("get_user", path=path))
