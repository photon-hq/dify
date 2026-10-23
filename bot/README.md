# Photon Bot for Dify

Answer messages on iMessage, SMS, WhatsApp, WhatsApp Business, email, and Telegram with a Dify Chatflow or Chatbot app, through [Photon](https://photon.codes)'s messaging API ([API reference](https://photon.codes/docs/beta/api-reference)).

Photon calls a conversation a *space*. Each space belongs to one platform, and the project's own phone numbers, bots, and email accounts are its *agent* users. When the project receives a message, Photon delivers a signed `message.received` webhook to this plugin's endpoint. The plugin passes the message's text to the app selected in the endpoint's settings and sends the app's answer back into the same space, from the agent user that received the message. Each space keeps one Dify conversation, so the app answers with the space's earlier messages as context.

## Setup

1. In your Photon project, connect the channels you will use ([Messaging](https://photon.codes/docs/beta/messaging)). The plugin does not connect channels.
2. Create an Account Service Key (`pho_ask_`) or a Project API key (`pho_sk_`) that can send messages in the project ([Set up your project](https://photon.codes/docs/beta/get-started/project)).
3. Install **Photon Bot**, and add an endpoint to it with these settings:

| Setting | Required | Value |
|---|---|---|
| `api_origin` | Yes | Production (`https://api.photon.codes`, the default) or Staging (`https://api.staging.photon.codes`), matching your key. |
| `api_key` | Yes | The raw key, without `Bearer`. It sends the replies. |
| `signing_secret` | No | Leave it empty until step 5. |
| `app` | Yes | The Chatflow or Chatbot app that answers. Inputs set here are passed to the app with every message. |

4. Copy the endpoint URL that Dify shows, ending in `/`, and create a webhook destination for it in the Photon project, subscribed to `message.received` with API version `2026-07-01`. Use the URL exactly as Dify shows it: Photon does not follow redirects. With Photon's [Create webhook destination](https://photon.codes/docs/beta/api-reference/webhook-destinations/create-webhook-destination):

```http
POST https://api.photon.codes/v1/projects/pho_prj_…/webhooks/destinations
Authorization: Bearer pho_…
Idempotency-Key: dify-bot-1
Content-Type: application/json

{
  "name": "Dify bot",
  "url": "https://dify.example.com/e/<hook id>/",
  "apiVersion": "2026-07-01",
  "enabledEvents": ["message.received"]
}
```

5. Paste the destination's signing secret (`signingSecret`, `whsec_…`, returned only when the destination is created) into the endpoint's `signing_secret`, and save.

Until the signing secret is saved, the endpoint rejects every delivery, and Photon does not retry rejected deliveries.

Photon delivers only to public HTTPS URLs. On self-hosted Dify, set `ENDPOINT_URL_TEMPLATE` to the public HTTPS address of your Dify, for example `https://dify.example.com/e/{hook_id}`, because Dify builds the endpoint URL it shows from it.

## Usage

When a person sends "What are your opening hours?" to the project's Telegram bot, Photon delivers (abbreviated):

```json
{
  "type": "message.received",
  "data": {
    "projectId": "pho_prj_…",
    "object": {
      "id": "pho_msg_A",
      "space": {"id": "pho_spc_S"},
      "sentBy": {"id": "pho_usr_P", "kind": "human"},
      "receivedBy": {"id": "pho_usr_B", "kind": "agent"},
      "content": {"type": "text", "format": "plain", "text": "What are your opening hours?"}
    }
  }
}
```

The plugin sends the text to the app as the query, in the conversation it keeps for `pho_spc_S` and the app; the first message of a space starts a new conversation. It then sends the app's answer with Photon's [Send a Message](https://photon.codes/docs/beta/api-reference/messages/send-a-message):

```json
{
  "spaceId": "pho_spc_S",
  "senderId": "pho_usr_B",
  "content": {"type": "text", "format": "plain", "text": "<the app's answer>"}
}
```

with the idempotency key `pho_msg_A.reply`, derived from the received message, so Photon sends at most one reply to each message.

- Only `message.received` deliveries with text content (`content.type: text`) are answered. Other events, other content (images, voice, reactions, and others), messages sent by one of the project's agents, and messages without `receivedBy` are acknowledged without an answer. Skipping the agents' messages keeps them from answering each other, and the reply is sent as `receivedBy`.
- An app that answers with empty text sends nothing.
- Every delivery is checked against Photon's signature before anything else: the Standard Webhooks HMAC-SHA256 signature over the delivery's ID, timestamp, and body, with the timestamp within 5 minutes. A delivery that fails the check gets HTTP 401 and starts nothing.

## Timing and retries

Photon waits 20 seconds for each delivery attempt and retries a delivery that times out or fails; the destination's later messages wait until that delivery is done. The plugin calls the app and sends the answer before it responds, so:

- An answer that takes the app longer than 20 seconds may not be sent.
- Each message is answered at most once. When Photon delivers a message again, after a timeout or an error, the plugin acknowledges it without calling the app again. A message whose app call or reply failed gets no reply; the space keeps its Dify conversation.

## Connection requirements

The plugin makes HTTPS requests to the selected Photon host, `api.photon.codes` or `api.staging.photon.codes`, to send the replies ([Send a Message](https://photon.codes/docs/beta/api-reference/messages/send-a-message)), and calls the selected app through Dify. Photon sends deliveries to the endpoint URL.

## Limitations

- Only text is answered, and replies are plain text.
- The endpoint answers every text message its destination delivers, on every platform and line of the project.
- Agent apps cannot answer. Dify 1.17.1 rejects the plugin's blocking call to an Agent app (`agent-chat`), and rejects apps of its newer Agent runtime (app mode `agent`) as `unexpected app type`. To use tools, add tool or Agent nodes to a Chatflow.
- In Dify 1.17.1, if a space's conversation is deleted, a Chatbot app fails every later message in that space, because Dify cannot find the conversation; a Chatflow starts a new one.
- If the destination's signing secret is rotated in Photon, save the new secret in the endpoint before the old one expires.

## Privacy

See [PRIVACY.md](PRIVACY.md).

## Development

Source: [photon-hq/dify](https://github.com/photon-hq/dify), in `bot/`. With Python 3.12, from `bot/`:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

The tests mock Photon and Dify's app and storage calls, and never send messages.

## License

[MIT](https://github.com/photon-hq/dify/blob/main/LICENSE)
