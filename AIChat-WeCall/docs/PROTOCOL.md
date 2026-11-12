# AIChat v1.9.1 协议还原

包名 `com.ai.assistant.powerful.chat.bot`，样本 `AIChat v1.9.1 (PREMIUM) by aichat.apk`。
反编译产物在 `decom/sources`（18,583 类，PairIP 导致 29 处方法体缺失）。

## 1. 端点

| 方法 | URL | 用途 | 代码位置 |
|---|---|---|---|
| POST | `https://chatai.wecall.info/chat_stream` | 主聊天，SSE | `s3/k.java:120` |
| POST | `https://chatai.wecall.info/chat_role` | 角色聊天，SSE | `z3/i.java:133`、`z3/i.java:161` |
| GET | `https://chatai.wecall.info/prompts/get_new?lang=<lang>` | bot 目录，DES 密文 | `z3/l.java:449` |
| POST | `https://report.wecall.info/report.php` | 埋点上报 | `ji/b.java:105` |
| WebView | `https://chatai.wecall.info/chat_new` | H5 聊天页 | `AssistantActivity.java:1317` |
| WebView | `https://chatai.wecall.info/chat_role` | H5 角色页 | `z3/i.java:133` |
| — | `https://ipinfo.io/json` | 启动时取 IP/国家 | `StartActivity` |

同一族域名还有 `ss.seamobi.org`、`www.seamobitech.com`（隐私政策、广告 SDK 域名）。

## 2. `POST /chat_stream`

请求体（`RequestData`，Gson 序列化，字段名原样）：

```json
{
  "conversation": [{"answer": "上一轮回答", "question": "上一轮问题"}],
  "model": 3,
  "query": "本轮问题"
}
```

- `model` 取值来自 `key_chat_model`，缺省 3（`AssistantActivity.java:1279`）。
- 请求头只有两条：`Content-Type: application/json; charset=utf-8` 与
  `Accept: text/event-stream`（`s3/k.java:123-125`）。没有签名、没有 token。
- 空 `query` 时服务端返回 HTTP 500：
  `{"statusCode":500,"message":"Request parameter check error:query should not be empty"}`。

响应是 SSE，每个事件的 `data` 是 `StreamBean` JSON：

```json
{"content": "<base64 DES 密文或明文片段>", "conversation_id": "…", "event": "message"}
```

`event == "end"` 表示结束（`s3/a.java:129`）。`content` 会先过
`b9.b.a(key, iv, content)` 做 DES 解密再拼进回答（`s3/a.java:137`）。

## 3. `POST /chat_role`

请求体（`RequestBotParam`）：

```json
{
  "query": "问题",
  "user": "<设备 UUID，g.a.g()>",
  "id": "<bot id>",
  "conversationId": "<上次返回的会话 id，首次为空>",
  "response_mode": "streaming"
}
```

`response_mode` 必填，缺失时服务端返回
`{"statusCode":500,"message":"Request parameter check error:response_mode should not be empty"}`。
这个错误格式和字段名与 Dify 的 `/chat-messages` 契约一致，后端大概率是 Dify 的封装。

## 4. 加密层

响应解密（两处相同实现）：

- `z4/r.java`：`a(String key, String iv, String str)` → Base64 解码 → `DES/CBC/PKCS5Padding` 解密
- `b9/b.java`：字节级相同的实现，用于 SSE `content`

key/iv 来自 `z4/q`（`Parser`）的 `doGetKey` / `doGetIV`，二者都读 `assets/cid`——
一个 x86 的 32 位 ELF 文件（5,520 字节），`.rodata` 段长 15 字节：

```
7c 3d 02 65 78 67 04 7c 2a 02 65 78 67 04 59
```

这两个方法在默认 jadx 下被判为"Unsupported multi-entry loop pattern"跳过。
用 `jadx --show-bad-code` 重跑后（产物在 `decom/jadx-badcode`）完整实现拿到了。

`doGetKey` 依次拼接 8 个片段（`k l m n l o k p`），`doGetIV` 拼接另外 8 个（`c c d e f g h e`），
每个片段是一个 `"&#<十进制>"` 字面量（`z4/k.java` … `z4/p.java`），拼接后按 `&#` 切分，
逐段 `Integer.parseInt(s) ^ 65280` 再转 `char`：

