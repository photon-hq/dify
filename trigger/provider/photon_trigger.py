"""Photon's webhook deliveries, and the Photon webhook destination behind each subscription."""

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any

from dify_plugin.entities.provider_config import CredentialType
from dify_plugin.entities.trigger import EventDispatch, Subscription, UnsubscribeResult
from dify_plugin.errors.trigger import (
    SubscriptionError,
    TriggerDispatchError,
    TriggerProviderCredentialValidationError,
    TriggerValidationError,
    UnsubscribeError,
)
from dify_plugin.interfaces.trigger import Trigger, TriggerSubscriptionConstructor
from photon_api import ApiError, Photon, TransportError
from photon_api import PhotonError as ClientError
from photon_api.rpc_generated import (
    CreateWebhookDestinationInput,
    DeleteWebhookDestinationInput,
    ListWebhookDestinationsInput,
)
from werkzeug import Request, Response

API_VERSION = "2026-07-01"
# Dify does not hold trigger credentials to the select's options, so the plugin does.
ORIGINS = ("https://api.photon.codes", "https://api.staging.photon.codes")
EVENTS = {"message.received": "message_received"}
TOLERANCE_SECONDS = 300
INPUTS = {
    "list_webhook_destinations": ListWebhookDestinationsInput,
    "create_webhook_destination": CreateWebhookDestinationInput,
    "delete_webhook_destination": DeleteWebhookDestinationInput,
}


class PhotonError(ValueError):
    """An error to show the Dify user."""


def issue_reason(issue: dict[str, Any]) -> str:
    """One validation issue, prefixed with the field it is about."""
    field = (issue.get("path") or "").lstrip("/")
    return f"{field}: {issue['message']}" if field else issue["message"]


def api_error_message(error: ApiError) -> str:
    """HTTP status, Photon's error code, and the problem's detail, issues, or title."""
    problem = error.body if isinstance(error.body, dict) else {}
    code = f" ({problem['code']})" if isinstance(problem.get("code"), str) else ""
    issues = [
        issue_reason(issue)
        for issue in problem.get("issues") or []
        if isinstance(issue, dict) and isinstance(issue.get("message"), str)
    ]
    reason = problem.get("detail") or "; ".join(dict.fromkeys(issues)) or problem.get("title")
    if isinstance(reason, str) and reason:
        return f"Photon API HTTP {error.status}{code}: {reason}"
    return f"Photon API HTTP {error.status}{code}."


def call(credentials: Mapping[str, Any], operation: str, **parts: Any) -> dict[str, Any]:
    """Run one Photon operation on the credentials' project and return its JSON."""
    origin = credentials["api_origin"]
    if origin not in ORIGINS:
        raise PhotonError(f"api_origin must be {' or '.join(ORIGINS)}.")
    api = Photon(base_url=origin, headers={"Authorization": f"Bearer {credentials['api_key']}"})
    path = {"projectId": credentials["project_id"], **parts.pop("path", {})}
    try:
        result = getattr(api.projects, operation)(
            INPUTS[operation].model_validate({"path": path, **parts})
        )
    except ApiError as error:
        raise PhotonError(api_error_message(error)) from None
    except TransportError:
        raise PhotonError(f"Cannot reach Photon at {origin}, or the request timed out.") from None
    except ClientError as error:
        raise PhotonError(f"{error}.") from None
    return result.model_dump(mode="json")


def verify_signature(request: Request, secret: str, now: float) -> None:
    """Check a delivery's Standard Webhooks signature and timestamp, as Photon signs them."""
    key = base64.b64decode(secret.removeprefix("whsec_"))
    if not key:
        raise TriggerValidationError("The subscription has no signing secret.")
    webhook_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    signatures = request.headers.get("webhook-signature", "").split()
    if not webhook_id or not re.fullmatch(r"[0-9]+", timestamp) or not signatures:
        raise TriggerValidationError("Missing or malformed Photon webhook headers.")
    if abs(now - int(timestamp)) > TOLERANCE_SECONDS:
        raise TriggerValidationError("The Photon webhook timestamp is more than 5 minutes off.")
    signed = f"{webhook_id}.{timestamp}.".encode() + request.get_data()
    expected = b"v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
    if not any(hmac.compare_digest(signature.encode(), expected) for signature in signatures):
        raise TriggerValidationError("Invalid Photon webhook signature.")


class PhotonTrigger(Trigger):
    """Verify each Photon delivery and start the event its type names."""

    def _dispatch_event(self, subscription: Subscription, request: Request) -> EventDispatch:
        verify_signature(request, subscription.properties["signing_secret"], time.time())
        try:
            delivery = json.loads(request.get_data())
        except ValueError:
            raise TriggerDispatchError("The Photon webhook body is not JSON.") from None
        sender = ((delivery.get("data") or {}).get("object") or {}).get("sentBy") or {}
        event = EVENTS.get(delivery.get("type"))
        return EventDispatch(
            user_id=sender.get("id") or "",
            events=[event] if event else [],
            response=Response(status=200),
            payload=delivery,
        )


class PhotonSubscriptionConstructor(TriggerSubscriptionConstructor):
    """Create and delete the Photon webhook destination that delivers to a subscription."""

    def _validate_api_key(self, credentials: Mapping[str, Any]) -> None:
        try:
            call(credentials, "list_webhook_destinations", query={"pageSize": 1})
        except PhotonError as error:
            raise TriggerProviderCredentialValidationError(str(error)) from None

    def _create_subscription(
        self,
        endpoint: str,
        parameters: Mapping[str, Any],
        credentials: Mapping[str, Any],
        credential_type: CredentialType,
    ) -> Subscription:
        try:
            created = call(
                credentials,
                "create_webhook_destination",
                headers={"Idempotency-Key": str(uuid.uuid4())},
                body={
                    "name": "Dify",
                    "url": endpoint,
                    "apiVersion": API_VERSION,
                    "enabledEvents": list(EVENTS),
                    "status": "enabled",
                },
            )
        except PhotonError as error:
            raise SubscriptionError(str(error), error_code="CREATE_DESTINATION_FAILED") from None
        return Subscription(
            endpoint=endpoint,
            parameters=parameters,
            properties={
                "destination_id": created["destination"]["destinationId"],
                "signing_secret": created["signingSecret"],
            },
        )

    def _delete_subscription(
        self,
        subscription: Subscription,
        credentials: Mapping[str, Any],
        credential_type: CredentialType,
    ) -> UnsubscribeResult:
        destination_id = subscription.properties["destination_id"]
        try:
            call(credentials, "delete_webhook_destination", path={"destinationId": destination_id})
        except PhotonError as error:
            raise UnsubscribeError(
                message=str(error), error_code="DELETE_DESTINATION_FAILED", external_response=None
            ) from None
        return UnsubscribeResult(
            success=True, message=f"Deleted Photon destination {destination_id}."
        )

    def _refresh_subscription(
        self,
        subscription: Subscription,
        credentials: Mapping[str, Any],
        credential_type: CredentialType,
    ) -> Subscription:
        # Photon destinations do not expire.
        return subscription
