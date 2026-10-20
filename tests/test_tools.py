import hashlib
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from dify_plugin import DifyPluginEnv
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.entities.tool import ToolInvokeMessage, ToolRuntime
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
import httpx
import requests
import yaml

from fixtures import ATTACHMENT, CREDENTIALS, CURSOR, FAILED_MESSAGE, KEY, MESSAGE, NOW, OTHER_ATTACHMENT, OTHER_SENDER, OTHER_SPACE, PNG, PROJECT, SENDER, SPACE, attachment, chat, image, message
from provider.client import IMAGE_TYPES, MAX_ATTACHMENT_BYTES, MAX_EMAIL_SUBJECT_LENGTH, MAX_IMAGE_BYTES, MAX_TEXT_LENGTH, PLATFORMS, PhotonClient, PhotonError
from provider.photon import PhotonProvider


class ToolAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registration = PluginRegistration(DifyPluginEnv())
        cls.mapping = cls.registration.tools_mapping["photon"][2]
        cls.contract = None
        if os.environ.get("PHOTON_OPENAPI"):
            from openapi_contract import OpenAPIContract
            cls.contract = OpenAPIContract()

    def setUp(self):
        self.calls = []
        self.responses = []
        self.expected_origin = "https://api.photon.codes"
        self.mock_send = patch("requests.adapters.HTTPAdapter.send", autospec=True, side_effect=self.transport)
        self.mock_send.start()
        self.addCleanup(self.mock_send.stop)
        self.downloads = []
        self.download_bodies = {}
        self.mock_download = patch("dify_plugin.file.file.httpx.get", side_effect=self.download)
        self.mock_download.start()
        self.addCleanup(self.mock_download.stop)

    def download(self, url, timeout=None):
        self.downloads.append(url)
        self.assertTrue(url.startswith("https://dify.example/files/"))
        return httpx.Response(200, content=self.download_bodies.get(url, PNG), request=httpx.Request("GET", url))

    def transport(self, adapter, request, **kwargs):
        self.assertEqual(adapter.max_retries.total, 0)
        self.assertEqual(urlparse(request.url).scheme, "https")
        self.assertEqual(urlparse(request.url).netloc, urlparse(self.expected_origin).netloc)
        self.assertTrue(urlparse(request.url).path.startswith(f"/v1/projects/{PROJECT}/"))
        self.assertEqual(request.headers["Authorization"], "Bearer " + KEY)
        self.assertEqual(kwargs["timeout"], (5, 15))
        self.assertIs(kwargs["verify"], True)
        self.assertEqual(kwargs["proxies"], {})
        if self.contract:
            self.contract.validate_request(request)
        self.calls.append(request)
        self.assertTrue(self.responses, "Unexpected additional HTTP request or retry")
        queued = self.responses.pop(0)
        if isinstance(queued, Exception):
            raise queued
        status, data, content_type, headers = queued
        response = requests.Response()
        response.status_code = status
        response.headers = {"Content-Type": content_type, **headers}
        response._content = json.dumps(data).encode() if not isinstance(data, bytes) else data
        response._content_consumed = True
        response.request = request
        response.url = request.url
        return response

    def queue(self, data, status=200, content_type="application/json", headers=None):
        self.responses.append((status, data, content_type, headers or {}))

    def invoke(self, name, parameters, credentials=None):
        runtime = ToolRuntime(credentials=credentials or CREDENTIALS, user_id="local-test", session_id="local-test")
        tool = self.mapping[name][1](runtime=runtime, session=None)
        result = list(tool.invoke(parameters))
        self.assertTrue(result)
        self.assertEqual(result[0].type.value, "json")
        payload = result[0].message.json_object
        expected = {key: value for key, value in payload.items() if key not in {"text", "files", "json"}}
        self.blobs = [item for item in result if item.type.value == "blob"]
        self.assertEqual(len(result), len(expected) + 1 + len(self.blobs))
        variables = [item for item in result[1:] if item.type.value != "blob"]
        self.assertTrue(all(item.type.value == "variable" for item in variables))
        self.assertEqual([item.message.variable_name for item in variables], list(expected))
        self.assertEqual({item.message.variable_name: item.message.variable_value for item in variables}, expected)
        self.assertFalse({"text", "files", "json"} & {item.message.variable_name for item in variables})
        for item in result[:len(result) - len(self.blobs)]:
            serialized = item.model_dump_json()
            self.assertNotIn(KEY, serialized)
            restored = ToolInvokeMessage.model_validate_json(serialized)
            self.assertEqual(restored.message, item.message)
        if self.contract:
            self.contract.validator(self.mapping[name][0].output_schema).validate(payload)
        return payload

    def test_every_tool_emits_named_variables_for_every_non_reserved_top_level_field(self):
        cases = [
            ("send_message", {"space_id": SPACE, "text": "Synthetic variable acceptance."}, message(text="Synthetic variable acceptance."), 202),
            ("list_spaces", {}, {"items": [chat()]}, 200),
            ("list_messages", {}, {"items": [message()]}, 200),
            ("get_message", {"message_id": FAILED_MESSAGE}, message("failed"), 200),
        ]
        for name, parameters, data, status in cases:
            with self.subTest(tool=name):
                self.queue(data, status=status)
                self.invoke(name, parameters)
        self.queue(attachment())
        self.queue(PNG, content_type="image/png")
        self.invoke("get_attachment", {"attachment_id": ATTACHMENT})

    def test_reserved_output_names_are_not_emitted_by_any_tool_and_text_stays_in_json(self):
        text = "Synthetic reserved-output regression."
        cases = [
            ("send_message", {"space_id": SPACE, "text": text}, message(text=text), 202),
            ("get_message", {"message_id": MESSAGE}, message(text=text), 200),
            ("list_messages", {}, {"items": [message(text=text)]}, 200),
            ("list_spaces", {}, {"items": [chat()]}, 200),
        ]
        for name, parameters, data, status in cases:
            with self.subTest(tool=name):
                self.queue(data, status=status)
                result = self.invoke(name, parameters)
                if name in {"send_message", "get_message"}:
                    self.assertEqual(result["text"], text)
                elif name == "list_messages":
                    self.assertEqual(result["items"][0]["text"], text)

    def test_sdk_preserves_nested_variable_values_lists_scalars_and_null(self):
        runtime = ToolRuntime(credentials={}, user_id=None, session_id=None)
        tool = self.mapping["get_message"][1](runtime=runtime, session=None)
        values = {
            "timestamps": {"dispatched_at": NOW, "delivered_at": None},
            "failure": {"code": "message_delivery_failed", "confirmed_recipient_count": 0},
            "items": [{"id": MESSAGE, "timestamps": {"delivered_at": None}}],
            "empty_items": [], "next_page_token": None,
            "delivery_confirmed": False, "scanned_count": 0, "fraction": 0.5, "status": "dispatched",
        }
        for name, value in values.items():
            with self.subTest(name=name):
                emitted = tool.create_variable_message(name, value)
                restored = ToolInvokeMessage.model_validate_json(emitted.model_dump_json())
                self.assertEqual(restored.type.value, "variable")
                self.assertEqual(restored.message.variable_name, name)
                self.assertEqual(restored.message.variable_value, value)
                self.assertFalse(restored.message.stream)

    def test_send_variables_and_json_share_the_same_redacted_result(self):
        self.queue(message(text="Echo " + KEY), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "text": "Echo " + KEY, "idempotency_key": KEY})
        self.assertEqual(result["text"], "Echo [REDACTED]")
        self.assertEqual(result["idempotency_key"], "[REDACTED]")

    def query(self):
        return parse_qs(urlparse(self.calls[-1].url).query)

    def test_sdk_registers_exactly_the_five_tools_and_secret_credentials(self):
        self.assertEqual(set(self.mapping), {"send_message", "list_spaces", "list_messages", "get_message", "get_attachment"})
        with open("provider/photon.yaml") as stream:
            provider = yaml.safe_load(stream)
        self.assertEqual(provider["credentials_for_provider"]["api_key"]["type"], "secret-input")
        origin = provider["credentials_for_provider"]["api_origin"]
        self.assertEqual(origin["type"], "select")
        self.assertEqual(origin["default"], "https://api.photon.codes")
        self.assertEqual([option["value"] for option in origin["options"]], ["https://api.photon.codes", "https://api.staging.photon.codes"])
        for definition, _ in self.mapping.values():
            self.assertFalse({"api_key", "project_id", "api_origin", "base_url"} & {p.name for p in definition.parameters})

    def test_omitted_origin_defaults_to_production(self):
        self.assertEqual(PhotonClient(CREDENTIALS).origin, "https://api.photon.codes")

    def test_both_origins_route_provider_validation_and_every_tool(self):
        for origin in ["https://api.photon.codes", "https://api.staging.photon.codes"]:
            with self.subTest(origin=origin):
                self.expected_origin = origin
                credentials = {**CREDENTIALS, "api_origin": origin}
                before = len(self.calls)
                self.queue({"items": []})
                PhotonProvider().validate_credentials(credentials)
                self.queue({"items": [chat()]})
                self.invoke("list_spaces", {}, credentials=credentials)
                self.queue({"items": [message()]})
                self.invoke("list_messages", {}, credentials=credentials)
                self.queue(message("delivered"))
                self.invoke("get_message", {"message_id": MESSAGE}, credentials=credentials)
                self.queue(message(text="Synthetic origin selection."), status=202)
                sent = self.invoke("send_message", {"space_id": SPACE, "text": "Synthetic origin selection."}, credentials=credentials)
                self.assertEqual(sent["status"], "dispatched")
                self.queue(attachment())
                self.queue(PNG, content_type="image/png")
                self.invoke("get_attachment", {"attachment_id": ATTACHMENT}, credentials=credentials)
                self.assertEqual(len(self.calls), before + 7)
                for request in self.calls[before:]:
                    self.assertTrue(request.url.startswith(origin + f"/v1/projects/{PROJECT}/"))

    def test_origins_outside_the_exact_allowlist_are_rejected_before_http(self):
        invalid = [
            None, "", "production", "staging", False, 0, [], {},
            "http://api.photon.codes", "https://api.photon.codes/", "https://api.staging.photon.codes/",
            "https://api.staging.photon.codes/v1", "https://api.photon.codes?x=1",
            "https://api.staging.photon.codes#fragment", "https://api.photon.codes:443",
            "https://api.staging.photon.codes.evil.test", "https://api.photon.codes@evil.test",
            "https://" + KEY + "@api.staging.photon.codes", "https://api.photon.codes\\@evil.test",
            "https://API.PHOTON.CODES", " https://api.photon.codes", "https://api.staging.photon.codes\n",
        ]
        for origin in invalid:
            with self.subTest(origin_type=type(origin).__name__):
                credentials = {**CREDENTIALS, "api_origin": origin}
                with self.assertRaises(PhotonError) as caught:
                    PhotonClient(credentials)
                self.assertIn("api_origin must be exactly", str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))
                with self.assertRaises(ToolProviderCredentialValidationError):
                    PhotonProvider().validate_credentials(credentials)
                with self.assertRaises(PhotonError):
                    self.invoke("list_spaces", {}, credentials=credentials)
        self.assertEqual(self.calls, [])

    def test_staging_auth_errors_are_safe_and_do_not_fall_back_to_production(self):
        self.expected_origin = "https://api.staging.photon.codes"
        self.queue({"code": "NOT_AUTHENTICATED", "detail": KEY}, status=401, content_type="application/problem+json")
        with self.assertRaises(ToolProviderCredentialValidationError) as caught:
            PhotonProvider().validate_credentials({**CREDENTIALS, "api_origin": self.expected_origin})
        self.assertIn("selected Photon environment", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(len(self.calls), 1)

    def test_provider_validation_accepts_empty_authenticated_page(self):
        self.queue({"items": []})
        PhotonProvider().validate_credentials(CREDENTIALS)
        self.assertEqual(self.query(), {"pageSize": ["1"]})
        self.assertEqual(len(self.calls), 1)

    def test_provider_rejects_invalid_credentials_before_http(self):
        for name, value in [("api_key", "bad"), ("api_key", KEY + "\r\nheader: value"), ("project_id", "pho_prj_bad"), ("default_sender_id", "pho_res_00000000000000000000000001")]:
            with self.subTest(name=name, value_kind=type(value).__name__):
                with self.assertRaises(ToolProviderCredentialValidationError) as caught:
                    PhotonProvider().validate_credentials({**CREDENTIALS, name: value})
                self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_provider_auth_error_is_actionable_without_echoed_secret(self):
        self.queue({"code": "NOT_AUTHENTICATED", "detail": KEY, "title": "Authorization: Bearer " + KEY}, status=401, content_type="application/problem+json; charset=utf-8")
        with self.assertRaises(ToolProviderCredentialValidationError) as caught:
            PhotonProvider().validate_credentials(CREDENTIALS)
        self.assertIn("NOT_AUTHENTICATED", str(caught.exception))
        self.assertIn("API key", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))

    def test_send_202_default_sender_and_generated_uuid(self):
        self.queue(message(), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "text": "Hello from local acceptance."})
        body = json.loads(self.calls[0].body)
        self.assertEqual(body, {"spaceId": SPACE, "senderId": SENDER, "content": {"type": "text", "format": "plain", "text": "Hello from local acceptance."}})
        self.assertEqual(UUID(result["idempotency_key"]).version, 4)
        self.assertEqual(self.calls[0].headers["Idempotency-Key"], result["idempotency_key"])
        self.assertEqual(result["id"], MESSAGE)
        self.assertEqual(result["space_id"], SPACE)
        self.assertEqual(result["status"], "dispatched")
        self.assertIs(result["delivery_confirmed"], False)
        self.assertEqual(result["timestamps"]["dispatched_at"], NOW)
        self.assertIsNone(result["timestamps"]["delivered_at"])
        self.assertEqual(len(self.calls), 1)

    def test_explicit_sender_parent_and_idempotency_preserve_text(self):
        text = "  Keep whitespace\nand punctuation.  "
        self.queue(message(text=text), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "text": text, "sender_id": OTHER_SENDER, "parent_message_id": MESSAGE, "idempotency_key": "manual-retry-1"})
        body = json.loads(self.calls[0].body)
        self.assertEqual(body["senderId"], OTHER_SENDER)
        self.assertEqual(body["parentMessageId"], MESSAGE)
        self.assertEqual(body["content"]["text"], text)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["idempotency_key"], "manual-retry-1")

    def test_send_validation_prevents_http(self):
        invalid = [
            {"space_id": "https://other.test"}, {"space_id": SPACE + "/../messages"},
            {"sender_id": "pho_usr_bad"}, {"sender_id": 0}, {"parent_message_id": "pho_msg_bad"},
            {"text": ""}, {"text": " \n\t"}, {"text": "x" * (MAX_TEXT_LENGTH + 1)}, {"text": 17},
            {"idempotency_key": "with space"}, {"idempotency_key": "x" * 256}, {"idempotency_key": "bad\r\nheader"},
        ]
        for update in invalid:
            with self.subTest(field=list(update)):
                with self.assertRaises(PhotonError):
                    self.invoke("send_message", {"space_id": SPACE, "text": "valid", **update})
        self.assertEqual(self.calls, [])

    def test_missing_sender_is_actionable_before_http(self):
        with self.assertRaisesRegex(PhotonError, "Provide sender_id or configure default_sender_id"):
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"}, credentials={"api_key": KEY, "project_id": PROJECT})
        self.assertEqual(self.calls, [])

    def test_maximum_text_length_and_idempotency_length_are_accepted(self):
        self.queue(message(text="x" * MAX_TEXT_LENGTH), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "text": "x" * MAX_TEXT_LENGTH, "idempotency_key": "x" * 255})
        self.assertEqual(len(result["text"]), MAX_TEXT_LENGTH)
        self.assertEqual(len(self.calls[0].headers["Idempotency-Key"]), 255)

    def test_no_retry_after_timeout_connection_error_or_rate_limit(self):
        for failure in [requests.Timeout("Bearer " + KEY), requests.ConnectionError(KEY)]:
            with self.subTest(failure=type(failure).__name__):
                self.responses.append(failure)
                before = len(self.calls)
                with self.assertRaises(PhotonError) as caught:
                    self.invoke("send_message", {"space_id": SPACE, "text": "valid", "idempotency_key": "stable-key"})
                self.assertNotIn(KEY, str(caught.exception))
                self.assertIn("same idempotency", str(caught.exception))
                self.assertEqual(len(self.calls), before + 1)
        self.queue({"code": "RATE_LIMITED", "detail": KEY}, status=429, content_type="application/problem+json", headers={"Retry-After": "1"})
        before = len(self.calls)
        with self.assertRaisesRegex(PhotonError, "429"):
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"})
        self.assertEqual(len(self.calls), before + 1)

    def test_redirects_are_not_followed(self):
        self.queue({}, status=307, headers={"Location": "https://other.test/capture"})
        with self.assertRaisesRegex(PhotonError, "307"):
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"})
        self.assertEqual(len(self.calls), 1)

    def test_send_requires_202_not_200(self):
        self.queue(message(), status=200)
        with self.assertRaisesRegex(PhotonError, "HTTP 200"):
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"})

    def test_list_spaces_filters_cap_and_opaque_cursor(self):
        self.queue({"items": [chat()], "nextPageToken": CURSOR})
        result = self.invoke("list_spaces", {"platform": "imessage", "page_size": 999, "participant_handle": "+14155550123", "order": "asc", "page_token": CURSOR})
        self.assertEqual(self.query(), {"platform": ["imessage"], "pageSize": ["100"], "order": ["asc"], "participantHandle": ["+14155550123"], "pageToken": [CURSOR]})
        self.assertEqual(result["items"][0]["participant_ids"], [SENDER, OTHER_SENDER])
        self.assertEqual(result["next_page_token"], CURSOR)

    def test_list_spaces_defaults_and_last_page(self):
        self.queue({"items": []})
        self.assertEqual(self.invoke("list_spaces", {}), {"items": [], "next_page_token": None})
        self.assertEqual(self.query(), {"pageSize": ["20"], "order": ["desc"]})

    def test_list_input_validation_prevents_http(self):
        for update in [{"page_size": 0}, {"page_size": -1}, {"page_size": True}, {"page_size": 1.5}, {"page_size": float("inf")}, {"page_size": "invalid"}, {"page_token": "not-a-cursor"}, {"page_token": "a." + "b" * 4096}, {"participant_handle": "x" * 321}, {"order": "sideways"}, {"platform": "voice"}]:
            with self.subTest(field=list(update)):
                with self.assertRaises(PhotonError):
                    self.invoke("list_spaces", update)
        self.assertEqual(self.calls, [])

    def test_message_direction_time_and_local_space_filter_match_api(self):
        self.queue({"items": [message(), message(space=OTHER_SPACE)], "nextPageToken": CURSOR})
        result = self.invoke("list_messages", {"space_id": SPACE, "platform": "imessage", "direction": "sent", "created_since": "2026-10-18T00:00:00Z", "created_before": "2026-10-19T00:00:00+00:00"})
        self.assertEqual(self.query(), {"platform": ["imessage"], "pageSize": ["20"], "order": ["desc"], "direction": ["sent"], "createdSince": ["2026-10-18T00:00:00Z"], "createdBefore": ["2026-10-19T00:00:00+00:00"]})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["space_id"], SPACE)
        self.assertEqual(result["scanned_count"], 2)
        self.assertTrue(result["space_filter_applied_locally"])
        self.assertEqual(result["next_page_token"], CURSOR)

    def test_filtered_empty_page_retains_next_token(self):
        self.queue({"items": [message(space=OTHER_SPACE)], "nextPageToken": CURSOR})
        result = self.invoke("list_messages", {"space_id": SPACE})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["next_page_token"], CURSOR)
        self.queue({"items": [message()]})
        result = self.invoke("list_messages", {"space_id": SPACE, "page_token": CURSOR})
        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["next_page_token"])

    def test_received_direction_and_non_text_content(self):
        data = message("received")
        data["content"] = {"type": "message.read", "messageId": MESSAGE}
        self.queue({"items": [data]})
        result = self.invoke("list_messages", {"direction": "received"})
        self.assertEqual(self.query()["direction"], ["received"])
        self.assertEqual(result["items"][0]["direction"], "received")
        self.assertIsNone(result["items"][0]["text"])
        self.assertFalse(result["space_filter_applied_locally"])

    def test_message_filters_validate_before_http(self):
        for parameters in [
            {"space_id": "pho_spc_bad"}, {"direction": "dispatched"}, {"order": "newest"}, {"page_size": 0}, {"platform": "whatsapp_personal"}, {"created_since": "yesterday"},
            {"created_since": "2026-10-19T00:00:00"}, {"created_since": "2026-02-30T00:00:00Z"},
            {"created_since": "2026-10-19T00:00:00+00:99"},
            {"created_since": "2026-10-20T00:00:00Z", "created_before": "2026-10-19T00:00:00Z"},
        ]:
            with self.subTest(parameters=parameters):
                with self.assertRaises(PhotonError):
                    self.invoke("list_messages", parameters)
        self.assertEqual(self.calls, [])

    def test_every_status_has_stable_delivery_semantics(self):
        for status in ["received", "dispatched", "accepted", "delivered", "failed"]:
            with self.subTest(status=status):
                self.queue(message(status))
                result = self.invoke("get_message", {"message_id": FAILED_MESSAGE if status == "failed" else MESSAGE})
                self.assertEqual(result["status"], status)
                self.assertEqual(result["delivery_confirmed"], status == "delivered")
                self.assertEqual(set(result["timestamps"]), {"created_at", "updated_at", "received_at", "dispatched_at", "accepted_at", "delivered_at", "failed_at"})
                if status == "failed":
                    self.assertEqual(result["failure"]["code"], "message_delivery_failed")
                    self.assertEqual(result["failure"]["confirmed_recipient_count"], 0)

    def test_status_id_validation_prevents_http(self):
        with self.assertRaises(PhotonError):
            self.invoke("get_message", {"message_id": "pho_msg_bad"})
        self.assertEqual(self.calls, [])

    def test_secret_echoes_are_redacted_from_all_json_output(self):
        data = message("failed", text="An accidental key " + KEY)
        data["failure"]["message"] = "Echo " + KEY
        self.queue(data)
        result = self.invoke("get_message", {"message_id": FAILED_MESSAGE})
        self.assertNotIn(KEY, json.dumps(result))
        self.assertIn("[REDACTED]", result["text"])
        self.assertIn("[REDACTED]", result["failure"]["message"])

    def test_malformed_json_and_pages_have_safe_errors(self):
        for data in [b"<html>" + KEY.encode(), [], {"unexpected": KEY}]:
            with self.subTest(kind=type(data).__name__):
                self.queue(data)
                with self.assertRaises(PhotonError) as caught:
                    self.invoke("list_spaces", {})
                self.assertNotIn(KEY, str(caught.exception))

    def test_error_body_variants_are_never_exposed(self):
        for code, data, content_type in [(500, {"detail": KEY, "code": KEY}, "application/problem+json"), (403, b"raw secret " + KEY.encode(), "text/plain"), (404, b"invalid json " + KEY.encode(), "application/problem+json")]:
            self.queue(data, status=code, content_type=content_type)
            with self.assertRaises(PhotonError) as caught:
                self.invoke("list_spaces", {})
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn(KEY, str(caught.exception))

    def test_platform_filter_reaches_both_list_tools_and_results_name_their_platform(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                self.queue({"items": [chat(platform=platform)]})
                chats = self.invoke("list_spaces", {"platform": platform})
                self.assertEqual(self.query()["platform"], [platform])
                self.assertEqual(chats["items"][0]["platform"], platform)
                self.queue({"items": [message(platform=platform)]})
                messages = self.invoke("list_messages", {"platform": platform})
                self.assertEqual(self.query()["platform"], [platform])
                self.assertEqual(messages["items"][0]["platform"], platform)

    def test_omitted_platform_lists_every_channel(self):
        self.queue({"items": [chat(platform=platform) for platform in PLATFORMS]})
        result = self.invoke("list_spaces", {})
        self.assertNotIn("platform", self.query())
        self.assertEqual([item["platform"] for item in result["items"]], list(PLATFORMS))

    def test_invalid_platforms_are_rejected_before_http(self):
        for value in ["voice", "iMessage", "whatsapp_personal", "all", " sms", 0, True, ["sms"], {"sms": 1}]:
            with self.subTest(value_type=type(value).__name__, value=str(value)):
                for name in ["list_spaces", "list_messages"]:
                    with self.assertRaisesRegex(PhotonError, "platform must be one of"):
                        self.invoke(name, {"platform": value})
        self.assertEqual(self.calls, [])

    def test_send_and_status_report_the_space_platform(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                self.queue(message(platform=platform), status=202)
                self.assertEqual(self.invoke("send_message", {"space_id": SPACE, "text": "Synthetic channel send."})["platform"], platform)
                self.queue(message("delivered", platform=platform))
                self.assertEqual(self.invoke("get_message", {"message_id": MESSAGE})["platform"], platform)

    def test_message_without_platform_is_rejected(self):
        data = message()
        del data["platform"]
        self.queue(data)
        with self.assertRaisesRegex(PhotonError, "incomplete message"):
            self.invoke("get_message", {"message_id": MESSAGE})

    def test_email_subject_is_sent_as_email_options(self):
        subject = "Order 1042 update"
        self.queue(message(platform="email"), status=202)
        self.invoke("send_message", {"space_id": SPACE, "text": "Your order shipped.", "email_subject": subject})
        self.assertEqual(json.loads(self.calls[0].body)["email"], {"subject": subject})
        self.queue(message(platform="email"), status=202)
        self.invoke("send_message", {"space_id": SPACE, "text": "Your order shipped.", "email_subject": "x" * MAX_EMAIL_SUBJECT_LENGTH})
        self.assertEqual(len(json.loads(self.calls[1].body)["email"]["subject"]), MAX_EMAIL_SUBJECT_LENGTH)
        self.queue(message(), status=202)
        self.invoke("send_message", {"space_id": SPACE, "text": "No subject.", "email_subject": ""})
        self.assertNotIn("email", json.loads(self.calls[2].body))

    def test_invalid_email_subject_prevents_http(self):
        for value in [" \n\t", "x" * (MAX_EMAIL_SUBJECT_LENGTH + 1), 17, ["subject"]]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(PhotonError, "email_subject must be"):
                    self.invoke("send_message", {"space_id": SPACE, "text": "valid", "email_subject": value})
        self.assertEqual(self.calls, [])

    def test_channel_send_errors_have_specific_safe_hints(self):
        cases = [
            (409, "SMS_CAMPAIGN_NOT_ELIGIBLE", "campaign eligibility"),
            (403, "SHARED_LINE_INBOUND_REQUIRED", "messaged it"),
            (403, "SHARED_LINE_NOT_ASSIGNED", "no active assignment"),
            (422, "SHARED_LINE_GROUP_UNSUPPORTED", "direct spaces"),
            (409, "SPACE_NOT_SENDABLE", "does not support replies"),
            (409, "SENDER_NOT_SENDABLE", "same channel"),
            (404, "SENDER_NOT_FOUND", "same channel"),
            (422, "MESSAGE_TOO_LONG", "shorter messages"),
            (422, "IDEMPOTENCY_KEY_REUSED", "different send body"),
            (402, "BILLING_SUSPENDED", "billing"),
            (422, "UNSUPPORTED_CONTENT", "some take no attachments"),
        ]
        for status, code, hint in cases:
            with self.subTest(code=code):
                self.queue({"code": code, "detail": KEY, "title": KEY}, status=status, content_type="application/problem+json")
                with self.assertRaises(PhotonError) as caught:
                    self.invoke("send_message", {"space_id": SPACE, "text": "valid"})
                self.assertIn(f"HTTP {status} ({code})", str(caught.exception))
                self.assertIn(hint, str(caught.exception))
                self.assertNotIn(KEY, str(caught.exception))

    def test_unknown_error_codes_fall_back_to_status_hints(self):
        self.queue({"code": "SOMETHING_NEW", "detail": KEY}, status=409, content_type="application/problem+json")
        with self.assertRaises(PhotonError) as caught:
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"})
        self.assertNotIn("SOMETHING_NEW", str(caught.exception))
        self.assertIn("channel setup", str(caught.exception))

    def test_list_tool_platform_options_match_client_platforms(self):
        for name in ["list_spaces", "list_messages"]:
            with self.subTest(tool=name):
                with open(f"tools/{name}.yaml") as stream:
                    parameters = {item["name"]: item for item in yaml.safe_load(stream)["parameters"]}
                self.assertEqual([option["value"] for option in parameters["platform"]["options"]], list(PLATFORMS))
                self.assertFalse(parameters["platform"]["required"])
                self.assertNotIn("default", parameters["platform"])

    def test_message_outputs_follow_photon_content_types(self):
        cases = [
            ({"type": "text", "format": "plain", "text": "Hi"}, "Hi", [], {"type": "text", "format": "plain", "text": "Hi"}),
            ({"type": "attachment", "attachmentId": ATTACHMENT}, None, [ATTACHMENT], {"type": "attachment", "attachment_id": ATTACHMENT}),
            ({"type": "group", "parts": [{"type": "attachment", "attachmentId": ATTACHMENT}, {"type": "attachment", "attachmentId": OTHER_ATTACHMENT}, {"type": "text", "format": "plain", "text": "Two photos"}]},
             "Two photos", [ATTACHMENT, OTHER_ATTACHMENT],
             {"type": "group", "parts": [{"type": "attachment", "attachment_id": ATTACHMENT}, {"type": "attachment", "attachment_id": OTHER_ATTACHMENT}, {"type": "text", "format": "plain", "text": "Two photos"}]}),
            ({"type": "reaction", "reaction": "\U0001F44D", "action": "add"}, None, [], {"type": "reaction", "reaction": "\U0001F44D", "action": "add"}),
        ]
        for content, text, attachment_ids, normalized in cases:
            with self.subTest(content_type=content["type"]):
                data = message("received", platform="sms", content=content)
                data["parentMessageId"] = MESSAGE
                self.queue(data)
                result = self.invoke("get_message", {"message_id": MESSAGE})
                self.assertEqual((result["type"], result["text"], result["attachment_ids"], result["content"], result["parent_message_id"], result["direction"]),
                                 (content["type"], text, attachment_ids, normalized, MESSAGE, "received"))

    def test_send_single_image_uploads_then_sends_one_attachment(self):
        self.queue(attachment(), status=201)
        self.queue(message(content={"type": "attachment", "attachmentId": ATTACHMENT}), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image()], "idempotency_key": "photo-1"})
        upload, send = self.calls
        upload_key = hashlib.sha256(b"photo-1").hexdigest() + ".attachment.0"
        boundary = "photon-" + hashlib.sha256(upload_key.encode()).hexdigest()[:32]
        self.assertTrue(upload.url.endswith(f"/v1/projects/{PROJECT}/attachments"))
        self.assertEqual(upload.headers["Content-Type"], f"multipart/related; boundary={boundary}")
        self.assertEqual(upload.headers["Idempotency-Key"], upload_key)
        declaration = json.dumps({"contentType": "image/png", "sizeBytes": len(PNG), "filename": "photo.png"})
        self.assertEqual(upload.body, f"--{boundary}\r\ncontent-type: application/json\r\n\r\n{declaration}\r\n--{boundary}\r\ncontent-type: image/png\r\n\r\n".encode() + PNG + f"\r\n--{boundary}--\r\n".encode())
        self.assertEqual(json.loads(send.body)["content"], {"type": "attachment", "attachmentId": ATTACHMENT})
        self.assertEqual(send.headers["Idempotency-Key"], "photo-1")
        self.assertEqual((result["type"], result["attachment_ids"]), ("attachment", [ATTACHMENT]))
        self.assertEqual(self.downloads, ["https://dify.example/files/photo.png"])

    def test_send_images_with_text_become_one_group_message(self):
        self.queue(attachment(), status=201)
        self.queue(attachment(OTHER_ATTACHMENT, filename="second.png"), status=201)
        group = {"type": "group", "parts": [{"type": "attachment", "attachmentId": ATTACHMENT}, {"type": "attachment", "attachmentId": OTHER_ATTACHMENT}, {"type": "text", "format": "plain", "text": "Two photos"}]}
        self.queue(message(platform="sms", content=group), status=202)
        result = self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image(), image("second.png")], "text": "Two photos", "idempotency_key": "album-1"})
        self.assertEqual([call.headers["Idempotency-Key"] for call in self.calls[:2]], [hashlib.sha256(b"album-1").hexdigest() + f".attachment.{index}" for index in range(2)])
        self.assertEqual(json.loads(self.calls[2].body)["content"], group)
        self.assertEqual((result["type"], result["text"], result["attachment_ids"]), ("group", "Two photos", [ATTACHMENT, OTHER_ATTACHMENT]))

    def test_send_retry_with_the_same_key_repeats_identical_uploads(self):
        bodies = []
        for _ in range(2):
            self.queue(attachment(), status=200)
            self.queue(message(content={"type": "attachment", "attachmentId": ATTACHMENT}), status=202)
            self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image()], "idempotency_key": "retry-1"})
            bodies.append([(call.headers["Idempotency-Key"], call.body) for call in self.calls[-2:]])
        self.assertEqual(bodies[0], bodies[1])

    def test_send_type_and_attachment_rules_prevent_http(self):
        cases = [
            ({"type": "voice", "text": "valid"}, "type must be one of text, attachment"),
            ({"type": "text", "text": ""}, "type text requires text"),
            ({"type": "text", "text": "valid", "attachments": [image()]}, "does not take attachments"),
            ({"type": "attachment"}, "requires at least one image"),
            ({"type": "attachment", "attachments": [image("report.pdf", "application/pdf")]}, "must be JPEG, PNG, GIF, or WebP images"),
            ({"type": "attachment", "attachments": [image(), image("logo.svg", "image/svg+xml")]}, "must be JPEG, PNG, GIF, or WebP images"),
            ({"type": "attachment", "attachments": [image()], "text": " \n"}, "cannot be blank"),
        ]
        for update, error in cases:
            with self.subTest(update=str(update)[:60]):
                with self.assertRaisesRegex(PhotonError, error):
                    self.invoke("send_message", {"space_id": SPACE, **update})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.downloads, [])

    def test_send_accepts_each_supported_image_type(self):
        names = {"image/jpeg": "photo.jpg", "image/png": "photo.png", "image/gif": "photo.gif", "image/webp": "photo.webp"}
        for mime in IMAGE_TYPES:
            with self.subTest(mime=mime):
                self.queue(attachment(content_type=mime, filename=names[mime]), status=201)
                self.queue(message(content={"type": "attachment", "attachmentId": ATTACHMENT}), status=202)
                self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image(names[mime], mime)]})
                self.assertIn(f"content-type: {mime}\r\n\r\n".encode(), self.calls[-2].body)

    def test_images_over_10_mb_are_rejected_before_any_upload(self):
        self.download_bodies["https://dify.example/files/large.png"] = bytes(MAX_IMAGE_BYTES + 1)
        with self.assertRaisesRegex(PhotonError, "at most 10 MB"):
            self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image(), image("large.png")]})
        self.assertEqual(self.calls, [])
        self.download_bodies["https://dify.example/files/largest.png"] = bytes(MAX_IMAGE_BYTES)
        self.queue(attachment(filename="largest.png", size=MAX_IMAGE_BYTES), status=201)
        self.queue(message(content={"type": "attachment", "attachmentId": ATTACHMENT}), status=202)
        self.invoke("send_message", {"space_id": SPACE, "type": "attachment", "attachments": [image("largest.png")]})
        self.assertIn(f'"sizeBytes": {MAX_IMAGE_BYTES}'.encode(), self.calls[0].body)

    def test_get_attachment_returns_metadata_and_the_file(self):
        self.queue(attachment())
        self.queue(PNG, content_type="image/png")
        result = self.invoke("get_attachment", {"attachment_id": ATTACHMENT})
        self.assertEqual(result, {"id": ATTACHMENT, "filename": "photo.png", "content_type": "image/png", "size_bytes": len(PNG), "created_at": NOW})
        metadata, content = self.calls
        self.assertTrue(metadata.url.endswith(f"/attachments/{ATTACHMENT}"))
        self.assertTrue(content.url.endswith(f"/attachments/{ATTACHMENT}/content"))
        self.assertEqual(content.headers["Accept"], "*/*")
        self.assertEqual(len(self.blobs), 1)
        self.assertEqual(self.blobs[0].message.blob, PNG)
        self.assertEqual(self.blobs[0].meta, {"mime_type": "image/png", "filename": "photo.png"})

    def test_get_attachment_stops_reading_past_dify_file_limit(self):
        self.queue(attachment(size=MAX_ATTACHMENT_BYTES + 1))
        self.queue(bytes(MAX_ATTACHMENT_BYTES + 1), content_type="image/png")
        with self.assertRaisesRegex(PhotonError, "larger than 50 MB"):
            self.invoke("get_attachment", {"attachment_id": ATTACHMENT})

    def test_failed_send_reports_only_a_generated_idempotency_key(self):
        self.responses.append(requests.Timeout())
        with self.assertRaises(PhotonError) as caught:
            self.invoke("send_message", {"space_id": SPACE, "text": "valid"})
        generated = self.calls[-1].headers["Idempotency-Key"]
        self.assertIn(f"Generated idempotency_key: {generated}", str(caught.exception))
        self.assertEqual(UUID(generated).version, 4)
        self.responses.append(requests.Timeout())
        with self.assertRaises(PhotonError) as caught:
            self.invoke("send_message", {"space_id": SPACE, "text": "valid", "idempotency_key": "stable-key"})
        self.assertNotIn("Generated idempotency_key", str(caught.exception))
        with self.assertRaises(PhotonError) as caught:
            self.invoke("send_message", {"space_id": SPACE, "text": ""})
        self.assertNotIn("Generated idempotency_key", str(caught.exception))

    def test_get_attachment_rejects_bad_ids_and_explains_not_ready(self):
        with self.assertRaisesRegex(PhotonError, "attachment_id must be a Photon ID"):
            self.invoke("get_attachment", {"attachment_id": "pho_att_bad"})
        self.assertEqual(self.calls, [])
        self.queue(attachment())
        self.queue({"code": "ATTACHMENT_NOT_READY", "detail": KEY}, status=409, content_type="application/problem+json", headers={"Retry-After": "5"})
        with self.assertRaises(PhotonError) as caught:
            self.invoke("get_attachment", {"attachment_id": ATTACHMENT})
        self.assertIn("HTTP 409 (ATTACHMENT_NOT_READY)", str(caught.exception))
        self.assertIn("still processing", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.queue({"code": "INVALID_ATTACHMENT_REQUEST", "detail": KEY}, status=400, content_type="application/problem+json")
        with self.assertRaises(PhotonError) as caught:
            self.invoke("get_attachment", {"attachment_id": ATTACHMENT})
        self.assertIn("HTTP 400 (INVALID_ATTACHMENT_REQUEST)", str(caught.exception))
        self.assertIn("check the attachment ID", str(caught.exception))

    def test_list_messages_uses_api_direction_order_and_page_cap(self):
        for direction in ["received", "sent"]:
            with self.subTest(direction=direction):
                self.queue({"items": []})
                self.invoke("list_messages", {"direction": direction, "order": "asc", "page_size": 999})
                self.assertEqual(self.query(), {"pageSize": ["200"], "order": ["asc"], "direction": [direction]})

    def test_client_rejects_arbitrary_paths_before_http(self):
        for method, path in [("GET", "https://other.test"), ("POST", "/spaces"), ("GET", "/messages/../../account"), ("POST", "/attachments/" + ATTACHMENT), ("GET", "/attachments/pho_att_bad"), ("DELETE", "/attachments/" + ATTACHMENT)]:
            with self.assertRaises(PhotonError):
                PhotonClient(CREDENTIALS).request(method, path)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
