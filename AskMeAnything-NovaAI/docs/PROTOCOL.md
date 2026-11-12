# Ask Me Anything v1.7.0 / nova ai v3.7.2 协议还原

两个样本共用业务包 `com.android.ntduc.chatgpt`（Kotlin + Hilt + Ktor），是一样的代码库换皮。
反编译产物在 `decom/jadx/sources`（26,470 类，65 处方法体缺失）。

## 1. 四路上游

`DataRepository` 里并存四条流式通道，按 bot 配置切换：

| 通道 | 方法 | 上游 | DTO |
|---|---|---|---|
| Now AI | `startStreamNowAiServer` | `http://pass-gpt.nowtechai.com/api/v1/pass` | `now_ai/NowAiRequest` → `NowAIResponse` |
| OpenAI | `startStreamOpenAiServer` | `https://api.openai.com/v1/chat/completions` | `open_ai/OpenAIRequest` |
| Poe | `startStreamPoeAiServer` | `https://api.poe.com/bot/GPT-3.5-Turbo` | `poe_ai/PoeAIContentRequest` |
| Gemini | `callStreamGemini` | `generativelanguage…:generateContent` | `gemini/GenerateContentRequest` |

基址常量在 Dagger 图里（`DaggerApp_HiltComponents_SingletonC.java`）：

```
:684  http://art.nowtechai.com/          # 静态图床
:709  http://server.nowtechai.com/       # 业务后端
:759  http://server.nowtechai.com/
:809  http://checking.heratech.space/    # 版本/风控检查
```

`data.tolimanspaceni.com` 只在 `strings` 的静态资源 URL 里出现 37 次（`/gpt/Ai-Art/*.png`、
`/gpt/Ai-Character/avatar/*.png`），是图床不是 API。`gpt.tolimanspaceni.com` 同样只是图片站。

## 2. Now AI 通道（最常用）

请求：

```
POST http://pass-gpt.nowtechai.com/api/v1/pass
Key: <客户端 key>
TimeStamps: <epoch 毫秒>
Content-Type: application/json
```

```json
{"contents": [{"role": "user", "content": "你好"}]}
```

`NowAIContent` 只有 `role` / `content` 两个字段（`dto/now_ai/NowAIContent.java`）。

响应不是 SSE，是 **NDJSON**：每行 `{"status": "...", "content": "..."}`
（`NowAIResponse` 只有 `status` / `content`），由 `decodeToFlow` + `onEachLine` 逐行解析
（`DataRepository$startStreamNowAiServer$2`）。状态串出现过的取值含 `processing` / `done`，
`done` 由客户端映射为流结束。

`Key` 头的取值来自 ViewModel 层，反编译出来的调用链里没有硬编码常量；
`strings.txt` 中不存在形如 `sk-…` 的密钥，`KEY_DEFAULT_POE` / `KEY_GEMINI` / `SUPPORT_TOKEN`
是 SharedPreferences 的键名，不是值。网关把它作为 `NOWAI_KEY` 透传。

## 3. 其它业务端点

| 端点 | 说明 |
|---|---|
| `ws://server.nowtechai.com/message?id=<id>` | 在线客服 WebSocket（`LiveSupportFragment.java:870`） |
| `http://checking.heratech.space/` | 启动检查 |
| `http://art.nowtechai.com/` | 图片资源 |

## 4. 2026-11-12 实测

| 目标 | 结果 |
|---|---|
| `pass-gpt.nowtechai.com`（DNS → 23.20.110.97） | **503**，空 body；带 `Key`/`TimeStamps` 也是 503 |
| `server.nowtechai.com`（DNS → 54.87.60.147） | **503** |
| `checking.heratech.space`（DNS → 103.224.212.215） | 200，但内容是域名待售页 `heratech.space / This domain may be for sale` |
| `art.nowtechai.com` | DNS 解析失败 |
| `data.tolimanspaceni.com` / `gpt.tolimanspaceni.com` | DNS 解析失败 |

三条线上游全部不可用。这批 App 的构建标记是 `Now_AI_V4.3.0.0_26.07.2024_12h45_release`，
上游在 2024 年之后停掉了。

## 5. 复刻方式

`server/gateway.py`：

- `POST /api/v1/pass`：`auto` 模式先 POST 探测，503 时落 `mock`；`mock` 输出同构 NDJSON
  （25 行 + `status=done`），保留 `Key` / `TimeStamps` 头。
- `POST /v1/chat/completions`：OpenAI 形状包装，支持 `stream: true`。
- `GET /endpoints`：列出三条待复测的上游。

`server/stress_test.py`：health ×100、单次流、并发 1/8/16、空 `contents` → 400。

## 6. 未完项

- `Key` 头的生成算法（需要 smali 级追踪 ViewModel 到 Repository 的调用点）。
- OpenAI / Poe / Gemini 三条备用通道的鉴权参数（对应 `KEY_DEFAULT_POE` /
  `KEY_GEMINI` 在 SharedPreferences 里的实际值，只有装到设备上跑过一次才会有）。