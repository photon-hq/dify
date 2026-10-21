from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, normalize_message, query_params


class ListMessagesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = {"pageSize": 20, "order": "desc", **query_params(tool_parameters, {
            "platform": "platform", "direction": "direction", "order": "order", "created_since": "createdSince",
            "created_before": "createdBefore", "page_size": "pageSize", "page_token": "pageToken",
        })}
        space = tool_parameters.get("space_id") or None
        # API spaceId needs resourceId or perspectiveUserId; perspectives forbid
        # platform/time filters. Filter this bounded project page locally instead.
        data = client.call("list_messages", query=query)
        scanned = data["items"]
        items = [normalize_message(item) for item in scanned]
        if space is not None:
            items = [item for item in items if item["space_id"] == space]
        result = {
            "items": items,
            "next_page_token": data.get("nextPageToken"),
            "scanned_count": len(scanned),
            "space_filter_applied_locally": space is not None,
        }
        yield self.create_json_message(result)
        for key, value in result.items():
            if key not in {"text", "files", "json"}:
                yield self.create_variable_message(key, value)
