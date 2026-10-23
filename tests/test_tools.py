import hashlib
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from uuid import UUID

import httpx
from dify_plugin import DifyPluginEnv
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.entities.tool import ToolRuntime
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from fixtures import (
    ATTACHMENT,
    CREDENTIALS,
    CURSOR,
    KEY,
    MESSAGE,
    OTHER_ATTACHMENT,
    OTHER_SENDER,
    OTHER_SPACE,
    PNG,
    PROJECT,
    SENDER,
    SPACE,
    attachment,
    chat,
    image,
    message,
    user,
)

from provider.client import MAX_ATTACHMENT_BYTES, MAX_IMAGE_BYTES, PhotonError
from provider.photon import PhotonProvider


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = PluginRegistration(DifyPluginEnv()).tools_mapping["photon"][2]

    def setUp(self):
        self.calls = []
        self.responses = []
        self.downloads = []
        self.download_bodies = {}
        self.expected_origin = "https://api.photon.codes"
        for target, effect in [
            ("httpx.HTTPTransport.handle_request", self.transport),
            ("dify_plugin.file.file.httpx.get", self.download),
            ("photon_api.transport.time.sleep", lambda seconds: None),
        ]:
            patcher = patch(
                target, autospec=target.startswith("httpx.HTTPTransport"), side_effect=effect
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def transport(self, _transport, request):
        self.assertEqual(f"{request.url.scheme}://{request.url.host}", self.expected_origin)
        self.assertTrue(request.url.path.startswith(f"/v1/projects/{PROJECT}/"))
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
            content=data if isinstance(data, bytes) else json.dumps(data).encode(),
            request=request,
        )

    def download(self, url, timeout=None):
        self.downloads.append(url)
        self.assertTrue(url.startswith("https://dify.example/files/"))
        return httpx.Response(
            200, content=self.download_bodies.get(url, PNG), request=httpx.Request("GET", url)
        )

    def queue(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data, content_type))

    def problem(self, status, code=None, **fields):
        self.queue(
            {"status": status, **({"code": code} if code else {}), **fields},
            status=status,
            content_type="application/problem+json",
        )

    def query(self, index=-1):
        return {
            name: values[0]
            for name, values in parse_qs(self.calls[index].url.query.decode()).items()
        }

    def body(self, index=-1):
        return json.loads(self.calls[index].content)

    def invoke(self, name, parameters, credentials=None):
        runtime = ToolRuntime(
            credentials=credentials or CREDENTIALS, user_id="local-test", session_id="local-test"
        )
        result = list(self.mapping[name][1](runtime=runtime, session=None).invoke(parameters))
        self.assertEqual(result[0].type.value, "json")
        payload = result[0].message.json_object
        self.blobs = [item for item in result if item.type.value == "blob"]
        variables = [item for item in result[1:] if item.type.value != "blob"]
        self.assertTrue(all(item.type.value == "variable" for item in variables))
        self.assertEqual(
            {item.message.variable_name: item.message.variable_value for item in variables},
            payload,
        )
        return payload

    def fails(self, name, parameters, credentials=None):
        with self.assertRaises(PhotonError) as raised:
            self.invoke(name, parameters, credentials)
        return str(raised.exception)

    def test_both_origins_route_credential_validation_and_every_tool(self):
        for origin in ["https://api.photon.codes", "https://api.staging.photon.codes"]:
            with self.subTest(origin=origin):
                self.expected_origin = origin
                credentials = {**CREDENTIALS, "api_origin": origin}
                self.queue({"items": []})
                PhotonProvider().validate_credentials(credentials)
                self.assertEqual(
                    (self.calls[-1].method, self.calls[-1].url.path, self.query()),
                    ("GET", f"/v1/projects/{PROJECT}/spaces", {"pageSize": "1"}),
                )
                self.queue(message(), status=202)
                self.invoke(
                    "send_message",
                    {
                        "space_id": SPACE,
                        "sender_id": SENDER,
                        "type": "text",
                        "format": "plain",
                        "text": "Hello",
                    },
                    credentials,
                )
                self.queue({"items": [chat()]})
                self.invoke("list_spaces", {}, credentials)
                self.queue(chat())
                self.invoke(
                    "create_or_get_space",
                    {"platform": "imessage", "participant_ids": f"{SENDER},{OTHER_SENDER}"},
                    credentials,
                )
                self.queue({"items": [message()]})
                self.invoke("list_messages", {}, credentials)
                self.queue(message())
                self.invoke("get_message", {"message_id": MESSAGE}, credentials)
                self.queue(user())
                self.invoke("get_user", {"user_id": SENDER}, credentials)
                self.queue(user())
                self.invoke(
                    "create_or_get_user",
                    {"platform": "imessage", "handle": "+14155550123"},
                    credentials,
                )
                self.queue(attachment())
                self.queue(PNG, content_type="image/png")
                self.invoke("get_attachment", {"attachment_id": ATTACHMENT}, credentials)

    def test_credential_validation_reports_the_photon_error(self):
        self.problem(401, "NOT_AUTHENTICATED", title="Not Authenticated")
        with self.assertRaises(ToolProviderCredentialValidationError) as raised:
            PhotonProvider().validate_credentials(CREDENTIALS)
        self.assertEqual(
            str(raised.exception), "Photon API HTTP 401 (NOT_AUTHENTICATED): Not Authenticated"
        )

    def test_send_text_returns_photons_message_and_a_generated_key(self):
        self.queue(message(text="Hello"), status=202)
        result = self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "text",
                "format": "plain",
                "text": "Hello",
            },
        )
        call = self.calls[-1]
        self.assertEqual((call.method, call.url.path), ("POST", f"/v1/projects/{PROJECT}/messages"))
        self.assertEqual(
            self.body(),
            {
                "spaceId": SPACE,
                "senderId": SENDER,
                "content": {"type": "text", "format": "plain", "text": "Hello"},
            },
        )
        self.assertEqual(UUID(call.headers["Idempotency-Key"]).version, 4)
        self.assertEqual(
            result,
            {**message(text="Hello"), "idempotency_key": call.headers["Idempotency-Key"]},
        )

    def test_send_passes_sender_reply_email_subject_and_caller_key(self):
        self.queue(message(platform="email"), status=202)
        result = self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "type": "text",
                "format": "plain",
                "text": "Hello",
                "sender_id": OTHER_SENDER,
                "parent_message_id": MESSAGE,
                "email_subject": "Order 1042",
                "idempotency_key": "order-1042-v1",
            },
        )
        self.assertEqual(
            self.body(),
            {
                "spaceId": SPACE,
                "senderId": OTHER_SENDER,
                "parentMessageId": MESSAGE,
                "email": {"subject": "Order 1042"},
                "content": {"type": "text", "format": "plain", "text": "Hello"},
            },
        )
        self.assertEqual(self.calls[-1].headers["Idempotency-Key"], "order-1042-v1")
        self.assertEqual(result["idempotency_key"], "order-1042-v1")

    def test_send_one_image_uploads_it_then_sends_an_attachment(self):
        self.queue(attachment(), status=201)
        self.queue(message(content={"type": "attachment", "attachmentId": ATTACHMENT}), status=202)
        result = self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "attachment",
                "format": "plain",
                "attachments": [image()],
                "idempotency_key": "photos-v1",
            },
        )
        upload = self.calls[0]
        self.assertEqual(
            (upload.method, upload.url.path), ("POST", f"/v1/projects/{PROJECT}/attachments")
        )
        self.assertEqual(
            upload.headers["Idempotency-Key"],
            hashlib.sha256(b"photos-v1").hexdigest() + ".attachment.0",
        )
        media_type, boundary = upload.headers["Content-Type"].split("; boundary=")
        self.assertEqual(media_type, "multipart/related")
        declaration, data = upload.content.split(f"--{boundary}".encode())[1:3]
        self.assertEqual(
            json.loads(declaration.split(b"\r\n\r\n", 1)[1]),
            {"contentType": "image/png", "sizeBytes": len(PNG), "filename": "photo.png"},
        )
        self.assertEqual(data, b"\r\ncontent-type: image/png\r\n\r\n" + PNG + b"\r\n")
        self.assertEqual(
            self.body(),
            {
                "spaceId": SPACE,
                "senderId": SENDER,
                "content": {"type": "attachment", "attachmentId": ATTACHMENT},
            },
        )
        self.assertEqual(result["content"], {"type": "attachment", "attachmentId": ATTACHMENT})
        self.assertEqual(self.downloads, ["https://dify.example/files/photo.png"])

    def test_send_images_with_text_become_one_group_message_with_the_text_first(self):
        group = {
            "type": "group",
            "parts": [
                {"type": "text", "format": "plain", "text": "Two photos"},
                {"type": "attachment", "attachmentId": ATTACHMENT},
                {"type": "attachment", "attachmentId": OTHER_ATTACHMENT},
            ],
        }
        self.queue(attachment(), status=201)
        self.queue(attachment(OTHER_ATTACHMENT, "image/jpeg", "photo.jpg"), status=201)
        self.queue(message(content=group), status=202)
        result = self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "attachment",
                "format": "plain",
                "text": "Two photos",
                "attachments": [image(), image("photo.jpg", "image/jpeg")],
            },
        )
        self.assertEqual(
            [call.headers["Idempotency-Key"].rsplit(".", 1)[1] for call in self.calls[:2]],
            ["0", "1"],
        )
        self.assertEqual(self.body()["content"], group)
        self.assertEqual(result["content"], group)

    def test_send_markdown_alone_and_with_images(self):
        self.queue(message(text="**Hello**"), status=202)
        self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "text",
                "format": "markdown",
                "text": "**Hello**",
            },
        )
        self.assertEqual(
            self.body()["content"], {"type": "text", "format": "markdown", "text": "**Hello**"}
        )
        self.queue(attachment(), status=201)
        self.queue(message(), status=202)
        self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "attachment",
                "text": "**Photo**",
                "format": "markdown",
                "attachments": [image()],
            },
        )
        self.assertEqual(
            self.body()["content"]["parts"][0],
            {"type": "text", "format": "markdown", "text": "**Photo**"},
        )

    def test_send_rejects_invalid_combinations_and_files_before_any_request(self):
        self.download_bodies["https://dify.example/files/large.png"] = b"0" * (MAX_IMAGE_BYTES + 1)
        cases = [
            ({}, "type text requires text"),
            ({"text": "Hi", "format": "html"}, "format must be one of plain, markdown"),
            ({"text": "Hi", "attachments": [image()]}, "type text does not take attachments"),
            ({"type": "attachment"}, "requires at least one image"),
            (
                {"type": "attachment", "attachments": [image("doc.pdf", "application/pdf")]},
                "JPEG, PNG, GIF, or WebP",
            ),
            (
                {"type": "attachment", "attachments": [image("logo.svg", "image/svg+xml")]},
                "JPEG, PNG, GIF, or WebP",
            ),
            ({"type": "attachment", "attachments": [image("large.png")]}, "at most 10 MB"),
            ({"type": "voice", "text": "Hi"}, "type must be one of text, attachment"),
        ]
        for parameters, error in cases:
            with self.subTest(error=error):
                self.assertIn(
                    error,
                    self.fails(
                        "send_message",
                        {
                            "space_id": SPACE,
                            "sender_id": SENDER,
                            "type": "text",
                            "format": "plain",
                            **parameters,
                        },
                    ),
                )
        self.assertIn(
            "Invalid input for Photon: body.senderId",
            self.fails(
                "send_message", {"space_id": SPACE, "type": "text", "format": "plain", "text": "Hi"}
            ),
        )
        self.assertEqual(self.calls, [])

    def test_send_requires_type_and_format_before_any_request(self):
        for missing in ("type", "format"):
            with self.subTest(missing=missing):
                parameters = {
                    "space_id": SPACE,
                    "sender_id": SENDER,
                    "type": "text",
                    "format": "plain",
                    "text": "Hi",
                }
                del parameters[missing]
                self.assertIn(f"{missing} must be one of", self.fails("send_message", parameters))
        self.assertEqual(self.calls, [])

    def test_photon_errors_keep_the_status_code_and_reason(self):
        self.problem(
            422,
            "UNSUPPORTED_CONTENT",
            title="Unsupported Content",
            detail="This Space cannot accept this content",
        )
        error = self.fails(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "text",
                "format": "plain",
                "text": "Hi",
            },
        )
        self.assertRegex(
            error,
            r"^Photon API HTTP 422 \(UNSUPPORTED_CONTENT\): This Space cannot accept this content "
            r"Generated idempotency_key: [0-9a-f-]{36}$",
        )
        self.problem(409, "SPACE_NOT_SENDABLE", detail="Replies are not supported for this Space")
        self.assertEqual(
            self.fails(
                "send_message",
                {
                    "space_id": SPACE,
                    "sender_id": SENDER,
                    "type": "text",
                    "format": "plain",
                    "text": "Hi",
                    "idempotency_key": "k1",
                },
            ),
            "Photon API HTTP 409 (SPACE_NOT_SENDABLE): Replies are not supported for this Space",
        )
        issue = {
            "code": "invalid_value",
            "location": "param",
            "message": "value must be a pho_msg_ TypeID",
            "path": "/messageId",
        }
        self.problem(
            422, "VALIDATION_FAILED", title="Request Validation Failed", issues=[issue, issue]
        )
        self.assertEqual(
            self.fails("get_message", {"message_id": "invalid"}),
            "Photon API HTTP 422 (VALIDATION_FAILED): messageId: value must be a pho_msg_ TypeID",
        )
        self.problem(418, "A_NEW_CODE", title="A New Problem")
        self.assertEqual(
            self.fails("get_message", {"message_id": MESSAGE}),
            "Photon API HTTP 418 (A_NEW_CODE): A New Problem",
        )
        self.queue(b"", status=500, content_type="text/plain")
        self.assertEqual(self.fails("get_message", {"message_id": MESSAGE}), "Photon API HTTP 500.")

    def test_retries_reuse_the_idempotency_key_and_unreachable_photon_is_reported(self):
        self.problem(503, title="Service Unavailable")
        self.queue(message(), status=202)
        result = self.invoke(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "text",
                "format": "plain",
                "text": "Hi",
                "idempotency_key": "retry-v1",
            },
        )
        self.assertEqual(
            [call.headers["Idempotency-Key"] for call in self.calls], ["retry-v1", "retry-v1"]
        )
        self.assertEqual(result["id"], MESSAGE)
        self.calls.clear()
        self.responses.extend([httpx.ConnectError("unreachable")] * 3)
        error = self.fails(
            "send_message",
            {
                "space_id": SPACE,
                "sender_id": SENDER,
                "type": "text",
                "format": "plain",
                "text": "Hi",
            },
        )
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(
            error,
            "Cannot reach Photon at https://api.photon.codes, or the request timed out. "
            "Check the message history before resending, and reuse the same idempotency_key "
            "for any retry. Generated idempotency_key: " + self.calls[0].headers["Idempotency-Key"],
        )
        self.responses.extend([httpx.ConnectError("unreachable")] * 3)
        self.assertEqual(
            self.fails("get_message", {"message_id": MESSAGE}),
            "Cannot reach Photon at https://api.photon.codes, or the request timed out.",
        )

    def test_results_keep_photons_field_names(self):
        space = {
            **chat(OTHER_SPACE, "email"),
            "details": {
                "latestAddressing": {
                    "from": {"address": "person@example.com"},
                    "sourceMessageId": MESSAGE,
                }
            },
        }
        self.queue({"items": [space]})
        self.assertEqual(self.invoke("list_spaces", {"platform": "email"}), {"items": [space]})

    def test_list_spaces_passes_filters_and_returns_photons_page(self):
        page = {"items": [chat(), chat(OTHER_SPACE, "telegram")], "nextPageToken": CURSOR}
        self.queue(page)
        result = self.invoke(
            "list_spaces",
            {
                "platform": "telegram",
                "participant_handle": "+14155550123",
                "order": "asc",
                "page_size": 50,
                "page_token": CURSOR,
            },
        )
        self.assertEqual(
            self.query(),
            {
                "platform": "telegram",
                "participantHandle": "+14155550123",
                "order": "asc",
                "pageSize": "50",
                "pageToken": CURSOR,
            },
        )
        self.assertEqual(result, page)
        self.queue({"items": []})
        self.assertEqual(
            self.invoke("list_spaces", {"platform": "", "page_size": None}), {"items": []}
        )
        self.assertEqual(self.query(), {"pageSize": "20"})

    def test_list_messages_passes_filters_and_returns_photons_page(self):
        page = {
            "items": [message(space=SPACE), message("delivered", space=OTHER_SPACE)],
            "nextPageToken": CURSOR,
        }
        self.queue(page)
        result = self.invoke(
            "list_messages",
            {
                "platform": "imessage",
                "direction": "sent",
                "order": "asc",
                "page_size": 200,
                "created_since": "2026-10-19T00:00:00Z",
                "created_before": "2026-10-20T00:00:00Z",
            },
        )
        self.assertEqual(
            self.query(),
            {
                "platform": "imessage",
                "direction": "sent",
                "order": "asc",
                "pageSize": "200",
                "createdSince": "2026-10-19T00:00:00Z",
                "createdBefore": "2026-10-20T00:00:00Z",
            },
        )
        self.assertEqual(result, page)
        self.queue({"items": [message(), message("received")]})
        result = self.invoke("list_messages", {"space_id": SPACE, "perspective_user_id": SENDER})
        self.assertEqual(
            self.query(), {"pageSize": "20", "spaceId": SPACE, "perspectiveUserId": SENDER}
        )
        self.assertEqual([item["status"] for item in result["items"]], ["dispatched", "received"])

    def test_get_message_returns_photons_message_with_status_and_reasons(self):
        for status in ["failed", "accepted", "delivered"]:
            with self.subTest(status=status):
                self.queue(message(status))
                self.assertEqual(
                    self.invoke("get_message", {"message_id": MESSAGE}), message(status)
                )
        self.assertEqual(self.calls[-1].url.path, f"/v1/projects/{PROJECT}/messages/{MESSAGE}")
        content = {
            "type": "text",
            "format": "plain",
            "text": "Hi",
            "metadata": {"crm": {"ticketId": "T-1", "SKU": "A1"}},
        }
        self.queue(message("received", content=content))
        self.assertEqual(self.invoke("get_message", {"message_id": MESSAGE})["content"], content)

    def test_get_user_returns_photons_user(self):
        self.queue(user(OTHER_SENDER, "human", "+14155550199"))
        result = self.invoke("get_user", {"user_id": OTHER_SENDER})
        self.assertEqual(self.calls[-1].url.path, f"/v1/projects/{PROJECT}/users/{OTHER_SENDER}")
        self.assertEqual(result, user(OTHER_SENDER, "human", "+14155550199"))

    def test_create_or_get_user_sends_platform_and_handle_and_returns_photons_user(self):
        self.queue(user(OTHER_SENDER, "human", "+14155550199", platform="sms"))
        result = self.invoke("create_or_get_user", {"platform": "sms", "handle": "+14155550199"})
        call = self.calls[-1]
        self.assertEqual((call.method, call.url.path), ("POST", f"/v1/projects/{PROJECT}/users"))
        self.assertEqual(self.body(), {"platform": "sms", "handle": "+14155550199"})
        self.assertEqual(result, user(OTHER_SENDER, "human", "+14155550199", platform="sms"))

    def test_create_or_get_space_sends_participants_and_returns_photons_space_with_its_key(self):
        self.queue(chat(platform="sms"), status=201)
        result = self.invoke(
            "create_or_get_space",
            {"platform": "sms", "participant_ids": f"{SENDER}, {OTHER_SENDER}"},
        )
        call = self.calls[-1]
        self.assertEqual((call.method, call.url.path), ("POST", f"/v1/projects/{PROJECT}/spaces"))
        self.assertEqual(self.body(), {"platform": "sms", "participantIds": [SENDER, OTHER_SENDER]})
        self.assertEqual(UUID(call.headers["Idempotency-Key"]).version, 4)
        self.assertEqual(
            result, {**chat(platform="sms"), "idempotency_key": call.headers["Idempotency-Key"]}
        )
        self.queue(chat(platform="email"))
        result = self.invoke(
            "create_or_get_space",
            {
                "platform": "email",
                "participant_ids": f"{SENDER},{OTHER_SENDER}",
                "idempotency_key": "order-1042-thread",
            },
        )
        self.assertEqual(self.calls[-1].headers["Idempotency-Key"], "order-1042-thread")
        self.assertEqual(result["idempotency_key"], "order-1042-thread")

    def test_create_or_get_space_errors_carry_the_generated_key(self):
        issue = {"code": "invalid_value", "location": "body", "message": "needs an Agent"}
        self.problem(422, "VALIDATION_FAILED", title="Request Validation Failed", issues=[issue])
        error = self.fails(
            "create_or_get_space", {"platform": "sms", "participant_ids": OTHER_SENDER}
        )
        self.assertEqual(
            error,
            "Photon API HTTP 422 (VALIDATION_FAILED): needs an Agent Generated idempotency_key: "
            + self.calls[-1].headers["Idempotency-Key"],
        )
        self.calls.clear()
        self.responses.extend([httpx.ConnectError("unreachable")] * 3)
        error = self.fails(
            "create_or_get_space",
            {"platform": "sms", "participant_ids": SENDER, "idempotency_key": "k1"},
        )
        self.assertEqual(
            [call.headers["Idempotency-Key"] for call in self.calls], ["k1", "k1", "k1"]
        )
        self.assertEqual(
            error,
            "Cannot reach Photon at https://api.photon.codes, or the request timed out. "
            "Reuse the same idempotency_key for any retry.",
        )

    def test_get_attachment_returns_metadata_and_the_file(self):
        self.queue(attachment())
        self.queue(PNG, content_type="image/png")
        result = self.invoke("get_attachment", {"attachment_id": ATTACHMENT})
        self.assertEqual(
            [call.url.path for call in self.calls],
            [
                f"/v1/projects/{PROJECT}/attachments/{ATTACHMENT}",
                f"/v1/projects/{PROJECT}/attachments/{ATTACHMENT}/content",
            ],
        )
        self.assertEqual(result, attachment())
        self.assertEqual(len(self.blobs), 1)
        self.assertEqual(
            (
                self.blobs[0].message.blob,
                self.blobs[0].meta["mime_type"],
                self.blobs[0].meta["filename"],
            ),
            (PNG, "image/png", "photo.png"),
        )

    def test_get_attachment_over_50_mb_is_not_downloaded(self):
        self.queue(attachment(size=MAX_ATTACHMENT_BYTES + 1))
        self.assertIn(
            "larger than 50 MB", self.fails("get_attachment", {"attachment_id": ATTACHMENT})
        )
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
