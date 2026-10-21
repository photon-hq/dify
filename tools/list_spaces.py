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


class ListSpacesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        query = {
            "pageSize": DEFAULT_PAGE_SIZE,
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
        yield from tool_messages(self, client.call("list_spaces", query=query))
