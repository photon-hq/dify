import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

import httpx
from dify_plugin import DifyPluginEnv
from dify_plugin.core.entities.invocation import InvokeType
from dify_plugin.core.entities.plugin.request import EndpointInvokeRequest
from dify_plugin.core.plugin_executor import PluginExecutor
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.core.runtime import Session
from endpoints.photon_bot import verify_signature
from fixtures import (
    AGENT,
    APP,
    CONVERSATION,
    KEY,
    MESSAGE,
    OTHER_APP,
    OTHER_CONVERSATION,
    OTHER_MESSAGE,
    OTHER_SPACE,
    PROJECT,
    SECRET,
    SETTINGS,
    SPACE,
    VECTOR,
    answer,
    delivery,
    sent,
    user,
)
from werkzeug import Request
from werkzeug.test import EnvironBuilder


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
    }


class BotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = PluginExecutor(DifyPluginEnv(), PluginRegistration(DifyPluginEnv()))

    def setUp(self):
        self.calls = []
        self.responses = []
        self.storage = {}
        self.app_calls = []
        self.answers = []
        self.expected_origin = "https://api.photon.codes"
        for target, effect in [
            ("httpx.HTTPTransport.handle_request", self.transport),
            ("photon_api.transport.time.sleep", lambda seconds: None),
            ("dify_plugin.core.runtime.BackwardsInvocation._backwards_invoke", self.dify),
        ]:
            patcher = patch(target, autospec=not target.endswith(".sleep"), side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def transport(self, _transport, request):
        self.assertEqual(f"{request.url.scheme}://{request.url.host}", self.expected_origin)
        self.assertEqual(request.url.path, f"/v1/projects/{PROJECT}/messages")
        self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)
        request.read()
        self.calls.append(request)
        self.assertTrue(self.responses, "Unexpected additional HTTP request")
        queued = self.responses.pop(0)
        if isinstance(queued, Exception):
            raise queued
        status, data, content_type = queued
        return httpx.Response(
            status,
            headers={"Content-Type": content_type},
            content=json.dumps(data).encode(),
            request=request,
        )

    def dify(self, _invocation, kind, _data_type, data):
        """Dify's side of the plugin's storage and app calls."""
        if kind == InvokeType.Storage:
            if data["opt"] == "exist":
                yield {"data": data["key"] in self.storage}
            elif data["opt"] == "get":
                yield {"data": self.storage[data["key"]].hex()}
            else:
                self.assertEqual(data["opt"], "set")
                self.storage[data["key"]] = bytes.fromhex(data["value"])
                yield {"data": "ok"}
            return
        self.assertEqual(kind, InvokeType.App)
        self.app_calls.append(data)
        self.assertTrue(self.answers, "Unexpected additional app call")
        queued = self.answers.pop(0)
        if isinstance(queued, Exception):
            raise queued
        yield queued

    def queue(self, data, status=202, content_type="application/json"):
        self.responses.append((status, data, content_type))

    def problem(self, status, code, **fields):
        self.queue(
            {"status": status, "code": code, **fields},
            status=status,
            content_type="application/problem+json",
        )

    def deliver(self, payload, headers=None, settings=SETTINGS):
        """POST a delivery to the endpoint as Dify hands it over; return Photon's HTTP status
        and the response body."""
        body = json.dumps(payload).encode()
        head = {
            "host": "dify.example",
            "content-type": "application/json",
            "content-length": str(len(body)),
            **(signed(body) if headers is None else headers(body)),
        }
        raw = "POST / HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in head.items()) + "\r\n"
        (response,) = self.executor.invoke_endpoint(
            Session.empty_session(),
            EndpointInvokeRequest(settings=settings, raw_http_request=(raw.encode() + body).hex()),
        )
        return response["status"], bytes.fromhex(response["result"]).decode()

    def stored(self):
        return {key: json.loads(value) for key, value in self.storage.items()}

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
            "no secret": (VECTOR["body"], headers, "", VECTOR["now"]),
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
            with self.subTest(case=name), self.assertRaises(ValueError):
                verify_signature(request(body, case_headers), secret, now)
        verify_signature(request(VECTOR["body"], headers), VECTOR["secret"], VECTOR["now"] + 300)

    def test_unverified_deliveries_get_401_and_nothing_runs(self):
        unset = {name: value for name, value in SETTINGS.items() if name != "signing_secret"}
        cases = [
            ("unsigned", lambda body: {}, SETTINGS, "Missing or malformed Photon webhook headers."),
            (
                "other secret",
                lambda body: signed(body, "whsec_" + base64.b64encode(b"x" * 32).decode()),
                SETTINGS,
                "Invalid Photon webhook signature.",
            ),
            (
                "stale",
                lambda body: signed(body, timestamp=int(time.time()) - 301),
                SETTINGS,
                "The Photon webhook timestamp is more than 5 minutes off.",
            ),
            (
                "no secret set, signed with an empty key",
                lambda body: signed(body, "whsec_"),
                unset,
                "The endpoint has no signing secret yet.",
            ),
        ]
        for name, headers, settings, reason in cases:
            with self.subTest(case=name):
                self.assertEqual(self.deliver(delivery(), headers, settings), (401, reason))
        self.assertEqual((self.storage, self.app_calls, self.calls), ({}, [], []))

    def test_other_events_contents_and_agent_senders_are_acknowledged_without_an_answer(self):
        without_receiver = delivery()
        del without_receiver["data"]["object"]["receivedBy"]
        cases = {
            "another event": delivery("message.delivered", status="delivered"),
            "an event without a message": {"type": "space.updated", "data": {}},
            "an image": delivery(content={"type": "attachment", "attachmentId": "pho_att_1"}),
            "a message from an agent": delivery(sender=user(AGENT, "agent", "photon_test_bot")),
            "a message without receivedBy": without_receiver,
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.deliver(payload), (200, ""))
        self.assertEqual((self.storage, self.app_calls, self.calls), ({}, [], []))

    def test_a_message_starts_a_conversation_and_its_answer_is_sent_into_the_space(self):
        self.answers.append(answer())
        self.queue(sent())
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(
            self.app_calls,
            [
                {
                    "app_id": APP,
                    "query": "Hi",
                    "inputs": {"tone": "brief"},
                    "response_mode": "blocking",
                    "conversation_id": None,
                    "user": None,
                }
            ],
        )
        self.assertEqual(
            self.stored(),
            {f"{APP}:{SPACE}": {"message_id": MESSAGE, "conversation_id": CONVERSATION}},
        )
        (call,) = self.calls
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.headers["Idempotency-Key"], f"{MESSAGE}.reply")
        self.assertEqual(
            json.loads(call.content),
            {
                "spaceId": SPACE,
                "senderId": AGENT,
                "content": {"type": "text", "format": "plain", "text": "Hello from the app."},
            },
        )

    def test_later_messages_in_the_space_continue_its_conversation(self):
        self.answers.extend([answer(), answer("Second answer.")])
        self.queue(sent())
        self.queue(sent("Second answer."))
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(self.deliver(delivery(message_id=OTHER_MESSAGE, text="And?")), (200, ""))
        self.assertEqual(
            [(call["query"], call["conversation_id"]) for call in self.app_calls],
            [("Hi", None), ("And?", CONVERSATION)],
        )
        self.assertEqual(
            self.stored(),
            {f"{APP}:{SPACE}": {"message_id": OTHER_MESSAGE, "conversation_id": CONVERSATION}},
        )
        self.assertEqual(self.calls[1].headers["Idempotency-Key"], f"{OTHER_MESSAGE}.reply")
        self.assertEqual(json.loads(self.calls[1].content)["content"]["text"], "Second answer.")

    def test_each_space_and_each_app_has_its_own_conversation(self):
        self.answers.extend([answer(), answer(conversation=OTHER_CONVERSATION), answer()])
        self.queue(sent())
        self.queue(sent(space=OTHER_SPACE))
        self.queue(sent())
        other_app = {**SETTINGS, "app": {**SETTINGS["app"], "app_id": OTHER_APP}}
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(
            self.deliver(delivery(message_id=OTHER_MESSAGE, space=OTHER_SPACE)), (200, "")
        )
        self.assertEqual(self.deliver(delivery(), settings=other_app), (200, ""))
        self.assertEqual(
            [(call["app_id"], call["conversation_id"]) for call in self.app_calls],
            [(APP, None), (APP, None), (OTHER_APP, None)],
        )
        self.assertEqual(
            self.stored(),
            {
                f"{APP}:{SPACE}": {"message_id": MESSAGE, "conversation_id": CONVERSATION},
                f"{APP}:{OTHER_SPACE}": {
                    "message_id": OTHER_MESSAGE,
                    "conversation_id": OTHER_CONVERSATION,
                },
                f"{OTHER_APP}:{SPACE}": {"message_id": MESSAGE, "conversation_id": CONVERSATION},
            },
        )
        self.assertEqual(json.loads(self.calls[1].content)["spaceId"], OTHER_SPACE)

    def test_a_message_delivered_again_is_not_answered_again(self):
        self.answers.append(answer())
        self.queue(sent())
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual((len(self.app_calls), len(self.calls)), (1, 1))

    def test_photon_errors_fail_the_delivery_once_and_send_no_second_reply(self):
        self.answers.append(answer())
        self.problem(409, "SPACE_NOT_SENDABLE", detail="This Space cannot be sent to")
        self.assertEqual(
            self.deliver(delivery()), (500, "Internal Server Error: This Space cannot be sent to")
        )
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual((len(self.app_calls), len(self.calls)), (1, 1))
        self.assertEqual(
            self.stored(),
            {f"{APP}:{SPACE}": {"message_id": MESSAGE, "conversation_id": CONVERSATION}},
        )
        self.answers.append(answer())
        self.responses.extend([httpx.ConnectError("unreachable")] * 3)
        status, _ = self.deliver(delivery(message_id=OTHER_MESSAGE))
        self.assertEqual(status, 500)
        self.assertEqual(
            [call.headers["Idempotency-Key"] for call in self.calls[1:]],
            [f"{OTHER_MESSAGE}.reply"] * 3,
        )

    def test_app_errors_fail_the_delivery_once_without_a_reply(self):
        self.answers.append(Exception("invoke app failed: model rate limited"))
        self.assertEqual(
            self.deliver(delivery()),
            (500, "Internal Server Error: invoke app failed: model rate limited"),
        )
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual((len(self.app_calls), self.calls), (1, []))
        self.assertEqual(self.stored(), {f"{APP}:{SPACE}": {"message_id": MESSAGE}})

    def test_after_a_failed_app_call_the_next_message_starts_a_new_conversation(self):
        third = "pho_msg_00000000000000000000000004"
        self.answers.extend(
            [
                answer(),
                Exception("Conversation Not Exists."),
                answer(conversation=OTHER_CONVERSATION),
            ]
        )
        self.queue(sent())
        self.queue(sent())
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(self.deliver(delivery(message_id=OTHER_MESSAGE, text="And?"))[0], 500)
        self.assertEqual(self.deliver(delivery(message_id=third, text="Hello?")), (200, ""))
        self.assertEqual(
            [call["conversation_id"] for call in self.app_calls], [None, CONVERSATION, None]
        )
        self.assertEqual(
            self.stored(),
            {f"{APP}:{SPACE}": {"message_id": third, "conversation_id": OTHER_CONVERSATION}},
        )

    def test_an_empty_answer_keeps_the_conversation_and_sends_nothing(self):
        self.answers.append(answer(""))
        self.assertEqual(self.deliver(delivery()), (200, ""))
        self.assertEqual(self.calls, [])
        self.assertEqual(
            self.stored(),
            {f"{APP}:{SPACE}": {"message_id": MESSAGE, "conversation_id": CONVERSATION}},
        )

    def test_staging_replies_go_to_the_staging_origin(self):
        self.expected_origin = "https://api.staging.photon.codes"
        self.answers.append(answer())
        self.queue(sent())
        staging = {**SETTINGS, "api_origin": "https://api.staging.photon.codes"}
        self.assertEqual(self.deliver(delivery(), settings=staging), (200, ""))
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
