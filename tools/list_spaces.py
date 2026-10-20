from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, normalize_space, optional_string, page_items, pagination, platform_filter, sort_order


class ListSpacesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = pagination(tool_parameters, 100)
        query.update(platform_filter(tool_parameters.get("platform")))
        query["order"] = sort_order(tool_parameters.get("order"))
        handle = optional_string(tool_parameters.get("participant_handle"), "participant_handle", 320)
        if handle is not None:
            query["participantHandle"] = handle
        data = client.request("GET", "/spaces", params=query)
        result = {"items": [normalize_space(item) for item in page_items(data)], "next_page_token": data.get("nextPageToken")}
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
