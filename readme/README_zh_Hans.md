# Photon Dify 插件

通过 [Photon](https://photon.codes) 的消息 API（[API 参考](https://photon.codes/docs/beta/api-reference)），在 Dify 的 Workflow、Chatflow 和 Agent 中收发 iMessage、短信（SMS）、WhatsApp、WhatsApp Business、电子邮件和 Telegram 消息。

Photon 把会话称为 *space*。每个会话只属于一个渠道（`imessage`、`sms`、`whatsapp`、`whatsapp_business`、`email` 或 `telegram`），向会话发送的消息会走该渠道，所以同一套工具适用于所有渠道。

## 工具

| 工具 | 作用 | Photon API |
|---|---|---|
| `send_message` | 向现有会话发送文字（`type: text`），或每张不超过 10 MB 的 JPEG、PNG、GIF、WebP 图片（`type: attachment`）。 | [Upload attachment](https://photon.codes/docs/beta/api-reference/attachments/upload-attachment)、[Send a Message](https://photon.codes/docs/beta/api-reference/messages/send-a-message) |
| `list_spaces` | 查看会话，可按渠道或参与者筛选。 | [List Spaces](https://photon.codes/docs/beta/api-reference/spaces/list-spaces) |
| `create_or_get_space` | 返回指定用户在一个渠道上的会话，没有时新建。 | [Create or get a Space](https://photon.codes/docs/beta/api-reference/spaces/create-or-get-a-space) |
| `list_messages` | 按渠道、方向和创建时间查看消息，或查看单个会话的消息。 | [List Messages](https://photon.codes/docs/beta/api-reference/messages/list-messages) |
| `get_message` | 获取一条消息及其发送者、内容和投递状态。 | [Get a Message](https://photon.codes/docs/beta/api-reference/messages/get-a-message) |
| `get_user` | 获取一个用户的联系方式，以及它是 agent 用户（Photon 托管的号码或账号）还是普通联系人。 | [Get an User](https://photon.codes/docs/beta/api-reference/users/get-an-user) |
| `create_or_get_user` | 返回一个渠道上某个电话号码或电子邮箱对应的用户，Photon 还没有时新建。 | [Create or get a User](https://photon.codes/docs/beta/api-reference/users/create-or-get-a-user) |
| `get_attachment` | 获取附件的元数据，并以 Dify 文件返回附件本身。 | [Get attachment](https://photon.codes/docs/beta/api-reference/attachments/get-attachment)、[Download attachment](https://photon.codes/docs/beta/api-reference/attachments/download-attachment) |

## 配置

1. 在 Photon 项目中连接要使用的渠道（[Messaging](https://photon.codes/docs/beta/messaging)）。插件不会连接渠道。
2. 创建 Account Service Key（`pho_ask_`）或 Project API key（`pho_sk_`），并复制项目 ID（`pho_prj_`）（[Set up your project](https://photon.codes/docs/beta/get-started/project)）。
3. 从 Dify Marketplace 安装 **Photon**，然后在 **工具 > Photon** 中授权：

| 凭据 | 是否必填 | 取值 |
|---|---|---|
| `api_key` | 是 | 原始密钥，不要加 `Bearer`。 |
| `project_id` | 是 | 项目 ID。 |

在自部署的 Dify 上，需要把 `INTERNAL_FILES_URL`（或 `FILES_URL`）设为插件能访问到的 Dify API 地址，否则插件无法下载要发送的图片。

## 使用

发送文字，或发送图片并附带可选的文字：

```json
{
  "space_id": "pho_spc_…",
  "sender_id": "pho_usr_…",
  "type": "attachment",
  "format": "plain",
  "attachments": ["<来自 Dify 文件变量的图片>"],
  "text": "您的订单已发货。",
  "idempotency_key": "order-1042-photos-v1"
}
```

- 多张图片，或图片加文字，会作为一条 `group` 消息发送：文字在前，图片按顺序在后。每张图片会先上传到 Photon，再发送消息。
- `sender_id` 是该会话中项目的 agent 用户：该会话中收到的消息的 `receivedBy.id`，或从该会话发出的消息的 `sentBy.id`。可用 `get_user` 区分 agent 用户（`kind: agent`）和普通联系人；本项目的专属号码带 `details.resourceId`。
- `parent_message_id`（回复）和 `email_subject` 是可选的。
- `type` 和 `format` 都必填，没有默认值。`format` 取 `plain`（按原样发送文字）或 `markdown`，即 CommonMark，以及 GFM 的表格和删除线。渠道支持格式时（例如 Telegram），Photon 用该渠道自己的格式显示 Markdown，不支持时转成易读的纯文本；Markdown 中不能包含 HTML。
- 各渠道接受什么内容由 Photon 决定。Photon 拒绝发送时，错误信息会保留 Photon 返回的状态码、错误码和原因，例如 `Photon API HTTP 422 (UNSUPPORTED_CONTENT): …`。各错误码见 Photon 的[错误码目录](https://photon.codes/docs/beta/problems/catalog)。
- 发送是异步的：结果通常是 `dispatched`。之后可调用 `get_message` 查看：`delivered` 表示已确认送达；`accepted` 表示渠道已接收但没有确认送达，原因见 `acceptance.code`；`failed` 时原因见 `failure`。
- 使用同一个 `idempotency_key` 可以安全地重试发送。省略时插件会生成一个，在结果中返回；发送失败时也会写在错误信息里。

要与新的联系人发起会话，先用 `create_or_get_user` 获取对方的用户，再用 `create_or_get_space` 获取会话，然后向该会话发送：

```json
{"platform": "sms", "handle": "+14155550123"}
{"platform": "sms", "participant_ids": "pho_usr_<agent 用户>,pho_usr_<联系人>"}
```

- `participant_ids` 必须包含负责发送的项目 agent 用户：该号码上收到的消息的 `receivedBy.id`，或用 `create_or_get_user` 查询该号码本身得到的用户（`kind: agent`）。在 iMessage 上，请把 agent 用户放在第一位。新建 iMessage 会话需要项目的专属号码；共享号码只会返回与已分配给本项目的联系人的已有单聊。
- Photon 已有的联系方式会返回已有的用户；参与者相同的单聊和短信群聊会返回已有会话。电子邮件中，每个新的 `idempotency_key` 都会开启一个新线程。

列表工具返回 Photon 的分页结果：`items`，还有更多结果时另有 `nextPageToken`。要获取下一页，把它作为 `page_token` 传入，其他筛选条件保持不变。要查看单个会话的消息，请同时传入 `space_id` 和 `perspective_user_id`（该会话中项目所属的 agent 用户）；此时 Photon 不接受 `platform`、`created_since` 和 `created_before`。

结果就是 API 返回的 Photon 原始对象。消息包含 `id`、`platform`、`space`、`sentBy`、Photon 记录到的 `receivedBy`、`content`、`parentMessageId`、`status`、`timestamps`，以及适用时的 `acceptance` 或 `failure`；文字消息的正文在 `content.text`。结果的每个顶层字段都会同时作为同名输出变量。

`get_attachment` 以 Dify 文件输出返回附件，供工作流使用，例如传给视觉模型；在 Agent 应用里，模型看不到这个文件。超过 50 MB（Dify 对插件返回文件的默认上限）的文件不会下载。

## 网络连接要求

插件会向 Photon 的 `api.photon.codes` 发起 HTTPS 请求，并从 Dify 提供的地址下载要发送的图片。

## 限制

- 收到消息时启动工作流，由单独的 Photon 触发器插件负责，源码在本仓库的 `trigger/`。不包括投递状态回调。
- Photon 不能在 Telegram 上新建用户或会话（`OPERATION_UNAVAILABLE`）；Telegram 会话要由对方先给机器人发消息。
- 发送支持文字和图片，读取支持所有内容类型。
- 经典 Agent 应用不能把文件传给工具，所以只能发文字；工作流和新版 Agent 可以发图片。

## 隐私

见 [PRIVACY.md](../PRIVACY.md)。

## 开发

源码：[photon-hq/dify](https://github.com/photon-hq/dify)。使用 Python 3.12：

```sh
pip install -r requirements.txt ruff==0.15.0
ruff check .
ruff format --check .
python -m unittest discover -s tests
```

测试会模拟 Photon 和 Dify 的文件下载，不会发送真实消息。

每次合并到 `main` 都会发布一个 GitHub 预发布版本，其中包含 staging 构建和正式候选。正式版需要手动运行 **Promote to production** 工作流发布。

## 许可证

[MIT](../LICENSE)
