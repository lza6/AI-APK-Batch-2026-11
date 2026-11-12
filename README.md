# AI APK Batch — 2026-11

7 个 Android AI 应用（2024–2026 年版本）的逆向分析、协议还原与可执行网关。
样本全部来自公开分发渠道的 Premium/Pro 变体，用于协议学习与互操作性研究。

## 判定矩阵

| 样本 | 包名 | 加固 / 形态 | 业务上游 | 2026-11-12 实测 | 结论 |
|---|---|---|---|---|---|
| AIChat v1.9.1 | `com.ai.assistant.powerful.chat.bot` | PairIP | `chatai.wecall.info` | `/health` 200；`/chat_stream` 201 + 0 字节 | 协议完整，AI 通道无输出 |
| Ask Me Anything v1.7.0 | `com.android.ntduc.chatgpt` | libconceal | `pass-gpt.nowtechai.com` | 503 | 上游停服 |
| nova ai v3.7.2 | 同上（同一代码库） | 同上 | 同上 | 503 | 同上 |
| iMemo v9.0.12 | `com.oneweek.noteai` | 无 | `noteai.sboomtools.net` | 443 拒绝 | 上游停服 |
| GPTalk v4.0.2.2 | `com.energysh.aichat` | `\0IAP` 加密 assets | `aicup-v2.magicutapp.com` | 在线，端点运行时解密 | 需动态抓包 |
| Viddo v4.0.4.1 | Flutter（arm64） | Dart AOT | videoshow 系 | 同上 | 需 blutter |
| AnimeArt v3.9.2 | `com.art.fantasy` | native 业务 | 未定位 | — | 需动态 |

完整结论见 [`docs/第一轮总览.md`](docs/第一轮总览.md)。

## 两个可直接跑的网关

```bash
pip install fastapi uvicorn httpx pycryptodome

python AIChat-WeCall/server/gateway.py              # http://127.0.0.1:18621
python AskMeAnything-NovaAI/server/gateway.py       # http://127.0.0.1:18622
```

两个网关在 `auto` 模式下先做双段探测（Web 服务是否在线 / AI 通道是否吐字节），
上游不可用时自动落 `mock`，并在 `/health` 里分开报告 `server_alive` 与 `ai_channel_alive`。
强制透传用 `AICHAT_MODE=real` / `NOWAI_MODE=real`。

压测：

```bash
python AIChat-WeCall/server/stress_test.py
python AskMeAnything-NovaAI/server/stress_test.py
python _tools/browser_verify.py
```

## AIChat 的加密层

AIChat 的响应是 `DES/CBC/PKCS5Padding` + Base64。key/iv 由 `Parser.doGetKey` /
`doGetIV` 用 8 个 `"&#<n>"` 片段拼接后按 `&#` 切分、逐段 `n ^ 65280` 得到：

```
key = "20190826"
iv  = "00514321"
```

用这对 key/iv 解上游 `/prompts/get_new?lang=en` 的 15,628 字节密文，得到 11,717 字节
JSON、18 个 bot。网关的 `/prompts/get_new?source=upstream` 就是这条链路。

推导过程见 [`AIChat-WeCall/docs/PROTOCOL.md`](AIChat-WeCall/docs/PROTOCOL.md) §4。

## 目录

```
AIChat-WeCall/        协议还原 + 网关 + demo 页 + 压测
AskMeAnything-NovaAI/ NowAI/OpenAI/Poe/Gemini 四路上游 + 网关 + 压测
GPTalk-VideoShow/     基址与加密包格式
Viddo-VideoShow/      Flutter 形态与血缘
iMemo-Sboom/          形态与上游状态
AnimeArt/             native 业务形态
_tools/               dex 字符串池提取、Playwright 浏览器验证
```

## 压测结果（2026-11-12，mock 模式）

| 网关 | health ×100 | 单次流 | 并发 1/8/16 | 错误路径 |
|---|---|---|---|---|
| AIChat :18621 | p50 1.7ms / p95 2.4ms | 397.8ms，26 帧 | 全部通过，p95 418–434ms | 3/3 |
| NowAI :18622 | p50 1.9ms / p95 3.3ms | 761.2ms，25 行 | 全部通过，p95 653–697ms | 2/2 |

Playwright 真实浏览器验证：两个 demo 页均通过（输入 → 发送 → 流式结束 → 计数断言）。

## 说明

- 仓库不含 APK 本体、反编译产物与运行期数据。
- 所有上游域名与端点来自公开分发客户端的静态分析，仅用于协议互操作性研究。
- `AIChat-WeCall/work/assets/bots.json` 里的 `token` 字段是客户端内置的公共 bot 标识，
  不是个人凭据。