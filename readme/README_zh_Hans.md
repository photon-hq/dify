# Photon Dify 插件

通过 [Photon](https://photon.codes) 的消息 API，在 Dify 的 Workflow、Chatflow 和 Agent 中收发 iMessage、短信（SMS）、WhatsApp、WhatsApp Business、电子邮件和 Telegram 消息。

Photon 把会话称为 *space*。每个会话只属于一个渠道（`imessage`、`sms`、`whatsapp`、`whatsapp_business`、`email` 或 `telegram`），向会话发送的消息会走该渠道，所以同一套工具适用于所有渠道。

## 工具

| 工具 | 作用 |
|---|---|
| `send_message` | 向现有会话发送文字（`type: text`），或每张不超过 10 MB 的 JPEG、PNG、GIF、WebP 图片（`type: attachment`）。 |
| `list_spaces` | 查看会话，可按渠道或参与者筛选。 |
| `list_messages` | 按渠道、方向、创建时间和会话查看消息。 |
| `get_message` | 获取一条消息及其内容和投递状态。 |
| `get_attachment` | 获取附件的元数据，并以 Dify 文件返回附件本身。 |

## 配置

1. 在 Photon 项目中连接要使用的渠道。插件只向现有会话发送，不会连接渠道或新建会话。
2. 创建 Account Service Key（`pho_ask_`）或 Project API key（`pho_sk_`），并复制项目 ID（`pho_prj_`）。记下每个要发送的渠道上负责发送的代理用户 ID（`pho_usr_`）；Photon 的用户只属于一个渠道。
3. 从 Dify Marketplace 安装 **Photon**，然后在 **工具 > Photon** 中授权：

| 凭据 | 是否必填 | 取值 |
|---|---|---|
| `api_origin` | 是 | 与密钥匹配的生产环境（`https://api.photon.codes`，默认）或预发布环境（`https://api.staging.photon.codes`）。 |
| `api_key` | 是 | 原始密钥，不要加 `Bearer`。 |
| `project_id` | 是 | 项目 ID。 |
| `default_sender_id` | 否 | `send_message` 未传 `sender_id` 时使用的代理用户 ID。 |

在自部署的 Dify 上，需要把 `INTERNAL_FILES_URL`（或 `FILES_URL`）设为插件能访问到的 Dify API 地址，否则插件无法下载要发送的图片。

## 使用

发送文字，或发送图片并附带可选的文字：

```json
{
  "space_id": "pho_spc_…",
  "type": "attachment",
  "attachments": ["<来自 Dify 文件变量的图片>"],
  "text": "您的订单已发货。",
  "idempotency_key": "order-1042-photos-v1"
}
```

- 多张图片，或图片加文字，会作为一条 `group` 消息发送：文字在前，图片按顺序在后。每张图片会先上传到 Photon，再发送消息。
- `sender_id`、`parent_message_id`（回复）和 `email_subject` 都是可选的。
- 各渠道接受什么内容由 Photon 决定。Photon 拒绝发送时，错误信息会保留 Photon 返回的状态码、错误码和原因，例如 `Photon API HTTP 422 (UNSUPPORTED_CONTENT): …`。
- 发送是异步的：结果通常是 `dispatched`。之后请调用 `get_message`，只有 `delivered` 才会把 `delivery_confirmed` 设为 `true`。
- 使用同一个 `idempotency_key` 可以安全地重试发送。省略时插件会生成一个，在结果中返回；发送失败时也会写在错误信息里。

列表工具返回 `items` 和 `next_page_token`。请把令牌作为 `page_token` 传回，并保持筛选条件不变，直到令牌为 `null`，即使某一页为空也要继续。`list_messages` 会在读取的每一页内按 `space_id` 筛选，所以一页中的匹配结果可能少于 `page_size`。

消息包含 `id`、`platform`、`space_id`、`direction`（`received` 或 `sent`）、`type`、`text`、`attachment_ids`、`content`（Photon 原始结构的完整内容）、`parent_message_id`、`status`、`delivery_confirmed`、`timestamps` 和 `failure`。每个结果的顶层字段都会同时作为同名输出变量，但消息的 `text` 例外：消息有文本时，它填入 Dify 自带的 `text` 输出。列表工具的顶层字段是 `items` 和 `next_page_token`，每条消息的字段都在 `items` 里。

`get_attachment` 以 Dify 文件输出返回附件，例如可传给视觉模型。超过 50 MB（Dify 对插件返回文件的默认上限）的文件不会下载。

## 网络连接要求

插件会向所选的 Photon 主机 `api.photon.codes` 或 `api.staging.photon.codes` 发起 HTTPS 请求，并从 Dify 提供的地址下载要发送的图片。

## 限制

- 只能使用现有会话；不能新建会话，没有入站触发器或投递回调。
- 发送支持文字和图片，读取支持所有内容类型。
- 一个默认发送者只对应一个渠道；在其他渠道发送时请传入 `sender_id`。

## 隐私

见 [PRIVACY.md](../PRIVACY.md)。

## 开发

源码：[photon-hq/dify](https://github.com/photon-hq/dify)。使用 Python 3.12：

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

测试会模拟 Photon 和 Dify 的文件下载，不会发送真实消息。

## 许可证

[MIT](../LICENSE)
