"""Synthetic Photon deliveries, Photon responses, and Dify answers; no real credentials or data."""

PROJECT = "pho_prj_00000000000000000000000001"
SPACE = "pho_spc_00000000000000000000000001"
OTHER_SPACE = "pho_spc_00000000000000000000000002"
AGENT = "pho_usr_00000000000000000000000001"
PERSON = "pho_usr_00000000000000000000000002"
MESSAGE = "pho_msg_00000000000000000000000001"
OTHER_MESSAGE = "pho_msg_00000000000000000000000002"
REPLY = "pho_msg_00000000000000000000000003"
APP = "00000000-0000-0000-0000-00000000000a"
OTHER_APP = "00000000-0000-0000-0000-00000000000b"
CONVERSATION = "00000000-0000-0000-0000-0000000000c1"
OTHER_CONVERSATION = "00000000-0000-0000-0000-0000000000c2"
KEY = "pho_" + "sk_" + "synthetic_fixture_only"
SECRET = "whsec_" + "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
NOW = "2026-10-22T00:00:00.000Z"
SETTINGS = {
    "api_key": KEY,
    "signing_secret": SECRET,
    "app": {"app_id": APP, "inputs": {"tone": "brief"}, "files": [], "type": "app-selector"},
}

# Photon's interoperability vector from @photon-hq/contracts (schemas/test-vectors).
VECTOR = {
    "secret": "whsec_BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    "body": '{"synthetic":true,"text":"Hello \U0001f30d"}'.encode(),
    "headers": {
        "webhook-id": "synthetic-vector",
        "webhook-timestamp": "1767225600",
        "webhook-signature": "v1,0urZDpPAiQuH0H0rEB2NpIzgZKIhN6z++ZQqVUiN8e8=",
    },
    "now": 1767225600,
}


def user(user_id, kind, handle):
    return {
        "id": user_id,
        "projectId": PROJECT,
        "platform": "telegram",
        "kind": kind,
        "handle": handle,
        "details": {},
        "metadata": {},
    }


def message(
    message_id=MESSAGE, space=SPACE, text="Hi", content=None, sender=None, status="received"
):
    return {
        "id": message_id,
        "projectId": PROJECT,
        "platform": "telegram",
        "space": {
            "id": space,
            "projectId": PROJECT,
            "platform": "telegram",
            "kind": "direct",
            "participantIds": [AGENT, PERSON],
            "details": {},
            "metadata": {},
        },
        "sentBy": sender or user(PERSON, "human", "100000001"),
        "receivedBy": user(AGENT, "agent", "photon_test_bot"),
        "content": content or {"type": "text", "format": "plain", "text": text},
        "status": status,
        "timestamps": {"receivedAt": NOW},
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
    }


def delivery(event_type="message.received", **fields):
    return {
        "id": "pho_evt_00000000000000000000000001",
        "type": event_type,
        "apiVersion": "2026-07-01",
        "source": "telegram.photon",
        "timestamp": NOW,
        "data": {"projectId": PROJECT, "object": message(**fields)},
    }


def answer(text="Hello from the app.", conversation=CONVERSATION):
    """Dify's blocking answer of a Chatflow, as the plugin receives it."""
    return {
        "event": "message",
        "task_id": "00000000-0000-0000-0000-0000000000d1",
        "id": "00000000-0000-0000-0000-0000000000d2",
        "message_id": "00000000-0000-0000-0000-0000000000d2",
        "conversation_id": conversation,
        "mode": "advanced-chat",
        "answer": text,
        "metadata": {},
        "created_at": 1792627200,
    }


def sent(text="Hello from the app.", space=SPACE):
    """Photon's 202 for the reply."""
    reply = message(REPLY, space, text, sender=user(AGENT, "agent", "photon_test_bot"))
    del reply["receivedBy"]
    return {**reply, "status": "dispatched", "timestamps": {"dispatchedAt": NOW}}
