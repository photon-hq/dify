# Photon Dify 插件

这是一个对接 Photon 消息 API 的 Dify 工具提供方插件。它可以向 iMessage、短信（SMS）、WhatsApp、WhatsApp Business、电子邮件和 Telegram 上的现有会话发送文字和图片，列出会话和消息，读取附件，并查询权威的投递状态。提供五个工具：`send_message`、`list_spaces`、`list_messages`、`get_message` 和 `get_attachment`。参数名是 Photon API 中名称的 snake_case 形式，`platform`、`type`、`direction`、`order` 等参数直接使用 Photon 的取值。

Photon 把会话称为 *space*。每个会话只属于一个渠道，向会话发送的消息会走该会话所在的渠道，所以同一套五个工具适用于所有渠道。

## 支持的渠道

| 渠道 | `platform` 取值 | Photon 项目需要具备 |
|---|---|---|
| iMessage | `imessage` | 专属 iMessage 线路，或共享线路分配。共享线路只能在单聊会话中发送，且只能发给分配之后给该线路发过消息的人。 |
| 短信 | `sms` | 可收发短信的号码。除非所有收件人都在网内，Photon 要求发送方具备 campaign 资格。 |
| WhatsApp | `whatsapp` | WhatsApp 线路（专属线路或共享线路分配）。 |
| WhatsApp Business | `whatsapp_business` | 已连接的 WhatsApp Business 账号和发送方。 |
| 电子邮件 | `email` | 已连接的邮件域名。 |
| Telegram | `telegram` | 已连接的 Telegram bot。 |

## 前提条件

- Dify 已启用工具插件安装，插件运行器使用 Python 3.12。清单声明的最低版本为 Dify 1.0.0。
- 在自部署的 Dify 上发送图片时，需要在 Dify 的环境变量中把 `INTERNAL_FILES_URL`（或 `FILES_URL`）设为插件能访问到的 Dify API 地址。对于存放在 Dify 中的文件，Dify 传给插件的地址由 `INTERNAL_FILES_URL` 生成，它为空时使用 `FILES_URL`；两者都为空时，地址是相对路径，插件无法下载图片。
- Photon 账号和项目至少连接了一个渠道，该渠道上有现有会话，并且有允许在这些会话中发送消息的项目自有代理用户。
- 使用具有项目访问权限的 Account Service Key（`pho_ask_` 前缀），或绑定该项目的 Project API key（`pho_sk_` 前缀）。本插件不创建账号、不连接渠道、不开通线路，也不新建会话。

## 配置步骤与凭据

