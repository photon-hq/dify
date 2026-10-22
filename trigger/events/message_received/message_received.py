import re
from collections.abc import Mapping
from typing import Any

from dify_plugin.entities.trigger import Variables
from dify_plugin.errors.trigger import EventIgnoreError
from dify_plugin.interfaces.trigger import Event
from werkzeug import Request


class MessageReceivedEvent(Event):
    """Photon's received message, as the delivery carries it, becomes the workflow's variables."""

    def _on_event(
        self, request: Request, parameters: Mapping[str, Any], payload: Mapping[str, Any]
    ) -> Variables:
        message = payload["data"]["object"]
        platforms = parameters.get("platforms") or []
        if platforms and message.get("platform") not in platforms:
            raise EventIgnoreError(f"Platform {message.get('platform')} is not selected.")
        text = (message.get("content") or {}).get("text") or ""
        contains = parameters.get("text_contains")
        if contains and contains.lower() not in text.lower():
            raise EventIgnoreError(f"Text does not contain: {contains}")
        pattern = parameters.get("text_regex")
        if pattern:
            try:
                matched = re.search(pattern, text)
            except re.error as error:
                raise EventIgnoreError(f"Invalid text regex: {error}") from None
            if not matched:
                raise EventIgnoreError(f"Text does not match regex: {pattern}")
        return Variables(variables=message)
