# Photon Dify 机器人

通过 [Photon](https://photon.codes) 的消息 API（[API 参考](https://photon.codes/docs/beta/api-reference)），用 Dify 的 Chatflow 或聊天助手应用回复 iMessage、短信（SMS）、WhatsApp、WhatsApp Business、电子邮件和 Telegram 上的消息。

Photon 把会话称为 *space*。每个会话只属于一个渠道，项目自己的电话号码、机器人和邮箱账号是它的 *agent 用户*。项目收到消息时，Photon 会向本插件的 API 端点推送一条带签名的 `message.received` webhook。插件把消息的文字交给端点设置中选择的应用，再以收到这条消息的 agent 用户的身份，把应用的回答发回同一个会话。每个会话对应一个 Dify 对话，所以应用回答时会参考该会话之前的消息。

## 配置

1. 在 Photon 项目中连接要使用的渠道（[Messaging](https://photon.codes/docs/beta/messaging)）。插件不会连接渠道。
2. 创建能在该项目中发送消息的 Account Service Key（`pho_ask_`）或 Project API key（`pho_sk_`）（[Set up your project](https://photon.codes/docs/beta/get-started/project)）。
3. 安装 **Photon 机器人**，并为它添加一个 API 端点，设置如下：

| 设置 | 是否必填 | 取值 |
|---|---|---|
| `api_origin` | 是 | 与密钥匹配的生产环境（`https://api.photon.codes`）或预发布环境（`https://api.staging.photon.codes`）。 |
| `api_key` | 是 | 原始密钥，不要加 `Bearer`。用于发送回复。 |
| `signing_secret` | 否 | 第 5 步之前留空。 |
| `app` | 是 | 负责回答的 Chatflow 或聊天助手应用。在这里设置的输入会随每条消息传给应用。 |

4. 复制 Dify 显示的端点地址（以 `/` 结尾），在 Photon 项目中为它创建一个推送地址（webhook destination），订阅 `message.received`，API 版本为 `2026-07-01`。请完全按 Dify 显示的地址填写：Photon 不会跟随重定向。使用 Photon 的 [Create webhook destination](https://photon.codes/docs/beta/api-reference/webhook-destinations/create-webhook-destination)：

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

5. 把推送地址的签名密钥（`signingSecret`，`whsec_…`，只在创建推送地址时返回）填入端点的 `signing_secret` 并保存。

签名密钥保存之前，端点会拒绝所有推送，Photon 也不会重试被拒绝的推送。

Photon 只向公网 HTTPS 地址推送。在自部署的 Dify 上，请把 `ENDPOINT_URL_TEMPLATE` 设为 Dify 的公网 HTTPS 地址，例如 `https://dify.example.com/e/{hook_id}`，因为 Dify 用它生成显示的端点地址。

## 使用

有人向项目的 Telegram 机器人发送“你们几点营业？”时，Photon 推送的内容如下（节选）：

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
      "content": {"type": "text", "format": "plain", "text": "你们几点营业？"}
    }
  }
}
```

插件把文字作为 query 发给应用，放在它为 `pho_spc_S` 和该应用保存的对话中；会话的第一条消息会开启新对话。然后用 Photon 的 [Send a Message](https://photon.codes/docs/beta/api-reference/messages/send-a-message) 发送应用的回答：

```json
{
  "spaceId": "pho_spc_S",
  "senderId": "pho_usr_B",
  "content": {"type": "text", "format": "plain", "text": "<应用的回答>"}
}
```

幂等键为 `pho_msg_A.reply`，由收到的消息生成，所以 Photon 对每条消息最多只发送一条回复。

- 只回答文字内容（`content.type: text`）的 `message.received`。其他事件、其他内容（图片、语音、表情回应等），项目 agent 用户发出的消息，以及没有 `receivedBy` 的消息，都只确认收到、不回答。跳过 agent 用户发出的消息，可以避免它们互相回复；回复要以 `receivedBy` 的身份发出。
- 应用回答的文字为空时，不发送任何内容。
- 每次推送都会先校验 Photon 的签名，再做其他处理：按 Standard Webhooks 规范，对推送的 ID、时间戳和正文做 HMAC-SHA256 签名，且时间戳须在 5 分钟以内。校验失败的推送返回 HTTP 401，不会触发任何处理。

## 超时与重试

Photon 每次推送最多等待 20 秒，推送超时或失败时会重试；在这次推送结束之前，该推送地址后续的消息都要等待。插件在响应之前调用应用并发送回答，因此：

- 应用回答超过 20 秒时，回答可能发不出去。
- 每条消息最多回答一次。Photon 在超时或出错后再次推送同一条消息时，插件只确认收到，不会再次调用应用。应用调用或回复失败的消息不会得到回复，该会话的 Dify 对话保持不变。

## 网络连接要求

插件会向所选的 Photon 主机 `api.photon.codes` 或 `api.staging.photon.codes` 发起 HTTPS 请求以发送回复（[Send a Message](https://photon.codes/docs/beta/api-reference/messages/send-a-message)），并通过 Dify 调用所选应用。Photon 会把推送发到端点地址。

## 限制

- 只回答文字，回复为纯文本。
- 端点会回答其推送地址推送的所有文字消息，涵盖项目的所有渠道和号码。
- Agent 应用无法回答。Dify 1.17.1 会拒绝插件对 Agent 应用（`agent-chat`）的阻塞调用，也会以 `unexpected app type` 拒绝新版 Agent 运行时的应用（应用模式为 `agent`）。需要用工具时，请在 Chatflow 中添加工具节点或 Agent 节点。
- 在 Dify 1.17.1 中，如果删除了某个会话对应的对话，聊天助手应用会拒绝该会话之后的所有消息，因为 Dify 找不到这个对话；Chatflow 会自动开启新对话。
- 如果在 Photon 中轮换了推送地址的签名密钥，请在旧密钥失效前把新密钥保存到端点。

## 隐私

见 [PRIVACY.md](../PRIVACY.md)。

## 开发

源码：[photon-hq/dify](https://github.com/photon-hq/dify) 的 `bot/` 目录。使用 Python 3.12，在 `bot/` 下运行：

```sh
pip install -r requirements.txt
python -m unittest discover -s tests
```

测试会模拟 Photon 以及 Dify 的应用和存储调用，不会发送真实消息。

## 许可证

[MIT](https://github.com/photon-hq/dify/blob/main/LICENSE)
