# Photon Dify 触发器

通过 [Photon](https://photon.codes) 的消息 API，在 iMessage、短信（SMS）、WhatsApp、WhatsApp Business、电子邮件或 Telegram 收到消息时启动 Dify 工作流。

Photon 把会话称为 *space*。每个会话只属于一个渠道，项目自己的电话号码、机器人和邮箱账号是它的 *agent 用户*。项目收到消息时，Photon 会推送一条带签名的 `message.received` webhook，本插件据此启动使用该事件的工作流。要回复，请使用 [Photon 插件](https://github.com/photon-hq/dify)的 `send_message`。

## 事件

| 事件 | 触发时机 |
|---|---|
| `message_received` | 项目收到消息（Photon 的 `message.received`）。 |

## 配置

1. 在 Photon 项目中连接要使用的渠道。插件不会连接渠道。
2. 创建有权管理项目推送地址（webhook destination）的 Account Service Key（`pho_ask_`）或 Project API key（`pho_sk_`），并复制项目 ID（`pho_prj_`）。
3. 安装 **Photon 触发器**，把它的 **收到消息** 事件作为工作流的开始节点，并用以下凭据创建订阅：

| 凭据 | 是否必填 | 取值 |
|---|---|---|
| `api_origin` | 是 | 与密钥匹配的生产环境（`https://api.photon.codes`，默认）或预发布环境（`https://api.staging.photon.codes`）。 |
| `api_key` | 是 | 原始密钥，不要加 `Bearer`。 |
| `project_id` | 是 | 项目 ID。 |

创建订阅时，插件会为该订阅的 Dify 地址创建一个订阅了 `message.received` 的 Photon 推送地址，Dify 会把推送地址的签名密钥和订阅一起保存。删除订阅时，推送地址也会被删除。

Photon 只向公网 HTTPS 地址推送。在自部署的 Dify 上，创建订阅前请把 `TRIGGER_URL` 设为 Dify API 的公网 HTTPS 地址，因为 Dify 用它生成订阅的地址。

## 使用

事件的变量就是 webhook 中 Photon 的消息对象：`id`、`platform`、`space`、`sentBy`、`receivedBy`、`content`、`status`、`timestamps`、`createdAt`，回复类消息另有 `parentMessageId`。`content.type` 表示收到的内容类型；文字消息的正文在 `content.text`，附件的 ID 在 `content.attachmentId`，可传给 Photon 插件的 `get_attachment`。除了文字和附件，`message.received` 还可能是表情回应（`reaction`）、编辑（`text.update`）、撤回（`message.delete`）、已读回执（`message.read`）或投票（`poll`）等，它们同样会启动工作流；只想回复文字时，请按 `content.type` 分支。

要在同一会话中回复，把以下参数传给 Photon 插件的 `send_message`：

```json
{
  "space_id": "<事件的 space.id>",
  "sender_id": "<事件的 receivedBy.id>",
  "type": "text",
  "text": "收到，我们会尽快回复您。",
  "idempotency_key": "<事件的 id>.reply"
}
```

`receivedBy` 是收到这条消息的项目 agent 用户，所以回复会从同一个号码、机器人或邮箱账号发出。推送超时或失败时，Photon 会再推送一次同一条消息；用消息的 `id` 生成幂等键，重复推送时就不会再发一次回复。

事件有三个可选参数，在开始节点上设置：**渠道**（只处理选中的渠道；不选表示全部）、**内容包含**（不区分大小写）和**内容正则**。不满足条件的消息会被跳过，不启动工作流；设置了**内容包含**时，没有正文的消息会被跳过。

每次推送都会先校验 Photon 的签名，再启动工作流：按 Standard Webhooks 规范，对推送的 ID、时间戳和正文做 HMAC-SHA256 签名，且时间戳须在 5 分钟以内。校验失败的推送不会启动任何工作流。

## 网络连接要求

插件会向所选的 Photon 主机 `api.photon.codes` 或 `api.staging.photon.codes` 发起 HTTPS 请求，用于校验密钥、创建和删除推送地址。Photon 会把推送发到订阅的 Dify 地址。

## 限制

- 只有收到的消息会启动工作流；投递状态等其他 Photon 事件不会。
- 一个订阅会收到项目的所有 `message.received`。只想处理其中一部分时，请使用事件参数；只处理某一个号码时，在工作流里按 `receivedBy.id` 分支。
- 订阅保存的是创建时 Photon 返回的签名密钥。如果在 Photon 轮换了推送地址的密钥，旧密钥失效后推送将无法通过校验；请删除并重新创建订阅。
- 删除订阅时如果连不上 Photon，Dify 仍会删除订阅，Photon 上的推送地址会保留下来；请到 Photon 删除它。

## 隐私

见 [PRIVACY.md](../PRIVACY.md)。

## 开发

源码：[photon-hq/dify](https://github.com/photon-hq/dify) 的 `trigger/` 目录。使用 Python 3.12，在 `trigger/` 下运行：

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

测试会模拟 Photon，不会创建真实的推送地址。

## 许可证

[MIT](https://github.com/photon-hq/dify/blob/main/LICENSE)
