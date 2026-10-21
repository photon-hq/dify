from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, normalize_space, query_params


class ListSpacesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = {"pageSize": 20, "order": "desc", **query_params(tool_parameters, {
            "platform": "platform", "participant_handle": "participantHandle", "order": "order",
            "page_size": "pageSize", "page_token": "pageToken",
        })}
        data = client.call("list_spaces", query=query)
        result = {"items": [normalize_space(item) for item in data["items"]], "next_page_token": data.get("nextPageToken")}
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