| 片段类 | 字面量 | `^ 65280` | 字符 |
|---|---|---|---|
| `k` | `&#65330` | 50 | `2` |
| `l` | `&#65328` | 48 | `0` |
| `m` | `&#65329` | 49 | `1` |
| `n` | `&#65337` | 57 | `9` |
| `o` | `&#65336` | 56 | `8` |
| `p` | `&#65334` | 54 | `6` |
| `c` | `&#65328` | 48 | `0` |
| `d` | `&#65333` | 53 | `5` |
| `e` | `&#65329` | 49 | `1` |
| `f` | `&#65332` | 52 | `4` |
| `g` | `&#65331` | 51 | `3` |
| `h` | `&#65330` | 50 | `2` |

结果：

```
key = "20190826"      # k l m n l o k p
iv  = "00514321"      # c c d e f g h e
```

**实测验证**：用这对 key/iv 解 `GET /prompts/get_new?lang=en` 的响应
（15,628 字节 Base64 → 11,717 字节明文），得到合法 JSON 数组，18 个 bot，
首条是 `Amy, Your Girlfriend (NSFW)`，`token` 为 `app-jTRBFqKSNjOmeAY6qqCs3obC`。
网关的 `/prompts/get_new?source=upstream` 就是把这条链路跑在生产代码里。

`assets/cid` 的 15 字节 `.rodata` 与最终 key/iv 无直接关系——它是这段派生逻辑的诱饵/无关载荷。

## 5. 内置 bot 目录

`assets/bots.json`（13,806 字节，20 个 bot）。单条结构：

```json
{
  "name": "Amy, Your Girlfriend (NSFW)",
  "avatar": "https://image.fastmobile.me/images/amy_192x192.jpg",
  "photo": "https://image.fastmobile.me/images/amy_1024x1024.jpg",
  "desc": "…",
  "like": "12.3k", "chat": "15.9k", "source": "DevTeam",
  "hello_msg": "…", "token": "app-jTRBFqKSNjOmeAY6qqCs3obC",
  "rank": 1, "conversations": 1235, "engagement": "69%",
  "pre_question": ["…"]
}
```

`token` 形如 `app-<24 位>`，是 bot 级标识；`/chat_stream` 不消费它，`chat_role` 用 `id`
定位 bot。`token` 在实测中对 `/chat_stream` 无影响。

## 6. 2026-11-12 实测

| 请求 | 结果 |
|---|---|
| `GET /health` | 200，`Hello World!`（12B），1,059ms |
| `GET /prompts/get_new?lang=en` | 200，15,628B Base64 密文 |
| `POST /chat_stream` `{query:"hi",model:3,conversation:[]}` | **201**，`content-type: text/event-stream`，**0 字节**，~550ms 后关闭 |
| 同上，model 1–10 全跑 | 全部 201 / 0 字节 |
| 同上，加 `response_mode: streaming` / `blocking` | 201 / 0 字节 |
| 同上，补齐 `lang/pk/ver/uuid/ip/country/isVip/channel/...` | 201 / 0 字节 |
| `POST /chat_role` 完整字段 | 201 / 0 字节，**20s 后**关闭 |
| HTTP/1.1 直连（绕过 fetch 的 HTTP/2） | 同上，无差异 |
| `GET /chat_stream` | 404 `Cannot GET /chat_stream` |

响应头稳定为 `server: cloudflare`、`x-powered-by: Express`、`cache-control: no-cache`、
`transfer-encoding: chunked`。网关据此判定：**Web 服务在线，AI 通道无输出**。

## 7. 复刻方式

`server/gateway.py` 按上述契约实现：

- `/chat_stream`、`/chat_role`：`auto` 模式先做双段探测（`/health` + 一次真实 SSE），
  AI 通道无字节时落 `mock`；`mock` 输出同构 SSE 帧（26 帧 + `event=end`）。
- `/prompts/get_new`：返回 `assets/bots.json` 明文并标注上游是 DES 密文。
- `/v1/chat/completions`：OpenAI 形状的包装层，支持 `stream: true`。

`server/stress_test.py` 覆盖 health、单次流、并发 1/8/16、两条错误路径、模型表。

## 8. 未完项

- `classes.dex` CRC 损坏（PairIP），如需完整类图需从 native 侧 dump。
- `chat_stream` 的 `content` 在真实客户端里同样走 `b9.b.a(key, iv, content)` 解密；
  上游目前不吐字节，这条路径只能在服务端恢复后验证。