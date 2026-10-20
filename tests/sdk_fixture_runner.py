"""Run the real entrypoint with synthetic Photon transport, for process acceptance."""

import dify_plugin  # Initialize the SDK's gevent patch before HTTP imports.

import json
import os
import runpy
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from fixtures import CURSOR, FAILED_MESSAGE, KEY, MESSAGE, MISSING_MESSAGE, OTHER_SPACE, PROJECT, chat, message

sys.path.insert(0, str(Path.cwd()))
contract = None
if os.environ.get("PHOTON_OPENAPI"):
    from openapi_contract import OpenAPIContract
    contract = OpenAPIContract()
sent = {}


def fixture_send(adapter, request, **kwargs):
    parsed = urlparse(request.url)
    assert parsed.scheme == "https" and parsed.netloc == "api.photon.codes"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert kwargs["verify"] is True and kwargs["timeout"] == (5, 15)
    assert kwargs["proxies"] == {} and adapter.max_retries.total == 0
    if contract:
        contract.validate_request(request)
    query = parse_qs(parsed.query)
    status, content_type = 200, "application/json"
    prefix = f"/v1/projects/{PROJECT}"
    if request.method == "GET" and parsed.path == prefix + "/spaces":
        data = {"items": [chat()], "nextPageToken": CURSOR}
    elif request.method == "POST" and parsed.path == prefix + "/messages":
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.body)
        status = 202
        if key in sent and sent[key] != body:
            status, content_type = 422, "application/problem+json"
            data = {"code": "IDEMPOTENCY_KEY_REUSED", "detail": KEY}
        else:
            sent[key] = body
            data = message(text=body["content"]["text"])
    elif request.method == "GET" and parsed.path == prefix + "/messages":
        assert query["platform"] == ["imessage"]
        assert query.get("direction") == ["sent"]
        assert "spaceId" not in query
        data = {"items": [message(space=OTHER_SPACE)], "nextPageToken": CURSOR} if "pageToken" not in query else {"items": [message("delivered")]}
    elif request.method == "GET" and parsed.path == prefix + "/messages/" + MESSAGE:
        assert sent, "Status lookup should follow a successful synthetic send"
        data = message("delivered", text=next(iter(sent.values()))["content"]["text"])
    elif request.method == "GET" and parsed.path == prefix + "/messages/" + FAILED_MESSAGE:
        data = message("failed")
    elif request.method == "GET" and parsed.path == prefix + "/messages/" + MISSING_MESSAGE:
        status, content_type = 404, "application/problem+json"
        data = {"code": "MESSAGE_NOT_FOUND", "title": KEY, "detail": KEY}
    else:
        raise AssertionError("Unexpected Photon fixture request")
    if contract and status in (200, 202):
        schema_name = "SpacePage" if parsed.path.endswith("/spaces") else "MessagePage" if request.method == "GET" and parsed.path.endswith("/messages") else "SentMessage" if request.method == "POST" else "ImessageMessage"
        contract.validate(data, {"$ref": "#/components/schemas/" + schema_name})
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response._content = json.dumps(data).encode()
    response.request = request
    response.url = request.url
    return response


requests.adapters.HTTPAdapter.send = fixture_send
runpy.run_module("main", run_name="__main__")
