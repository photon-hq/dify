# Photon Trigger for Dify

Start Dify workflows when a message arrives over iMessage, SMS, WhatsApp, WhatsApp Business, email, or Telegram, through [Photon](https://photon.codes)'s messaging API.

Photon calls a conversation a *space*. Each space belongs to one platform, and the project's own phone numbers, bots, and email accounts are its *agent* users. When the project receives a message, Photon delivers a signed `message.received` webhook, and this plugin starts the workflows that use its event. To reply, use the [Photon plugin](https://github.com/photon-hq/dify)'s `send_message`.

## Events

| Event | Starts when |
|---|---|
| `message_received` | The project receives a message (Photon's `message.received`). |

## Setup

1. In your Photon project, connect the channels you will use. The plugin does not connect channels.
2. Create an Account Service Key (`pho_ask_`) or a Project API key (`pho_sk_`) that can manage the project's webhook destinations, and copy the project ID (`pho_prj_`).
3. Install **Photon Trigger**, add its **Message received** event as a workflow's start node, and create a subscription with:

| Credential | Required | Value |
|---|---|---|
| `api_origin` | Yes | Production (`https://api.photon.codes`, the default) or Staging (`https://api.staging.photon.codes`), matching your key. |
| `api_key` | Yes | The raw key, without `Bearer`. |
| `project_id` | Yes | The project ID. |

Creating the subscription creates a Photon webhook destination for the subscription's Dify endpoint, subscribed to `message.received`, and Dify keeps the destination's signing secret with the subscription. Deleting the subscription deletes the destination.

Photon delivers only to public HTTPS URLs. On self-hosted Dify, set `TRIGGER_URL` to the public HTTPS address of your Dify API before creating the subscription, because Dify builds the endpoint from it.

## Usage

The event's variables are Photon's message as the webhook carries it: `id`, `platform`, `space`, `sentBy`, `receivedBy`, `content`, `status`, `timestamps`, `createdAt`, and `parentMessageId` when the message is a reply. `content.type` says what arrived; a text message's text is `content.text`, and an attachment's ID is `content.attachmentId`, for the Photon plugin's `get_attachment`.

To reply in the same space, pass these to the Photon plugin's `send_message`:

```json
{
  "space_id": "<the event's space.id>",
  "sender_id": "<the event's receivedBy.id>",
  "type": "text",
  "text": "Thanks, we got your message."
}
```

`receivedBy` is the project's agent user that received the message, so the reply comes from the same number, bot, or email account.

The event has three optional parameters, set on the start node: **Platforms** (start only for the selected platforms; none selected means all), **Text contains** (case-insensitive), and **Text regex**. A message that does not match is skipped and starts nothing; with **Text contains** set, a message without text is skipped.

Every delivery is checked against Photon's signature before a workflow starts: the Standard Webhooks HMAC-SHA256 signature over the delivery's ID, timestamp, and body, with the timestamp within 5 minutes. Deliveries that fail the check start nothing.

## Connection requirements

The plugin makes HTTPS requests to the selected Photon host, `api.photon.codes` or `api.staging.photon.codes`, to check the key and to create and delete the webhook destination. Photon sends deliveries to the subscription's Dify endpoint.

## Limitations

- Only received messages start workflows; delivery status and other Photon events do not.
- A subscription receives every `message.received` of the project. To handle only some, use the event's parameters, or branch on `receivedBy.id` in the workflow to handle one line.
- The subscription keeps the signing secret Photon returned when it was created. If the destination's secret is rotated in Photon, deliveries fail the check once the old secret expires; delete and recreate the subscription instead.
- If Photon cannot be reached when a subscription is deleted, Dify still deletes the subscription, and its webhook destination stays in Photon; delete it there.

## Privacy

See [PRIVACY.md](PRIVACY.md).

## Development

Source: [photon-hq/dify](https://github.com/photon-hq/dify), in `trigger/`. With Python 3.12, from `trigger/`:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

The tests mock Photon and never create destinations.

## License

[MIT](https://github.com/photon-hq/dify/blob/main/LICENSE)
