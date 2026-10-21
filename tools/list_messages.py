from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import (
    DEFAULT_PAGE_SIZE,
    PhotonClient,
    query_params,
    tool_messages,
)


class ListMessagesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = {
            "pageSize": DEFAULT_PAGE_SIZE,
            **query_params(
                tool_parameters,
                {
                    "platform": "platform",
                    "space_id": "spaceId",
                    "perspective_user_id": "perspectiveUserId",
                    "direction": "direction",
                    "order": "order",
                    "created_since": "createdSince",
                    "created_before": "createdBefore",
                    "page_size": "pageSize",
                    "page_token": "pageToken",
                },
            ),
        }
        yield from tool_messages(self, client.call("list_messages", query=query))
