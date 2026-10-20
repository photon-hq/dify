# Photon for Dify

A Dify Tool provider for Photon's messaging API. It sends text and images into existing conversations on iMessage, SMS, WhatsApp, WhatsApp Business, email, and Telegram, lists conversations and messages, reads attachments, and checks canonical delivery status. The five tools are `send_message`, `list_spaces`, `list_messages`, `get_message`, and `get_attachment`. Parameter names are snake_case forms of Photon's API names, and values such as `platform`, `type`, `direction`, and `order` are Photon's own.

Photon calls a conversation a *space*. Every space belongs to one platform, and a message sent into a space goes out on that space's platform, so the same five tools work for every channel.

## Supported channels

| Channel | `platform` value | What the Photon project needs |
|---|---|---|
| iMessage | `imessage` | A dedicated iMessage line, or a shared-line assignment. Shared lines send only in direct spaces, and only to people who have messaged the line since their assignment. |
| SMS | `sms` | An SMS-capable number. Photon requires campaign eligibility for the sender unless every recipient is in-network. |
| WhatsApp | `whatsapp` | A WhatsApp line (dedicated, or a shared-line assignment). |
| WhatsApp Business | `whatsapp_business` | A connected WhatsApp Business account and sender. |
| Email | `email` | A connected email domain. |
| Telegram | `telegram` | A connected Telegram bot. |

## Prerequisites

- A Dify instance with tool-plugin installation enabled and a Python 3.12 plugin runner. The manifest declares a minimum Dify version of 1.0.0.
- To send images from a self-hosted Dify, set `INTERNAL_FILES_URL` (or `FILES_URL`) in Dify's environment to a Dify API address the plugin can reach. Dify builds the URL of each Dify-stored file it passes to a plugin from `INTERNAL_FILES_URL`, or from `FILES_URL` when `INTERNAL_FILES_URL` is empty; if both are empty, the URL is relative and the plugin cannot download the image.
- A Photon account and project with at least one connected channel, existing spaces on it, and a project-owned agent user that may send in those spaces.
- A Photon Account Service Key (`pho_ask_` prefix) with access to that project, or a Project API key (`pho_sk_` prefix) bound to it. This plugin does not create accounts, connect channels, provision lines, or create spaces.

## Setup and required credentials

