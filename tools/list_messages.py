from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, PhotonError, normalize_message, page_items, pagination, photon_id, platform_filter, sort_order, time_bounds


class ListMessagesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = pagination(tool_parameters, 200)
        query.update(platform_filter(tool_parameters.get("platform")))
        query.update(time_bounds(tool_parameters))
        query["order"] = sort_order(tool_parameters.get("order"))
        space = photon_id(tool_parameters.get("space_id"), "space_id", "pho_spc_", required=False)
        direction = tool_parameters.get("direction")
        if direction is not None and direction != "":
            if direction not in ("received", "sent"):
                raise PhotonError("direction must be received or sent.")
            query["direction"] = direction
        # API spaceId needs resourceId or perspectiveUserId; perspectives forbid
        # platform/time filters. Filter this bounded project page locally instead.
        data = client.request("GET", "/messages", params=query)
        scanned = page_items(data)
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
