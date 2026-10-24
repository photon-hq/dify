"""Photon's message.received deliveries, answered by the Dify chat app the endpoint selects."""

import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from typing import Any

from dify_plugin import Endpoint
from photon_api import Photon
from photon_api.rpc_generated import SendMessageInput
from werkzeug import Request, Response

ORIGIN = "https://api.photon.codes"
TOLERANCE_SECONDS = 300


def verify_signature(request: Request, secret: str, now: float) -> None:
    """Check a delivery's Standard Webhooks signature and timestamp, as Photon signs them."""
    key = base64.b64decode(secret.removeprefix("whsec_"))
    if not key:
        raise ValueError("The endpoint has no signing secret yet.")
    webhook_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signatures = request.headers.get("webhook-signature", "").split()
    if not webhook_id or not re.fullmatch(r"[0-9]+", timestamp) or not signatures:
        raise ValueError("Missing or malformed Photon webhook headers.")
    if abs(now - int(timestamp)) > TOLERANCE_SECONDS:
        raise ValueError("The Photon webhook timestamp is more than 5 minutes off.")
    signed = f"{webhook_id}.{timestamp}.".encode() + request.get_data()
    expected = b"v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
    if not any(hmac.compare_digest(signature.encode(), expected) for signature in signatures):
        raise ValueError("Invalid Photon webhook signature.")


def send_reply(settings: Mapping, project_id: str, message: dict[str, Any], text: str) -> None:
    """Send text into the message's space from the agent user that received it."""
    photon = Photon(
        base_url=ORIGIN,
        headers={"Authorization": f"Bearer {settings['api_key']}"},
    )
    photon.projects.send_message(
        SendMessageInput.model_validate(
            {
                "path": {"id": project_id},
                "headers": {"idempotency-key": f"{message['id']}.reply"},
                "body": {
                    "spaceId": message["space"]["id"],
                    "senderId": message["receivedBy"]["id"],
                    "content": {"type": "text", "format": "plain", "text": text},
                },
            }
        )
    )


class PhotonBotEndpoint(Endpoint):
    """Answer each received text message in its space, with one app conversation per space."""

    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        try:
            verify_signature(r, settings.get("signing_secret") or "", time.time())
        except ValueError as error:
            return Response(str(error), status=401)
        delivery = json.loads(r.get_data())
        if delivery["type"] != "message.received":
            return Response(status=200)
        message = delivery["data"]["object"]
        if (
            message["content"]["type"] != "text"
            or message["sentBy"]["kind"] == "agent"
            or "receivedBy" not in message
        ):
            return Response(status=200)
        app = settings["app"]
        key = f"{app['app_id']}:{message['space']['id']}"
        storage = self.session.storage
        state = json.loads(storage.get(key)) if storage.exist(key) else {}
        # Photon delivers a message again after a timeout or an error; answer it only once.
        if state.get("message_id") == message["id"]:
            return Response(status=200)
        state["message_id"] = message["id"]
        storage.set(key, json.dumps(state).encode())
        result = self.session.app.chat.invoke(
            app_id=app["app_id"],
            query=message["content"]["text"],
            inputs=app.get("inputs", {}),
            response_mode="blocking",
            conversation_id=state.get("conversation_id"),
        )
        if result["conversation_id"] != state.get("conversation_id"):
            # Photon may deliver the space's next message while a slow call runs, so the record is
            # read again instead of writing back this message's copy.
            current = json.loads(storage.get(key))
            current["conversation_id"] = result["conversation_id"]
            storage.set(key, json.dumps(current).encode())
        if result["answer"]:
            send_reply(settings, delivery["data"]["projectId"], message, result["answer"])
        return Response(status=200)
