import dify_plugin  # Initialize the SDK before HTTP imports.

import os
import unittest

from fixtures import ATTACHMENT, attachment, chat, message
from provider.client import PLATFORMS

SCHEMA_PREFIX = {"imessage": "Imessage", "sms": "Sms", "whatsapp": "Whatsapp", "whatsapp_business": "WhatsappBusiness", "email": "Email", "telegram": "Telegram"}


@unittest.skipUnless(os.environ.get("PHOTON_OPENAPI"), "Set PHOTON_OPENAPI and install jsonschema to run source-contract acceptance")
class OfficialContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from openapi_contract import OpenAPIContract
        cls.contract = OpenAPIContract()

    def test_every_fixture_status_matches_each_official_platform_schema(self):
        for platform in PLATFORMS:
            for status in ["received", "dispatched", "accepted", "delivered", "failed"]:
                with self.subTest(platform=platform, status=status):
                    self.contract.validate(message(status, platform=platform), {"$ref": f"#/components/schemas/{SCHEMA_PREFIX[platform]}Message"})

    def test_chat_fixture_matches_each_official_platform_schema(self):
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                self.contract.validate(chat(platform=platform), {"$ref": f"#/components/schemas/{SCHEMA_PREFIX[platform]}Space"})

    def test_attachment_and_group_fixtures_match_each_official_platform_schema(self):
        contents = [
            {"type": "attachment", "attachmentId": ATTACHMENT},
            {"type": "group", "parts": [{"type": "attachment", "attachmentId": ATTACHMENT}, {"type": "text", "format": "plain", "text": "Caption"}]},
        ]
        for platform in PLATFORMS:
            for content in contents:
                with self.subTest(platform=platform, content=content["type"]):
                    self.contract.validate(message(platform=platform, content=content), {"$ref": f"#/components/schemas/{SCHEMA_PREFIX[platform]}Message"})

    def test_attachment_fixture_matches_official_schema(self):
        self.contract.validate(attachment(), {"$ref": "#/components/schemas/Attachment"})

    def test_tool_platforms_match_official_platform_enum(self):
        self.assertEqual(set(PLATFORMS), set(self.contract.spec["components"]["schemas"]["Platform"]["enum"]))

    def test_tool_direction_uses_actual_api_enum(self):
        self.assertEqual(self.contract.spec["components"]["schemas"]["MessageDirection"]["enum"], ["received", "sent"])
