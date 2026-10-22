"""Synthetic Photon deliveries and responses; no real credentials or customer data."""

PROJECT = "pho_prj_00000000000000000000000001"
SPACE = "pho_spc_00000000000000000000000001"
AGENT = "pho_usr_00000000000000000000000001"
PERSON = "pho_usr_00000000000000000000000002"
MESSAGE = "pho_msg_00000000000000000000000001"
DESTINATION = "pho_whd_00000000000000000000000001"
KEY = "pho_" + "sk_" + "synthetic_fixture_only"
SECRET = "whsec_" + "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
NOW = "2026-10-22T00:00:00.000Z"
ENDPOINT = "https://dify.example/triggers/plugin/00000000-0000-0000-0000-000000000001"
CREDENTIALS = {
    "api_origin": "https://api.photon.codes",
    "api_key": KEY,
    "project_id": PROJECT,
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


def message():
    return {
        "id": MESSAGE,
        "projectId": PROJECT,
        "platform": "telegram",
        "space": {
            "id": SPACE,
            "projectId": PROJECT,
            "platform": "telegram",
            "kind": "direct",
            "participantIds": [AGENT, PERSON],
            "details": {},
            "metadata": {},
        },
        "sentBy": user(PERSON, "human", "100000001"),
        "receivedBy": user(AGENT, "agent", "photon_test_bot"),
        "content": {"type": "text", "format": "plain", "text": "Hi"},
        "status": "received",
        "timestamps": {"receivedAt": NOW},
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
    }


def delivery(event_type="message.received"):
    return {
        "id": "pho_evt_00000000000000000000000001",
        "type": event_type,
        "apiVersion": "2026-07-01",
        "source": "telegram.photon",
        "timestamp": NOW,
        "data": {"projectId": PROJECT, "object": message()},
    }


def destination(**fields):
    return {
        "destinationId": DESTINATION,
        "projectId": PROJECT,
        "name": "Dify",
        "description": None,
        "url": ENDPOINT,
        "apiVersion": "2026-07-01",
        "enabledEvents": ["message.received"],
        "status": "enabled",
        "createdAt": NOW,
        "updatedAt": NOW,
        "deletedAt": None,
        **fields,
    }
