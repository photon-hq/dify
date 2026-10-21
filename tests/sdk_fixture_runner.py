"""Run the real entrypoint with synthetic Photon transport, for process tests."""

import json
import runpy
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from fixtures import (
    CURSOR,
    FAILED_MESSAGE,
    KEY,
    MESSAGE,
    MISSING_MESSAGE,
    OTHER_SPACE,
    PROJECT,
    chat,
    message,
)

sys.path.insert(0, str(Path.cwd()))
sent = {}


def problem(status, code, **fields):
    return status, "application/problem+json", {"status": status, "code": code, **fields}


def fixture_send(transport, request):
    url = request.url
    assert url.scheme == "https" and url.host == "api.photon.codes"
    query = {name: values[0] for name, values in parse_qs(url.query.decode()).items()}
    prefix = f"/v1/projects/{PROJECT}"
    status, content_type = 200, "application/json"
    if request.headers.get("Authorization") != "Bearer " + KEY:
        status, content_type, data = problem(401, "NOT_AUTHENTICATED", title="Not Authenticated")
    elif request.method == "GET" and url.path == prefix + "/spaces":
        data = {"items": [chat()], "nextPageToken": CURSOR}
    elif request.method == "POST" and url.path == prefix + "/messages":
        key = request.headers["Idempotency-Key"]
        body = json.loads(request.read())
        if key in sent and sent[key] != body:
            status, content_type, data = problem(
                422, "IDEMPOTENCY_KEY_REUSED", title="Idempotency Key Reused"
            )
        else:
            sent[key] = body
            status, data = 202, message(text=body["content"]["text"])
    elif request.method == "GET" and url.path == prefix + "/messages":
        assert (
            query["platform"] == "imessage"
            and query.get("direction") == "sent"
            and "spaceId" not in query
        )
        data = (
            {"items": [message(space=OTHER_SPACE)], "nextPageToken": CURSOR}
            if "pageToken" not in query
            else {"items": [message("delivered")]}
        )
    elif request.method == "GET" and url.path == prefix + "/messages/" + MESSAGE:
        assert sent, "Status lookup should follow a successful synthetic send"
        data = message("delivered", text=next(iter(sent.values()))["content"]["text"])
    elif request.method == "GET" and url.path == prefix + "/messages/" + FAILED_MESSAGE:
        data = message("failed")
    elif request.method == "GET" and url.path == prefix + "/messages/" + MISSING_MESSAGE:
        status, content_type, data = problem(404, "MESSAGE_NOT_FOUND", title="Message Not Found")
    elif request.method == "GET" and url.path == prefix + "/messages/invalid":
        status, content_type, data = problem(
            422,
            "VALIDATION_FAILED",
            issues=[{"message": "value must be a pho_msg_ TypeID", "path": "/messageId"}],
        )
    else:
        raise AssertionError("Unexpected Photon fixture request")
    return httpx.Response(
        status,
        headers={"Content-Type": content_type},
        content=json.dumps(data).encode(),
        request=request,
    )


httpx.HTTPTransport.handle_request = fixture_send
runpy.run_module("main", run_name="__main__")
