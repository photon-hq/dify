from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, normalize_message


class GetMessageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        result = normalize_message(client.call("get_message", path={"messageId": tool_parameters.get("message_id")}))
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
