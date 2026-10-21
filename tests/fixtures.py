"""Synthetic Photon responses; no real credentials or customer data."""

import struct
import zlib

from dify_plugin.file.constants import DIFY_FILE_IDENTITY

PROJECT = "pho_prj_00000000000000000000000001"
SPACE = "pho_spc_00000000000000000000000001"
OTHER_SPACE = "pho_spc_00000000000000000000000002"
SENDER = "pho_usr_00000000000000000000000001"
OTHER_SENDER = "pho_usr_00000000000000000000000002"
MESSAGE = "pho_msg_00000000000000000000000001"
FAILED_MESSAGE = "pho_msg_00000000000000000000000002"
RESOURCE = "pho_res_00000000000000000000000001"
ATTACHMENT = "pho_att_00000000000000000000000001"
OTHER_ATTACHMENT = "pho_att_00000000000000000000000002"
KEY = "pho_" + "sk_" + "synthetic_fixture_only"
NOW = "2026-10-19T00:00:00.000Z"
CURSOR = "fixture.signature"
CREDENTIALS = {
    "api_origin": "https://api.photon.codes",
    "api_key": KEY,
    "project_id": PROJECT,
}

HANDLES = {"email": "agent@example.com", "telegram": "123456789"}


def chat(space=SPACE, platform="imessage"):
    return {
        "id": space,
        "projectId": PROJECT,
        "platform": platform,
        "kind": "direct",
        "participantIds": [SENDER, OTHER_SENDER],
        "details": {},
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
    }


def user(user_id=SENDER, kind="agent", handle="+14155550123"):
    return {
        "id": user_id,
        "projectId": PROJECT,
        "platform": "imessage",
        "kind": kind,
        "handle": handle,
        "details": {"type": "dedicated", "resourceId": RESOURCE} if kind == "agent" else {},
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
    }


def png(width=2, height=2):
    raw = b"".join(b"\x00" + b"\x34\x78\xf6" * width for _ in range(height))

    def chunk(kind, data):
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


PNG = png()
PNG_SIZE = len(PNG)


def image(name="photo.png", mime="image/png", data=PNG):
    return {
        "dify_model_identity": DIFY_FILE_IDENTITY,
        "url": f"https://dify.example/files/{name}",
        "mime_type": mime,
        "filename": name,
        "extension": "." + name.rsplit(".", 1)[-1],
        "size": len(data),
        "type": "image" if mime.startswith("image/") else "document",
    }


def attachment(
    attachment_id=ATTACHMENT, content_type="image/png", filename="photo.png", size=PNG_SIZE
):
    return {
        "id": attachment_id,
        "projectId": PROJECT,
        "contentType": content_type,
        "filename": filename,
        "sizeBytes": size,
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
    }


def message(
    status="dispatched",
    text="Hello from local acceptance.",
    space=SPACE,
    platform="imessage",
    content=None,
):
    milestones = {
        "received": "receivedAt",
        "dispatched": "dispatchedAt",
        "accepted": "acceptedAt",
        "delivered": "deliveredAt",
        "failed": "failedAt",
    }
    details = (
        {"type": "dedicated", "resourceId": RESOURCE}
        if platform == "imessage"
        else {"resourceId": RESOURCE}
    )
    result = {
        "id": FAILED_MESSAGE if status == "failed" else MESSAGE,
        "projectId": PROJECT,
        "platform": platform,
        "space": {
            k: v for k, v in chat(space, platform).items() if k not in ("createdAt", "updatedAt")
        },
        "sentBy": {
            "id": SENDER,
            "projectId": PROJECT,
            "platform": platform,
            "kind": "agent",
            "handle": HANDLES.get(platform, "+14155550123"),
            "details": details,
            "metadata": {},
        },
        "content": content or {"type": "text", "format": "plain", "text": text},
        "metadata": {},
        "createdAt": NOW,
        "updatedAt": NOW,
        "status": status,
        "timestamps": {milestones[status]: NOW},
    }
    if status == "accepted":
        result["acceptance"] = {
            "code": "delivery_confirmation_unavailable",
            "message": "Delivery confirmation unavailable.",
        }
    if status in ("accepted", "delivered"):
        result["timestamps"]["dispatchedAt"] = NOW
    if status == "failed":
        result["failure"] = {
            "code": "message_delivery_failed",
            "message": "Synthetic delivery failure.",
            "confirmedRecipientCount": 0,
        }
    return result