1. Sign in to [Photon](https://photon.codes). Create an Account Service Key in your account's key settings, or a Project API key in the target project's API-key settings. Copy the raw key; do not prepend `Bearer`.
2. Copy the full project ID (`pho_prj_` followed by its 26-character ID) from the project details. A Project API key must belong to this same project.
3. For each channel you will send on, note the project's agent user ID (`pho_usr_` followed by its 26-character ID). Photon users belong to one platform, so an agent on your iMessage line is a different user from the agent on your WhatsApp line. Use agent users owned by the project, not human recipients or resource IDs.
4. In Dify, open **Plugins** and install **Photon** from the Marketplace, or choose **Install from local package** for a locally built `.difypkg` and follow your instance's plugin-signature policy.
5. Open **Tools > Photon > Authorize** (wording can vary by Dify version). Select **Photon environment** to match your credentials: **Production** (`https://api.photon.codes`, the default) or **Staging** (`https://api.staging.photon.codes`). Configure the remaining credentials below and save. The API key, project, sender, and space IDs must all belong to that environment. Saving makes one authenticated, read-only request for at most one space in the project; an empty project is valid. The plugin never switches environments on its own.
6. Add a Photon tool node to a Workflow, Chatflow, or Agent. Use `list_spaces` to find the right existing space before sending.

| Credential | Required | Meaning |
|---|---|---|
| `api_origin` | Default supplied | Environment selector: exactly `https://api.photon.codes` (Production, default) or `https://api.staging.photon.codes` (Staging). |
| `api_key` | Yes | Raw Account Service Key or Project API key, stored as a secret input in Dify. |
| `project_id` | Yes | Full `pho_prj_` ID used for every request. |
| `default_sender_id` | No | Full `pho_usr_` agent user ID used when `send_message.sender_id` is omitted. Set it to the agent you send from most often and pass `sender_id` for other channels. |

The environment selector accepts only these two exact origins. Arbitrary URLs, trailing slashes, paths, query strings, fragments, and custom ports are rejected. Existing credentials that omit `api_origin` use production. Credentials are provider settings and are not model-facing tool parameters.

## Usage examples

The IDs below are syntactically valid examples; replace them with real IDs from your project. Outputs are JSON messages with stable snake_case keys. Absent scalar values are `null`, and absent lists are empty arrays. Timestamps are passed through as RFC 3339 values under named snake_case keys. Every message and space in the output carries its `platform`.

Each tool also emits a named output variable for every non-reserved top-level result field, with the same value as in the JSON message. Dify reserves `text`, `files`, and `json`; these keys are never emitted as named variables. Message text stays in the JSON output (`json[0].text` for single-message results, or each message item in list results). For a tool node whose ID is `send`, an End node can bind selectors such as `["send", "id"]` or `["send", "status"]`; the complete JSON output remains available. Nested objects such as `content`, `timestamps`, and `failure`, arrays such as `items` and `attachment_ids`, empty lists, booleans, and nulls are passed through as variable values without flattening or string conversion.

### Message fields

`send_message`, `list_messages`, and `get_message` return messages with the same fields:

| Field | Meaning |
|---|---|
| `id`, `platform`, `space_id` | The message ID, its platform, and its space. |
| `direction` | `received` for inbound messages, `sent` for outbound messages with any delivery status. |
| `type` | Photon's content type, for example `text`, `attachment`, `group`, `voice`, or `reaction`. |
| `text` | The text of a `text` message, or the text parts of a `group` joined by new lines; otherwise `null`. |
| `attachment_ids` | The attachment IDs of `attachment` and `voice` content, including those inside a `group`. Pass one to `get_attachment`. |
| `content` | Photon's content object with snake_case keys, for every content type. |
| `parent_message_id` | The message this one replies to, or `null`. |
| `status`, `delivery_confirmed` | Canonical status: `received`, `dispatched`, `accepted`, `delivered`, or `failed`, on every channel. `delivery_confirmed` is `true` only for `delivered`. |
| `timestamps` | Always `created_at`, `updated_at`, `received_at`, `dispatched_at`, `accepted_at`, `delivered_at`, and `failed_at`; unavailable milestones are `null`. |
| `failure` | Photon's `code`, `message`, and `confirmed_recipient_count` when available, otherwise `null`. |

### 1. Send a message

Text, with a default sender configured:

```json
{
  "space_id": "pho_spc_00000000000000000000000001",
  "type": "text",
  "text": "Hello from my Dify workflow.",
  "idempotency_key": "order-1042-confirmation-v1"
}
```

Images, with optional text in the same message where the channel allows it:

```json
{
  "space_id": "pho_spc_00000000000000000000000001",
  "type": "attachment",
  "attachments": ["<image files from a Dify file variable>"],
  "text": "Your order has shipped.",
  "idempotency_key": "order-1042-photos-v1"
}
```

To send as another agent, reply to an existing message, or set an email subject, add:

```json
{
  "sender_id": "pho_usr_00000000000000000000000001",
  "parent_message_id": "pho_msg_00000000000000000000000001",
  "email_subject": "Your order 1042"
}
```

`space_id` and `type` are required; `type` defaults to `text`. It takes Photon's content types `text` and `attachment`:

- `text` requires `text` and takes no attachments. Text is sent unchanged as `{ "type": "text", "format": "plain", "text": "..." }`.
- `attachment` requires at least one file in `attachments`. Every file must be a JPEG, PNG, GIF, or WebP image of at most 10 MB, matching Dify's default image upload limit; anything else is rejected before anything is sent to Photon. Each image is uploaded to Photon first and then referenced by its attachment ID. One image without text is sent as `{ "type": "attachment", "attachmentId": "pho_att_..." }`. Several images, or images with text, are sent as one `group` message: the text first, if any, then the images in order.

Beyond these checks, Photon decides which content each channel accepts, and the tool reports Photon's error code when it rejects a send. Content a channel does not accept fails with `UNSUPPORTED_CONTENT`. Photon currently sends images on three channels:

- iMessage: images or text in one message, not both.
- SMS: up to 10 images, at most 600,000 bytes in total, as one MMS, with or without text.
- Telegram: JPEG and PNG only, one image or an album of up to 10 with at most 10,000,000 bytes in total, and no text in the same message.

WhatsApp, WhatsApp Business, and email spaces take text only. Where a channel does not take text and images together, send them as two messages.

The space decides the channel. `sender_id` falls back to the provider's default; one must be present, and it must be an agent on the same channel as the space. Text must be non-blank and no more than 10,000 characters, a plugin safety cap rather than a Photon maximum; individual channels may accept less. `parent_message_id` replies to an existing message. Photon currently supports replies on email and Telegram; iMessage, SMS, WhatsApp, and WhatsApp Business spaces reject it with `SPACE_NOT_SENDABLE`. `email_subject` is optional, at most 4,096 characters, and meant for email spaces only; leave it empty on other channels.

An omitted or empty `idempotency_key` generates a UUID. Supplied keys must contain 1-255 visible ASCII characters without spaces. Each image is uploaded with an idempotency key derived from the send key and the image's position, so a retry with the same key and the same images repeats identical uploads, which Photon answers with the attachments it already committed. The result has the message fields above plus `idempotency_key`.

**HTTP 202 means submission succeeded; it does not confirm delivery.** `dispatched` and `accepted` are not delivery confirmation. Only a canonical `delivered` status sets `delivery_confirmed` to `true`. Use `get_message` after sending. The plugin never retries automatically or polls in the background. For workflows that may retry, supply a stable key in advance and reuse it only with the identical send body; Photon rejects a reused key with a different body (`IDEMPOTENCY_KEY_REUSED`). After a timeout or connection failure, the submission may already have happened: check history or status before retrying explicitly. If the plugin generated the key, a failed send's error includes it, so an explicit retry can reuse it.

Send failures name Photon's error code with a short hint, for example `SMS_CAMPAIGN_NOT_ELIGIBLE`, `SHARED_LINE_INBOUND_REQUIRED`, `SPACE_NOT_SENDABLE`, `UNSUPPORTED_CONTENT`, `PAYLOAD_TOO_LARGE`, or `MESSAGE_TOO_LONG`.

### 2. List spaces

```json
{
  "platform": "whatsapp_business",
  "page_size": 20,
  "participant_handle": "+14155550123",
  "order": "desc"
}
```

All parameters are optional. `platform` is one of `imessage`, `sms`, `whatsapp`, `whatsapp_business`, `email`, or `telegram`; omit it to list every channel. `page_size` defaults to 20, must be a positive integer, and is capped at 100. `participant_handle` accepts a phone number or email address up to 320 characters and matches case-insensitively. `order` is `desc` by default or `asc`.

The output is `{ "items": [...], "next_page_token": null }`. Each space has `id`, `platform`, `kind`, `participant_ids`, `created_at`, and `updated_at`. If a token is returned, pass it as `page_token` with all other filters unchanged. Continue until `next_page_token` is `null`, even if a page has no items.

### 3. List messages

```json
{
  "platform": "imessage",
  "space_id": "pho_spc_00000000000000000000000001",
  "direction": "sent",
  "order": "desc",
  "page_size": 20,
  "created_since": "2026-10-18T00:00:00Z",
  "created_before": "2026-10-19T00:00:00Z"
}
```

All parameters are optional. `platform` works as in `list_spaces`. `direction` is Photon's `received` or `sent`; omit it for both. `order` is `desc` by default or `asc`. `page_size` defaults to 20 and is capped at 200. Dates require RFC 3339 with a timezone; the lower bound is inclusive and the upper bound is exclusive, and the lower bound must be earlier. Pagination works as in `list_spaces`.

The output contains `items` (messages with the fields above), `next_page_token`, `scanned_count`, and `space_filter_applied_locally`.

Photon's API requires a resource or user perspective to filter by `spaceId` on the server, and user perspectives cannot be combined with platform or time filters. To keep this tool's parameters, the plugin fetches one project page with the platform, direction, order, and time filters and applies `space_id` locally. `page_size` therefore bounds scanned project messages, and a filtered page may contain fewer matches or none. **Always follow a non-null `next_page_token`, including after an empty page.** There is no hidden page scanning and no extra request.

### 4. Get a message

```json
{
  "message_id": "pho_msg_00000000000000000000000001"
}
```

`message_id` is required. The output is one message with the fields above, including its content, canonical status, all timestamp slots, and `failure`. Fetching a message never sends another one.

### 5. Get an attachment

```json
{
  "attachment_id": "pho_att_00000000000000000000000001"
}
```

`attachment_id` is required and comes from a message's `attachment_ids`. The output has `id`, `filename`, `content_type`, `size_bytes`, and `created_at`, and the file itself is returned to Dify as a file output, for example to pass an image to a vision model. Files larger than 50 MB, Dify's default limit for files returned by plugins, are rejected. If Photon is still processing the file, the tool reports `ATTACHMENT_NOT_READY`; retry shortly.

## Connection requirements

- Allow outbound verified HTTPS on TCP port 443 to the selected environment: **`api.photon.codes`** for production or **`api.staging.photon.codes`** for staging. Both hosts are declared in `manifest.yaml`.
- Photon requests use exactly the selected origin plus the fixed `/v1/projects/{project_id}` prefix. Redirects are rejected, and there is no automatic fallback to the other environment. No arbitrary URLs or trailing paths are accepted.
- Photon requests use a 5-second connect timeout and a 15-second read timeout, an approximately 20-second budget per request. These are transport inactivity limits, not a strict wall-clock guarantee.
- Photon requests ignore ambient proxy and `.netrc` settings. Configure direct egress for the selected host.
- To send images, the Dify plugin SDK also downloads each image from the URL that Dify passes for it: a Dify file URL for files stored in Dify (see Prerequisites), or the original URL for a file that the workflow received by URL. Apart from that, the plugin talks only to Photon. Photon delivers each message over its channel's own network.

## Security

The plugin validates full Photon ID formats, sender availability, platform values, the content `type` and the inputs it requires, that every attachment is a JPEG, PNG, GIF, or WebP image of at most 10 MB, non-blank text and its local length cap, the email subject length, page sizes, cursor format, time bounds, direction, order, and idempotency keys before making the requested API call. Photon remains authoritative for project ownership, permissions, the space's channel, sender authorization, and the content each channel accepts.

Photon requests go only to the selected, allowlisted Photon API origin: production `https://api.photon.codes` or staging `https://api.staging.photon.codes`. Validation requires an exact string match before any API request; malformed origins, arbitrary hosts, paths, user information, query strings, fragments, and custom ports are rejected. The project path prefix stays fixed, and only seven Photon operations can be called: list spaces, list messages, get a message, send a message, upload an attachment, get an attachment, and download an attachment's content. TLS certificate verification stays enabled; redirects and automatic retries are disabled. The plugin performs no file system access, subprocess execution, arbitrary code evaluation, or persistent storage; image bytes stay in memory and are not stored by the plugin.

Dify manages provider credentials in its credential store. The plugin holds credentials only in memory to build the Bearer authorization header. It does not log secrets or full request headers. API `application/problem+json` errors are reduced to the HTTP status, an allowlisted Photon error code, and a short hint; arbitrary error bodies and transport exception text are never echoed. The configured API key and recognizable Photon key strings are redacted from JSON output, including message text or failure details if the API echoes them. Dify may retain workflow inputs, outputs, files, and logs according to its own settings. See [PRIVACY.md](PRIVACY.md).

Sending is an external write action. Treat asynchronous submission and confirmed delivery separately, and use caller-controlled idempotency to prevent duplicate sends.

## Limitations

- Existing spaces only: no new conversations, line provisioning, voice calls, inbound triggers, background polling, or delivery webhooks.
- Sending covers text and JPEG, PNG, GIF, or WebP images of up to 10 MB each (Photon's `text` and `attachment` content types). Voice messages, reactions, and other files are not sent. Reading messages returns every content type.
- Each channel's rules still apply. Shared iMessage lines send only in direct spaces to people who have messaged the line since their assignment. iMessage and Telegram do not accept text and images in one message, Telegram takes only JPEG and PNG images, and SMS takes at most 600,000 bytes of images per message. WhatsApp, WhatsApp Business, and email take text only, and only email and Telegram accept replies. SMS needs campaign eligibility unless every recipient is in-network. Telegram bots cannot start a conversation with a user or send to a group they are not in; Photon reports such sends as failed.
- One default sender covers one channel. Pass `sender_id` when sending on a channel whose agent differs from `default_sender_id`.
- Photon list results are eventually consistent. Empty or delayed history is not proof of failed delivery.
- Space-filtered message results are paginated project scans as described above.
- Provider validation verifies read access, not permission to send as every agent. It accepts an empty project and does not send a test message.

## Source and development

Source repository: [photon-hq/dify](https://github.com/photon-hq/dify). Report issues there or by email to the contact in `manifest.yaml`.

Runtime dependencies are exactly `dify-plugin==0.10.2` and `requests==2.33.1` in both dependency files. SDK 0.10.2 requires Requests >=2.33.1.

Install the requirements with Python 3.12, then run the tests from the source root:

```sh
python -m unittest discover -s tests -v
```

The tests mock Photon at the HTTPS transport boundary and mock Dify's file downloads. They cover SDK registration, credentials, all five tools, all six platforms, text and image sends, attachment uploads and downloads, production and staging origin selection, rejection of other origins, and error handling. Set `PHOTON_OPENAPI` to a copy of Photon's OpenAPI document (with `jsonschema` installed) to also validate requests and fixtures against the official schemas and tool outputs against each tool's output schema. The tests never send real messages, and tests and build tooling are excluded from the package.

## License

MIT License

Copyright (c) 2026 gtxy27

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