1. 登录 [Photon](https://photon.codes)，在账号的密钥设置中创建 Account Service Key，或在目标项目的 API 密钥设置中创建 Project API key。复制原始密钥，不要添加 `Bearer`。
2. 从项目详情复制完整的项目 ID（`pho_prj_` 加 26 位标识）。Project API key 必须绑定同一个项目。
3. 记下每个要发送的渠道上项目代理用户的 ID（`pho_usr_` 加 26 位标识）。Photon 的用户只属于一个渠道，所以 iMessage 线路上的代理和 WhatsApp 线路上的代理是不同的用户。请使用项目自有的代理用户，不要用收件人的用户 ID 或资源 ID。
4. 在 Dify 的插件页面从 Marketplace 安装 **Photon**；如果是本地构建的 `.difypkg`，选择从本地文件安装，并遵循当前部署的插件签名策略。
5. 进入 **工具 > Photon > 授权**（不同 Dify 版本的文案可能不同）。在 **Photon environment** 中选择与凭据匹配的环境：**Production**（`https://api.photon.codes`，默认）或 **Staging**（`https://api.staging.photon.codes`），再配置下表中的其他凭据并保存。API 密钥、项目、发送者和会话 ID 必须属于所选环境。保存时只向所选地址发起一次经过认证的只读请求，最多读取项目中的一个会话；项目为空也有效。插件不会自行切换环境。
6. 在 Workflow、Chatflow 或 Agent 中添加 Photon 工具节点。发送前先用 `list_spaces` 找到正确的现有会话。

| 凭据 | 是否必填 | 含义 |
|---|---|---|
| `api_origin` | 提供默认值 | 环境选择器，只接受 `https://api.photon.codes`（生产，默认）或 `https://api.staging.photon.codes`（预发布）。 |
| `api_key` | 是 | 原始 Account Service Key 或 Project API key，Dify 中以秘密输入保存。 |
| `project_id` | 是 | 所有请求使用的完整 `pho_prj_` 项目 ID。 |
| `default_sender_id` | 否 | `send_message` 未传 `sender_id` 时使用的完整 `pho_usr_` 代理用户 ID。建议填最常用的发送代理，在其他渠道发送时传入 `sender_id`。 |

环境选择器只接受这两个完全匹配的源地址，拒绝任意 URL、末尾斜杠、路径、查询字符串、片段和自定义端口。已有凭据省略 `api_origin` 时使用生产环境。凭据属于提供方设置，不作为面向模型的工具参数。

## 使用示例

以下 ID 仅为格式有效的示例，需要替换成实际项目中的 ID。所有输出为结构稳定、使用 snake_case 字段的 JSON；不存在的标量为 `null`，不存在的列表为空数组。时间戳以 RFC 3339 格式原样放在对应的 snake_case 字段中。输出中的每条消息和每个会话都带有 `platform` 字段。

每个工具还会为结果中非保留的顶层字段输出同名变量，其值与 JSON 完全一致。Dify 保留 `text`、`files` 和 `json`，这些名称不会作为变量输出。消息文本仍保留在 JSON 中：单条消息的结果为 `json[0].text`，消息列表结果则保留在各条消息项内。例如工具节点 ID 为 `send` 时，结束节点可以使用 `["send", "id"]` 或 `["send", "status"]` 选择器；完整 JSON 输出仍然保留。`content`、`timestamps`、`failure` 等嵌套对象，`items`、`attachment_ids` 等数组，以及空列表、布尔值和 `null` 都按原类型传递，不展开为多个字段，也不转换为字符串。

### 消息字段

`send_message`、`list_messages` 和 `get_message` 返回的消息字段相同：

| 字段 | 含义 |
|---|---|
| `id`、`platform`、`space_id` | 消息 ID、所属渠道和所属会话。 |
| `direction` | 入站消息为 `received`，任意投递状态的出站消息为 `sent`。 |
| `type` | Photon 的内容类型，例如 `text`、`attachment`、`group`、`voice` 或 `reaction`。 |
| `text` | `text` 消息的文字，或 `group` 中各文字部分按换行拼接的结果；其他情况为 `null`。 |
| `attachment_ids` | `attachment` 和 `voice` 内容中的附件 ID，包括 `group` 内的附件。可传给 `get_attachment`。 |
| `content` | Photon 的内容对象，字段名转为 snake_case，适用于所有内容类型。 |
| `parent_message_id` | 被回复的消息 ID，没有时为 `null`。 |
| `status`、`delivery_confirmed` | 权威状态，所有渠道都是 `received`、`dispatched`、`accepted`、`delivered` 或 `failed`。只有 `delivered` 时 `delivery_confirmed` 才为 `true`。 |
| `timestamps` | 始终包含 `created_at`、`updated_at`、`received_at`、`dispatched_at`、`accepted_at`、`delivered_at` 和 `failed_at`，尚未发生的节点为 `null`。 |
| `failure` | 可用时为 Photon 的 `code`、`message` 和 `confirmed_recipient_count`，否则为 `null`。 |

### 1. 发送消息

发送文字（已配置默认发送者）：

```json
{
  "space_id": "pho_spc_00000000000000000000000001",
  "type": "text",
  "text": "Hello from my Dify workflow.",
  "idempotency_key": "order-1042-confirmation-v1"
}
```

发送图片，渠道允许时可以在同一条消息里附带文字：

```json
{
  "space_id": "pho_spc_00000000000000000000000001",
  "type": "attachment",
  "attachments": ["<来自 Dify 文件变量的图片>"],
  "text": "Your order has shipped.",
  "idempotency_key": "order-1042-photos-v1"
}
```

如需换一个代理发送、回复已有消息或设置邮件主题，可以加上：

```json
{
  "sender_id": "pho_usr_00000000000000000000000001",
  "parent_message_id": "pho_msg_00000000000000000000000001",
  "email_subject": "Your order 1042"
}
```

`space_id` 和 `type` 必填，`type` 默认为 `text`，取 Photon 的内容类型 `text` 或 `attachment`：

- `text`：必须提供 `text`，不能带附件。文本原样以 `{ "type": "text", "format": "plain", "text": "..." }` 发送。
- `attachment`：`attachments` 中至少要有一个文件，每个文件都必须是 JPEG、PNG、GIF 或 WebP 图片，且不超过 10 MB（与 Dify 默认的图片上传上限一致），否则在向 Photon 发送任何内容之前就会被拒绝。每张图片先上传到 Photon，再按附件 ID 引用。只有一张图片且没有文字时，以 `{ "type": "attachment", "attachmentId": "pho_att_..." }` 发送；多张图片，或图片加文字时，以一条 `group` 消息发送，各部分依次是按顺序排列的图片，最后是文字。

除了这些检查，各渠道接受哪些内容由 Photon 决定，被拒绝时工具会给出 Photon 的错误码。Photon 目前在 iMessage、短信（以 MMS 发送）和 Telegram 上发送图片；WhatsApp、WhatsApp Business 和电子邮件会话只接受文字，在这些渠道发送图片会返回 `UNSUPPORTED_CONTENT`。iMessage 也不接受在一条消息中同时包含文字和附件，需要把图片和文字分成两条消息发送。

渠道由会话决定。`sender_id` 默认使用提供方的 `default_sender_id`，两者必须至少有一个，且必须是与会话同一渠道的代理。文本不能为空白，长度不超过 10,000 个字符；这是插件的安全上限，不是 Photon 的上限，个别渠道可能接受得更少。`parent_message_id` 用于回复一条已有消息。Photon 目前只在电子邮件和 Telegram 上支持回复；iMessage、短信、WhatsApp 和 WhatsApp Business 会话会以 `SPACE_NOT_SENDABLE` 拒绝。`email_subject` 可选，最多 4,096 个字符，只用于电子邮件会话，其他渠道请留空。

省略或留空 `idempotency_key` 时会生成 UUID。自行提供的键必须是 1 至 255 个不含空格的可见 ASCII 字符。每张图片上传时使用由发送幂等键和图片位置派生的幂等键，因此用相同的键和相同的图片重试时，会重复完全相同的上传请求，Photon 会返回已经提交过的附件。结果包含上述消息字段以及 `idempotency_key`。

**HTTP 202 只表示已成功提交，不代表已投递。** `dispatched` 和 `accepted` 都不是投递确认，只有 Photon 返回 `delivered` 时 `delivery_confirmed` 才为 `true`。发送后请用 `get_message` 查询。插件不会自动重试，也不会在后台轮询。可能重试的工作流应事先提供稳定的键，并且只在请求正文完全相同时复用；用同一个键发送不同正文会被 Photon 拒绝（`IDEMPOTENCY_KEY_REUSED`）。超时或连接失败后，消息可能已经提交，请先查看历史或状态再决定是否手动重试。调用失败时，自动生成的键无法找回。

发送失败时会给出 Photon 的错误码和简短提示，例如 `SMS_CAMPAIGN_NOT_ELIGIBLE`、`SHARED_LINE_INBOUND_REQUIRED`、`SPACE_NOT_SENDABLE`、`UNSUPPORTED_CONTENT`、`PAYLOAD_TOO_LARGE` 或 `MESSAGE_TOO_LONG`。

### 2. 查看会话

```json
{
  "platform": "whatsapp_business",
  "page_size": 20,
  "participant_handle": "+14155550123",
  "order": "desc"
}
```

所有参数都可选。`platform` 取 `imessage`、`sms`、`whatsapp`、`whatsapp_business`、`email` 或 `telegram` 之一，省略时列出所有渠道。`page_size` 默认 20，必须是正整数，上限 100。`participant_handle` 接受最长 320 个字符的电话号码或电子邮箱，匹配时不区分大小写。`order` 默认 `desc`，也可以是 `asc`。

输出为 `{ "items": [...], "next_page_token": null }`。每个会话包含 `id`、`platform`、`kind`、`participant_ids`、`created_at` 和 `updated_at`。如果返回了令牌，请在其他筛选条件不变的情况下作为 `page_token` 传入，一直查询到 `next_page_token` 为 `null`，即使某一页为空也要继续。

### 3. 查看消息

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

所有参数都可选。`platform` 的用法与 `list_spaces` 相同。`direction` 取 Photon 的 `received` 或 `sent`，省略时两个方向都返回。`order` 默认 `desc`，也可以是 `asc`。`page_size` 默认 20，上限 200。时间必须是带时区的 RFC 3339 格式，下限包含、上限不包含，且下限必须早于上限。分页方式与 `list_spaces` 相同。

输出包含 `items`（字段见上文的消息字段）、`next_page_token`、`scanned_count` 和 `space_filter_applied_locally`。

Photon API 在服务端按 `spaceId` 筛选时要求提供资源或用户视角，而用户视角不能和渠道或时间筛选同时使用。为了保留本工具的参数，插件会按渠道、方向、排序和时间条件读取一页项目消息，再在本地应用 `space_id` 筛选。因此 `page_size` 限制的是读取的项目消息数，筛选后的结果可能更少甚至为空。**只要 `next_page_token` 不为 null，就要继续翻页，空页之后也一样。** 插件不会隐式扫描多页，也不会发出额外请求。

### 4. 获取消息

```json
{
  "message_id": "pho_msg_00000000000000000000000001"
}
```

`message_id` 必填。输出为一条消息，字段见上文，包括内容、权威状态、所有时间戳字段和 `failure`。获取消息永远不会再次发送消息。

### 5. 获取附件

```json
{
  "attachment_id": "pho_att_00000000000000000000000001"
}
```

`attachment_id` 必填，来自消息的 `attachment_ids`。输出包含 `id`、`filename`、`content_type`、`size_bytes` 和 `created_at`，文件本身作为 Dify 文件输出返回，例如可以把图片传给视觉模型。如果 Photon 仍在处理该文件，工具会给出 `ATTACHMENT_NOT_READY`，请稍后重试。

## 网络连接要求

- 允许通过 TCP 443 端口向所选环境发起经过证书验证的 HTTPS 出站请求：生产环境为 **`api.photon.codes`**，预发布环境为 **`api.staging.photon.codes`**。两个主机都已在 `manifest.yaml` 中声明。
- 发往 Photon 的请求只使用所选源地址加固定的 `/v1/projects/{project_id}` 前缀。插件拒绝重定向，也不会自动切换到另一个环境，不接受任意 URL 或附加路径。
- 发往 Photon 的请求连接超时为 5 秒、读取超时为 15 秒，每个请求约 20 秒。这是传输层的空闲限制，不是严格的总耗时保证。
- 发往 Photon 的请求忽略环境中的代理和 `.netrc` 设置，请为所选主机配置直连出站。
- 发送图片时，Dify 插件 SDK 还会从 Dify 为每张图片提供的地址下载图片：存放在 Dify 中的文件使用 Dify 的文件地址（见前提条件），工作流通过 URL 收到的文件使用原始 URL。除此之外，插件只与 Photon 通信，由 Photon 通过各渠道自己的网络投递消息。

## 安全

插件在调用 API 之前会校验完整的 Photon ID 格式、发送者是否可用、渠道取值、内容 `type` 及其要求的输入、每个附件是否为不超过 10 MB 的 JPEG、PNG、GIF 或 WebP 图片、文本非空及本地长度上限、邮件主题长度、分页大小、游标格式、时间范围、方向、排序和幂等键。项目归属、权限、会话所属渠道、发送者授权以及各渠道接受哪些内容仍以 Photon 为准。

发往 Photon 的请求只访问所选的白名单 Photon API 源地址：生产环境 `https://api.photon.codes` 或预发布环境 `https://api.staging.photon.codes`。在发起任何请求前都会做完全一致的字符串匹配，格式错误的源地址、任意主机、路径、用户信息、查询字符串、片段和自定义端口都会被拒绝。项目路径前缀固定，且只能调用七个 Photon 操作：列出会话、列出消息、读取单条消息、发送消息、上传附件、读取附件信息、下载附件内容。TLS 证书验证始终开启，重定向和自动重试均已禁用。插件不访问文件系统、不执行子进程、不执行任意代码，也不做持久化存储；图片内容只在内存中处理，插件不会保存。

提供方凭据由 Dify 的凭据存储管理。插件只在内存中使用凭据构造 Bearer 授权头，不记录密钥或完整请求头。API 返回的 `application/problem+json` 错误只会转换为 HTTP 状态、白名单内的 Photon 错误码和简短提示，绝不回显任意错误正文或传输层异常文本。即使 API 在消息文本或失败详情中回显，JSON 输出中的已配置 API 密钥和可识别的 Photon 密钥字符串也会被打码。Dify 可能按自身设置保留工作流的输入、输出、文件和日志。详见 [PRIVACY.md](../PRIVACY.md)。

发送消息属于对外的写操作。请区分异步提交和确认投递，并使用由调用方控制的幂等键避免重复发送。

## 限制

- 只支持现有会话：不支持新建会话、开通线路、语音通话、入站触发、后台轮询或投递 webhook。
- 发送只支持文字和不超过 10 MB 的 JPEG、PNG、GIF、WebP 图片（Photon 的 `text` 和 `attachment` 内容类型），不发送语音消息、表情回应和其他文件。读取消息时会返回所有内容类型。
- 各渠道自身的规则仍然适用。共享 iMessage 线路只能在单聊中发给分配之后给该线路发过消息的人；iMessage 不接受在一条消息中同时包含文字和附件；WhatsApp、WhatsApp Business 和电子邮件只接受文字，且只有电子邮件和 Telegram 支持回复；短信需要 campaign 资格，除非所有收件人都在网内；Telegram bot 不能主动与用户发起会话，也不能向自己不在的群组发送，Photon 会把这类发送标记为失败。
- 一个默认发送者只对应一个渠道。在其他渠道发送时，如果代理不是 `default_sender_id`，请传入 `sender_id`。
- Photon 的列表结果是最终一致的。历史为空或延迟出现，不能证明投递失败。
- 按会话筛选的消息结果是上文所述的项目分页扫描。
- 提供方校验只验证读取权限，不验证能否以每个代理身份发送；项目为空也能通过，且不会发送测试消息。

## 源码与开发

源码仓库：[photon-hq/dify](https://github.com/photon-hq/dify)。问题可以在仓库中反馈，也可以发邮件到 `manifest.yaml` 中的联系人邮箱。

运行时依赖在两个依赖文件中都精确固定为 `dify-plugin==0.10.2` 和 `requests==2.33.1`。SDK 0.10.2 要求 Requests >=2.33.1。

使用 Python 3.12 安装依赖后，在源码根目录运行测试：

```sh
python -m unittest discover -s tests -v
```

测试在 HTTPS 传输层模拟 Photon，并模拟 Dify 的文件下载，覆盖 SDK 注册、凭据、全部五个工具、全部六个渠道、文字和图片发送、附件上传与下载、生产与预发布环境选择、拒绝其他源地址以及错误处理。如果把 `PHOTON_OPENAPI` 设为 Photon OpenAPI 文档的路径（并安装 `jsonschema`），测试还会按官方结构校验请求和测试数据，并按各工具的输出结构校验工具输出。测试不会发送真实消息，测试和构建工具都不会打进插件包。

## 许可证

MIT License，Copyright (c) 2026 gtxy27。完整英文许可文本随主 [README.md](../README.md#license) 提供，允许使用、复制、修改和分发，须保留版权与许可声明，软件按现状提供，不作担保。
