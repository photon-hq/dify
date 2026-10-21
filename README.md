# Photon for Dify

Send and read messages on iMessage, SMS, WhatsApp, WhatsApp Business, email, and Telegram from Dify workflows, chatflows, and agents, through [Photon](https://photon.codes)'s messaging API.

Photon calls a conversation a *space*. Each space belongs to one platform (`imessage`, `sms`, `whatsapp`, `whatsapp_business`, `email`, or `telegram`), and a message sent into a space goes out on that platform, so the same tools work for every channel.

## Tools

| Tool | What it does |
|---|---|
| `send_message` | Sends text (`type: text`) or JPEG, PNG, GIF, or WebP images of up to 10 MB each (`type: attachment`) into an existing space. |
| `list_spaces` | Lists spaces, optionally for one platform or participant. |
| `create_or_get_space` | Returns the space for the given users on one platform, creating it if needed. |
| `list_messages` | Lists messages by platform, direction, and creation time, or one space's messages. |
| `get_message` | Returns one message with its sender, content, and delivery status. |
| `get_user` | Returns one user's handle, and whether it is an agent (a line or account Photon manages) or a person. |
| `create_or_get_user` | Returns the user for a phone number or email address on one platform, creating it if Photon does not know it yet. |
| `get_attachment` | Returns an attachment's metadata, and its file as a Dify file. |

## Setup

1. In your Photon project, connect the channels you will use. The plugin does not connect channels.
2. Create an Account Service Key (`pho_ask_`) or a Project API key (`pho_sk_`), and copy the project ID (`pho_prj_`).
3. Install **Photon** from the Dify Marketplace, then authorize it under **Tools > Photon**:

| Credential | Required | Value |
|---|---|---|
| `api_origin` | Yes | Production (`https://api.photon.codes`, the default) or Staging (`https://api.staging.photon.codes`), matching your key. |
| `api_key` | Yes | The raw key, without `Bearer`. |
| `project_id` | Yes | The project ID. |

On self-hosted Dify, set `INTERNAL_FILES_URL` (or `FILES_URL`) to a Dify API address the plugin can reach; otherwise the plugin cannot download the images it is asked to send.

## Usage

Send text, or images with optional text:

```json
{
  "space_id": "pho_spc_…",
  "sender_id": "pho_usr_…",
  "type": "attachment",
  "attachments": ["<image files from a Dify file variable>"],
  "text": "Your order has shipped.",
  "idempotency_key": "order-1042-photos-v1"
}
```

- Several images, or images with text, are sent as one `group` message: the text first, then the images in order. Each image is uploaded to Photon before the message.
- `sender_id` is the project's agent user in the space: the `receivedBy.id` of a message received in it, or the `sentBy.id` of one sent from it. `get_user` tells agents (`kind: agent`) from people; this project's dedicated lines have `details.resourceId`.
- `parent_message_id` (reply) and `email_subject` are optional.
- Photon decides what each channel accepts. When it rejects a send, the error keeps Photon's status, code and reason, for example `Photon API HTTP 422 (UNSUPPORTED_CONTENT): …`.
- Sending is asynchronous: the result is usually `dispatched`. Call `get_message` later: `delivered` confirms delivery, `accepted` means the channel took the message without confirming delivery (`acceptance.code` says why), and `failed` carries `failure`.
- Reuse the same `idempotency_key` to retry a send safely. If you omit it, the plugin generates one and returns it in the result, and in the error if the send fails.

To start a conversation with someone new, get their user with `create_or_get_user`, then a space with `create_or_get_space`, and send into that space:

```json
{"platform": "sms", "handle": "+14155550123"}
{"platform": "sms", "participant_ids": "pho_usr_<agent>,pho_usr_<person>"}
```

- `participant_ids` must include one of the project's agents, the one that will send: the `receivedBy.id` of a message received on that line, or the user `create_or_get_user` returns for the line's own number (`kind: agent`). On iMessage, put the agent first. A new iMessage space needs one of the project's dedicated lines; a shared line only returns the existing direct space with a person assigned to the project on that line.
- A known handle returns its existing user, and direct spaces and SMS groups with the same participants return the existing space. On email, each new `idempotency_key` starts a new thread.

Lists return Photon's page: `items`, and `nextPageToken` when there are more. To get the next page, pass it as `page_token` with the same filters. To list one space's messages, pass `space_id` with `perspective_user_id`, the project's agent user in that space; Photon then does not accept `platform`, `created_since` or `created_before`.

Results are Photon's objects as the API returns them. A message has `id`, `platform`, `space`, `sentBy`, `receivedBy` when Photon records it, `content`, `parentMessageId`, `status`, `timestamps`, and `acceptance` or `failure` when they apply; a text message's text is `content.text`. Each top-level field of a result is also a named output variable.

`get_attachment` returns the file as a Dify file output for workflows, for example for a vision model; in Agent apps the model cannot see the file. Files over 50 MB, Dify's default limit for plugin files, are not downloaded.

## Connection requirements

The plugin makes HTTPS requests to the selected Photon host, `api.photon.codes` or `api.staging.photon.codes`, and downloads the images to send from the URLs Dify provides for them.

## Limitations

- No inbound triggers or delivery webhooks.
- Photon does not create users or spaces on Telegram (`OPERATION_UNAVAILABLE`); a Telegram conversation starts when the person messages the bot.
- Sending covers text and images. Reading returns every content type.
- Classic Agent apps cannot pass files to tools, so they send text only; workflows and the newer Agent can send images.

## Privacy

See [PRIVACY.md](PRIVACY.md).

## Development

Source: [photon-hq/dify](https://github.com/photon-hq/dify). With Python 3.12:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

The tests mock Photon and Dify's file downloads and never send messages.

Every merge to `main` publishes a GitHub prerelease with a staging build, which defaults to Photon's staging API, and the production candidate. The production release is published by running the **Promote to production** workflow.

## License

[MIT](LICENSE)
