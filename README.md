# Photon for Dify

Send and read messages on iMessage, SMS, WhatsApp, WhatsApp Business, email, and Telegram from Dify workflows, chatflows, and agents, through [Photon](https://photon.codes)'s messaging API.

Photon calls a conversation a *space*. Each space belongs to one platform (`imessage`, `sms`, `whatsapp`, `whatsapp_business`, `email`, or `telegram`), and a message sent into a space goes out on that platform, so the same tools work for every channel.

## Tools

| Tool | What it does |
|---|---|
| `send_message` | Sends text (`type: text`) or JPEG, PNG, GIF, or WebP images of up to 10 MB each (`type: attachment`) into an existing space. |
| `list_spaces` | Lists spaces, optionally for one platform or participant. |
| `list_messages` | Lists messages by platform, direction, creation time, and space. |
| `get_message` | Returns one message with its content and delivery status. |
| `get_attachment` | Returns an attachment's metadata, and its file as a Dify file. |

## Setup

1. In your Photon project, connect the channels you will use. The plugin sends into existing spaces; it does not connect channels or create conversations.
2. Create an Account Service Key (`pho_ask_`) or a Project API key (`pho_sk_`), and copy the project ID (`pho_prj_`). For each channel you send on, note the agent user ID (`pho_usr_`) that sends there; Photon users belong to one channel.
3. Install **Photon** from the Dify Marketplace, then authorize it under **Tools > Photon**:

| Credential | Required | Value |
|---|---|---|
| `api_origin` | Yes | Production (`https://api.photon.codes`, the default) or Staging (`https://api.staging.photon.codes`), matching your key. |
| `api_key` | Yes | The raw key, without `Bearer`. |
| `project_id` | Yes | The project ID. |
| `default_sender_id` | No | The agent user ID to send from when `send_message` has no `sender_id`. |

On self-hosted Dify, set `INTERNAL_FILES_URL` (or `FILES_URL`) to a Dify API address the plugin can reach; otherwise the plugin cannot download the images it is asked to send.

## Usage

Send text, or images with optional text:

```json
{
  "space_id": "pho_spc_…",
  "type": "attachment",
  "attachments": ["<image files from a Dify file variable>"],
  "text": "Your order has shipped.",
  "idempotency_key": "order-1042-photos-v1"
}
```

- Several images, or images with text, are sent as one `group` message: the text first, then the images in order. Each image is uploaded to Photon before the message.
- `sender_id`, `parent_message_id` (reply) and `email_subject` are optional.
- Photon decides what each channel accepts. When it rejects a send, the error keeps Photon's status, code and reason, for example `Photon API HTTP 422 (UNSUPPORTED_CONTENT): …`.
- Sending is asynchronous: the result is usually `dispatched`. Call `get_message` later; only `delivered` sets `delivery_confirmed` to `true`.
- Reuse the same `idempotency_key` to retry a send safely. If you omit it, the plugin generates one and returns it in the result, and in the error if the send fails.

Lists return `items` and `next_page_token`. Pass the token back as `page_token`, with the same filters, until it is `null`, even after an empty page. `list_messages` filters by `space_id` within each page it fetches, so a page can contain fewer matches than `page_size`.

Messages have `id`, `platform`, `space_id`, `direction` (`received` or `sent`), `type`, `text`, `attachment_ids`, `content` (the full content in Photon's structure), `parent_message_id`, `status`, `delivery_confirmed`, `timestamps` and `failure`. Each top-level field is also a named output variable, except `text`, which fills Dify's own `text` output.

`get_attachment` returns the file as a Dify file output, for example for a vision model. Files over 50 MB, Dify's default limit for plugin files, are not downloaded.

## Connection requirements

The plugin makes HTTPS requests to the selected Photon host, `api.photon.codes` or `api.staging.photon.codes`, and downloads the images to send from the URLs Dify provides for them.

## Limitations

- Only existing spaces; no new conversations, inbound triggers, or delivery webhooks.
- Sending covers text and images. Reading returns every content type.
- One default sender covers one channel; pass `sender_id` for the others.

## Privacy

See [PRIVACY.md](PRIVACY.md).

## Development

Source: [photon-hq/dify](https://github.com/photon-hq/dify). With Python 3.12:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

The tests mock Photon and Dify's file downloads and never send messages.

## License

[MIT](LICENSE)
