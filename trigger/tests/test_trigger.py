import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
from dify_plugin import DifyPluginEnv
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.entities.provider_config import CredentialType
from dify_plugin.entities.trigger import Subscription, TriggerSubscriptionConstructorRuntime
from dify_plugin.errors.trigger import (
    EventIgnoreError,
    SubscriptionError,
    TriggerProviderCredentialValidationError,
    TriggerValidationError,
    UnsubscribeError,
)
from dify_plugin.interfaces.trigger import EventRuntime
from fixtures import (
    CREDENTIALS,
    DESTINATION,
    ENDPOINT,
    KEY,
    PERSON,
    PROJECT,
    SECRET,
    VECTOR,
    delivery,
    destination,
    message,
)
from provider.photon_trigger import verify_signature
from werkzeug import Request
from werkzeug.test import EnvironBuilder

SUBSCRIPTION = Subscription(
    endpoint=ENDPOINT,
    parameters={},
    properties={"destination_id": DESTINATION, "signing_secret": SECRET},
)


def request(body, headers):
    return Request(EnvironBuilder(method="POST", data=body, headers=headers).get_environ())


def signed(body, secret=SECRET, timestamp=None):
    """Headers Photon would send for this body, signed independently of the plugin."""
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"pho_evt_1.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return {
        "webhook-id": "pho_evt_1",
        "webhook-timestamp": timestamp,
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
        "content-type": "application/json",
    }


class TriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registration = PluginRegistration(DifyPluginEnv())

    def setUp(self):
        self.calls = []
        self.responses = []
        self.expected_origin = "https://api.photon.codes"
        for target, effect in [
            ("httpx.HTTPTransport.handle_request", self.transport),
            ("photon_api.transport.time.sleep", lambda seconds: None),
        ]:
            patcher = patch(
                target, autospec=target.startswith("httpx.HTTPTransport"), side_effect=effect
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def transport(self, _transport, request):
        self.assertEqual(f"{request.url.scheme}://{request.url.host}", self.expected_origin)
        self.assertTrue(request.url.path.startswith(f"/v1/projects/{PROJECT}/webhooks/"))
        self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)
        request.read()
        self.calls.append(request)
        self.assertTrue(self.responses, "Unexpected additional HTTP request")
        status, data, content_type = self.responses.pop(0)
        return httpx.Response(
            status,
            headers={"Content-Type": content_type},
            content=json.dumps(data).encode(),
            request=request,
        )

    def queue(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data, content_type))

    def problem(self, status, code, **fields):
        self.queue(
            {"status": status, "code": code, **fields},
            status=status,
            content_type="application/problem+json",
        )

    def constructor(self, credentials=None):
        runtime = TriggerSubscriptionConstructorRuntime(
            session=None, credential_type=CredentialType.API_KEY, credentials=credentials
        )
        return self.registration.get_trigger_subscription_constructor("photon_trigger", runtime)

    def dispatch(self, body, headers):
        trigger = self.registration.get_trigger_provider(
            "photon_trigger", None, None, CredentialType.API_KEY
        )
        return trigger.dispatch_event(SUBSCRIPTION, request(body, headers))

    def test_photons_standard_webhooks_vector_verifies(self):
        verify_signature(
            request(VECTOR["body"], VECTOR["headers"]), VECTOR["secret"], VECTOR["now"]
        )
        rotating = {
            **VECTOR["headers"],
            "webhook-signature": "v1,AAAA " + VECTOR["headers"]["webhook-signature"],
        }
        verify_signature(request(VECTOR["body"], rotating), VECTOR["secret"], VECTOR["now"])

    def test_signature_check_rejects_changed_bodies_keys_times_and_headers(self):
        headers = VECTOR["headers"]
        cases = {
            "changed body": (VECTOR["body"] + b" ", headers, VECTOR["secret"], VECTOR["now"]),
            "other secret": (VECTOR["body"], headers, SECRET, VECTOR["now"]),
            "late": (VECTOR["body"], headers, VECTOR["secret"], VECTOR["now"] + 301),
            "early": (VECTOR["body"], headers, VECTOR["secret"], VECTOR["now"] - 301),
            "no signature": (
                VECTOR["body"],
                {**headers, "webhook-signature": ""},
                VECTOR["secret"],
                VECTOR["now"],
            ),
            "bad timestamp": (
                VECTOR["body"],
                {**headers, "webhook-timestamp": "1767225600.0"},
                VECTOR["secret"],
                VECTOR["now"],
            ),
        }
        for name, (body, case_headers, secret, now) in cases.items():
            with self.subTest(case=name), self.assertRaises(TriggerValidationError):
                verify_signature(request(body, case_headers), secret, now)
        verify_signature(request(VECTOR["body"], headers), VECTOR["secret"], VECTOR["now"] + 300)

    def test_a_signed_message_received_starts_its_event_with_photons_message(self):
        body = json.dumps(delivery()).encode()
        dispatched = self.dispatch(body, signed(body))
        self.assertEqual(dispatched.events, ["message_received"])
        self.assertEqual(dispatched.user_id, PERSON)
        self.assertEqual(dispatched.response.status_code, 200)
        self.assertEqual(dispatched.payload, delivery())
        event = self.registration.get_trigger_event_handler(
            "photon_trigger",
            "message_received",
            EventRuntime(
                session=None, credential_type=CredentialType.API_KEY, subscription=SUBSCRIPTION
            ),
        )
        variables = event.on_event(request(body, signed(body)), {}, dispatched.payload)
        self.assertEqual(variables.variables, message())

    def test_unsigned_or_wrongly_signed_deliveries_are_rejected(self):
        body = json.dumps(delivery()).encode()
        for name, headers in {
            "unsigned": {"content-type": "application/json"},
            "other secret": signed(body, secret="whsec_" + base64.b64encode(b"x" * 32).decode()),
            "stale": signed(body, timestamp=int(time.time()) - 600),
        }.items():
            with self.subTest(case=name), self.assertRaises(TriggerValidationError):
                self.dispatch(body, headers)

    def test_other_event_types_start_nothing(self):
        body = json.dumps(delivery("message.delivered")).encode()
        dispatched = self.dispatch(body, signed(body))
        self.assertEqual(dispatched.events, [])
        self.assertEqual(dispatched.response.status_code, 200)

    def test_both_origins_route_validation_and_subscriptions(self):
        for origin in ["https://api.photon.codes", "https://api.staging.photon.codes"]:
            with self.subTest(origin=origin):
                self.expected_origin = origin
                credentials = {**CREDENTIALS, "api_origin": origin}
                self.queue({"destinations": []})
                self.constructor().validate_api_key(credentials)
                self.assertEqual(self.calls[-1].method, "GET")
                self.assertEqual(self.calls[-1].url.params["pageSize"], "1")
                self.queue({"destination": destination(), "signingSecret": SECRET}, status=201)
                self.constructor(credentials).create_subscription(
                    ENDPOINT, {}, credentials, CredentialType.API_KEY
                )
                self.queue(destination(deletedAt="2026-10-22T00:01:00.000Z"))
                self.constructor(credentials).delete_subscription(
                    SUBSCRIPTION, credentials, CredentialType.API_KEY
                )
        self.assertEqual(len(self.calls), 6)

    def test_validation_passes_on_photons_error(self):
        self.problem(401, "UNAUTHORIZED", detail="Invalid API key")
        with self.assertRaises(TriggerProviderCredentialValidationError) as raised:
            self.constructor().validate_api_key(CREDENTIALS)
        self.assertEqual(
            str(raised.exception), "Photon API HTTP 401 (UNAUTHORIZED): Invalid API key"
        )

    def test_other_origins_are_refused_before_any_request(self):
        credentials = {**CREDENTIALS, "api_origin": "https://photon.example"}
        expected = (
            "api_origin must be https://api.photon.codes or https://api.staging.photon.codes."
        )
        with self.assertRaises(TriggerProviderCredentialValidationError) as raised:
            self.constructor().validate_api_key(credentials)
        self.assertEqual(str(raised.exception), expected)
        with self.assertRaises(SubscriptionError) as raised:
            self.constructor(credentials).create_subscription(
                ENDPOINT, {}, credentials, CredentialType.API_KEY
            )
        self.assertEqual(str(raised.exception), expected)
        self.assertEqual(self.calls, [])

    def test_subscribing_creates_a_destination_for_the_endpoint_and_keeps_its_secret(self):
        self.queue({"destination": destination(), "signingSecret": SECRET}, status=201)
        subscription = self.constructor(CREDENTIALS).create_subscription(
            ENDPOINT, {}, CREDENTIALS, CredentialType.API_KEY
        )
        call = self.calls[-1]
        self.assertEqual(
            (call.method, call.url.path), ("POST", f"/v1/projects/{PROJECT}/webhooks/destinations")
        )
        UUID(call.headers["Idempotency-Key"])
        self.assertEqual(
            json.loads(call.content),
            {
                "name": "Dify",
                "url": ENDPOINT,
                "apiVersion": "2026-07-01",
                "enabledEvents": ["message.received"],
                "status": "enabled",
            },
        )
        self.assertEqual(subscription.endpoint, ENDPOINT)
        self.assertEqual(subscription.expires_at, -1)
        self.assertEqual(
            subscription.properties, {"destination_id": DESTINATION, "signing_secret": SECRET}
        )

    def test_subscribing_passes_on_photons_error(self):
        self.problem(
            422,
            "VALIDATION_FAILED",
            issues=[{"path": "/url", "message": "must be an HTTPS URL"}],
        )
        with self.assertRaises(SubscriptionError) as raised:
            self.constructor(CREDENTIALS).create_subscription(
                "http://localhost/triggers/plugin/1", {}, CREDENTIALS, CredentialType.API_KEY
            )
        self.assertEqual(
            str(raised.exception),
            "Photon API HTTP 422 (VALIDATION_FAILED): url: must be an HTTPS URL",
        )

    def test_unsubscribing_deletes_the_destination(self):
        self.queue(destination(deletedAt="2026-10-22T00:01:00.000Z"))
        result = self.constructor(CREDENTIALS).delete_subscription(
            SUBSCRIPTION, CREDENTIALS, CredentialType.API_KEY
        )
        call = self.calls[-1]
        self.assertEqual(
            (call.method, call.url.path),
            ("DELETE", f"/v1/projects/{PROJECT}/webhooks/destinations/{DESTINATION}"),
        )
        self.assertTrue(result.success)
        self.problem(404, "NOT_FOUND", detail="Webhook destination not found")
        with self.assertRaises(UnsubscribeError) as raised:
            self.constructor(CREDENTIALS).delete_subscription(
                SUBSCRIPTION, CREDENTIALS, CredentialType.API_KEY
            )
        self.assertEqual(
            str(raised.exception), "Photon API HTTP 404 (NOT_FOUND): Webhook destination not found"
        )

    def test_event_parameters_skip_messages_that_do_not_match(self):
        event = self.registration.get_trigger_event_handler(
            "photon_trigger",
            "message_received",
            EventRuntime(
                session=None, credential_type=CredentialType.API_KEY, subscription=SUBSCRIPTION
            ),
        )
        body = json.dumps(delivery()).encode()
        incoming = request(body, signed(body))
        for parameters in [
            {},
            {"platforms": ["telegram", "sms"]},
            {"text_contains": "hI"},
            {"text_regex": "^H"},
        ]:
            with self.subTest(parameters=parameters):
                self.assertEqual(
                    event.on_event(incoming, parameters, delivery()).variables, message()
                )
        for parameters in [
            {"platforms": ["imessage"]},
            {"text_contains": "bye"},
            {"text_regex": "^x"},
            {"text_regex": "("},
        ]:
            with self.subTest(parameters=parameters), self.assertRaises(EventIgnoreError):
                event.on_event(incoming, parameters, delivery())
        photo = delivery()
        photo["data"]["object"]["content"] = {"type": "attachment", "attachmentId": "pho_att_1"}
        with self.assertRaises(EventIgnoreError):
            event.on_event(incoming, {"text_contains": "hi"}, photo)

    def test_refreshing_keeps_the_subscription(self):
        refreshed = self.constructor(CREDENTIALS).refresh_subscription(
            SUBSCRIPTION, CREDENTIALS, CredentialType.API_KEY
        )
        self.assertEqual(refreshed, SUBSCRIPTION)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
