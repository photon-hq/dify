from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import (
    DEFAULT_PAGE_SIZE,
    PhotonClient,
    normalize_space,
    query_params,
    tool_messages,
)


class ListSpacesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = {
            "pageSize": DEFAULT_PAGE_SIZE,
            "order": "desc",
            **query_params(
                tool_parameters,
                {
                    "platform": "platform",
                    "participant_handle": "participantHandle",
                    "order": "order",
                    "page_size": "pageSize",
                    "page_token": "pageToken",
                },
            ),
        }
        data = client.call("list_spaces", query=query)
        result = {
            "items": [normalize_space(item) for item in data["items"]],
            "next_page_token": data.get("nextPageToken"),
        }
        yield from tool_messages(self, result)
