"""HTTP /invoke -> SDK router -> tools -> mocked HTTPS -> JSON stream."""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx
from fixtures import CREDENTIALS, CURSOR, FAILED_MESSAGE, KEY, MESSAGE, MISSING_MESSAGE, SPACE


class SDKProcessTests(unittest.TestCase):
    def test_real_entrypoint_credentials_and_tools_over_sdk_http(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {
            **os.environ,
            "INSTALL_METHOD": "serverless",
            "SERVERLESS_HOST": "127.0.0.1",
            "SERVERLESS_PORT": str(port),
            "PYTHONUNBUFFERED": "1",
        }
        runner = Path(__file__).with_name("sdk_fixture_runner.py")
        process = subprocess.Popen(
            [sys.executable, str(runner)],
            cwd=Path.cwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        session = httpx.Client(trust_env=False)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail("SDK fixture process exited before serving")
                try:
                    if session.get(base + "/health", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                self.fail("SDK fixture process did not become healthy")

            def invoke(tool=None, parameters=None, credentials=None):
                data = {
                    "type": "tool",
                    "action": "invoke_tool" if tool else "validate_tool_credentials",
                    "user_id": "local-test",
                    "provider": "photon",
                    "credentials": credentials or CREDENTIALS,
                }
                if tool:
                    data.update(tool=tool, tool_parameters=parameters or {})
                response = session.post(
                    base + "/invoke",
                    json={"session_id": str(uuid4()), "event": "request", "data": data},
                    timeout=5,
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(KEY, response.text)
                return [json.loads(line) for line in response.text.splitlines() if line.strip()]

            def payload(events):
                stream = [event.get("data", {}).get("data", {}) for event in events]
                messages = [data for data in stream if data.get("type") in ("json", "variable")]
                self.assertTrue(messages, "Missing tool output in SDK stream")
                self.assertEqual(messages[0]["type"], "json")
                result = messages[0]["message"]["json_object"]
                expected = {
                    key: value
                    for key, value in result.items()
                    if key not in {"text", "files", "json"}
                }
                self.assertEqual(
                    [data["type"] for data in messages], ["json"] + ["variable"] * len(expected)
                )
                variables = [data["message"] for data in messages[1:]]
                self.assertEqual([item["variable_name"] for item in variables], list(expected))
                self.assertEqual(
                    {item["variable_name"]: item["variable_value"] for item in variables}, expected
                )
                self.assertFalse(
                    {"text", "files", "json"} & {item["variable_name"] for item in variables}
                )
                return result

            events = invoke()
            self.assertTrue(
                any(
                    event.get("data", {}).get("data", {}).get("result") is True for event in events
                ),
                json.dumps(events),
            )
            chats = payload(invoke("list_spaces", {}))
            self.assertEqual(chats["items"][0]["id"], SPACE)
            self.assertEqual(chats["next_page_token"], CURSOR)
            send_parameters = {
                "space_id": SPACE,
                "text": "SDK process test.",
                "idempotency_key": "process-stable-key",
            }
            sent = payload(invoke("send_message", send_parameters))
            self.assertEqual(sent["id"], MESSAGE)
            self.assertEqual(sent["status"], "dispatched")
            self.assertFalse(sent["delivery_confirmed"])
            delivered = payload(invoke("get_message", {"message_id": sent["id"]}))
            self.assertEqual(delivered["status"], "delivered")
            self.assertTrue(delivered["delivery_confirmed"])
            self.assertEqual(delivered["text"], send_parameters["text"])
            self.assertEqual(payload(invoke("send_message", send_parameters))["id"], MESSAGE)
            conflict = invoke("send_message", {**send_parameters, "text": "Changed body"})
            self.assertIn("IDEMPOTENCY_KEY_REUSED", json.dumps(conflict))
            first = payload(
                invoke(
                    "list_messages",
                    {"space_id": SPACE, "platform": "imessage", "direction": "sent"},
                )
            )
            self.assertEqual(first["items"], [])
            self.assertEqual(first["next_page_token"], CURSOR)
            second = payload(
                invoke(
                    "list_messages",
                    {
                        "space_id": SPACE,
                        "platform": "imessage",
                        "direction": "sent",
                        "page_token": first["next_page_token"],
                    },
                )
            )
            self.assertEqual(second["items"][0]["id"], MESSAGE)
            self.assertIsNone(second["next_page_token"])
            failure = payload(invoke("get_message", {"message_id": FAILED_MESSAGE}))
            self.assertEqual(failure["failure"]["code"], "message_delivery_failed")
            self.assertFalse(failure["delivery_confirmed"])
            not_found = invoke("get_message", {"message_id": MISSING_MESSAGE})
            self.assertIn("MESSAGE_NOT_FOUND", json.dumps(not_found))
            invalid = invoke("get_message", {"message_id": "invalid"})
            self.assertIn("VALIDATION_FAILED", json.dumps(invalid))
            invalid_credentials = invoke(credentials={**CREDENTIALS, "api_key": "invalid"})
            self.assertIn("NOT_AUTHENTICATED", json.dumps(invalid_credentials))
        finally:
            session.close()
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            self.assertNotIn(KEY, stdout + stderr, "SDK process logs exposed a fixture credential")
            # SDK 0.10.2 logs safe tracebacks for the four deliberate error calls.
            self.assertNotIn("AssertionError", stderr, "Synthetic HTTP contract check failed")


if __name__ == "__main__":
    unittest.main()
