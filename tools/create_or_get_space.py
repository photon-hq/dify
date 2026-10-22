from collections.abc import Generator
from typing import Any
from uuid import uuid4

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.client import PhotonClient, PhotonError, UnknownOutcome, tool_messages


class CreateOrGetSpaceTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        client = PhotonClient(self.runtime.credentials)
        participants = [
            user_id.strip()
            for user_id in (tool_parameters.get("participant_ids") or "").split(",")
            if user_id.strip()
        ]
        key = tool_parameters.get("idempotency_key") or None
        generated = key is None
        if generated:
            key = str(uuid4())
        body = {"platform": tool_parameters.get("platform"), "participantIds": participants}
        try:
            result = client.call("create_or_get_space", headers={"idempotency-key": key}, body=body)
        except PhotonError as error:
            reason = str(error)
            if isinstance(error, UnknownOutcome):
                reason += " Reuse the same idempotency_key for any retry."
            if generated:
                reason += f" Generated idempotency_key: {key}"
            raise PhotonError(reason) from None
        result["idempotency_key"] = key
        yield from tool_messages(self, result)
