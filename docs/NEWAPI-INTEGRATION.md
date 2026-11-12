# new-api 对接指南

给负责对接 new-api 的会话：这份文档自包含，照着做即可。

## 0. 先看结论

7 个样本里，**当前没有任何一个能直接当 new-api 的 chat 上游**：

| 目标 | 阻塞 |
|---|---|
| AIChat `/chat_stream` | 上游 201 + 0 字节（服务端接单不吐数据） |
| NowAI `pass-gpt` | 503 |
| Viddo `v4/upload` | 回「该功能未配置」，appId `YZ080` 的功能没开 |
| iMemo / GPTalk / AnimeArt | 上游已死 / 端点运行时才解密 |

但**适配层与配置路径已经确定**。下面给的是「上游一恢复就能接」的完整接线方案，
以及现在就能跑通的本地链路（mock）。

---

## 1. 架构

```
客户端 ──OpenAI 格式──> new-api ──OpenAI 格式──> 适配层 gateway.py ──原生协议──> 上游
```

new-api 只认 OpenAI 形状，所以**必须有一层适配器**做双向翻译。仓库里已有的：

- `AIChat-WeCall/server/gateway.py`（端口 18621）—— 已实现 `/v1/chat/completions`，支持 `stream:true`
- `AskMeAnything-NovaAI/server/gateway.py`（端口 18622）—— 同样已有
- Viddo 的 v4 适配层还没写，§4 给骨架

---

## 2. new-api 侧配置（AIChat / NowAI 通用）

两个网关都是 OpenAI 兼容，配法完全一样。

### 2.1 启动适配层

```powershell
# AIChat
C:\Python314\python.exe "AIChat-WeCall\server\gateway.py"
# 默认 127.0.0.1:18621

# Ask Me Anything / nova ai
C:\Python314\python.exe "AskMeAnything-NovaAI\server\gateway.py"
# 默认 127.0.0.1:18622
```

### 2.2 new-api 添加渠道

后台 → 渠道 → 添加渠道：

| 字段 | 值 |
|---|---|
| 类型 | **OpenAI** |
| 名称 | `aichat-local` |
| 分组 | 默认 |
| 模型 | `aichat-1,aichat-2,aichat-3,aichat-4,aichat-5` |
| 密钥 | 任意非空字符串（适配层不校验） |
| 代理 | 留空 |
| Base URL | `http://127.0.0.1:18621` |

保存后点「测试」应回 `200`。

> new-api 会把 Base URL 拼成 `{Base URL}/v1/chat/completions`，所以填 `http://127.0.0.1:18621`
> 而不是 `.../v1`。如果填了 `/v1` 会变成 `/v1/v1/chat/completions`。

### 2.3 模型重定向（可选）

如果想让客户端继续用 `gpt-4o` 这类名字：

```
gpt-4o -> aichat-3
gpt-4o-mini -> aichat-1
```

填在渠道的「模型重定向」里。

### 2.4 验证

```bash
curl http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer sk-你的newapi令牌" \
  -H "Content-Type: application/json" \
  -d '{"model":"aichat-3","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

期望：`data: {"choices":[{"delta":{"content":"..."}}]}` 逐块返回，最后 `data: [DONE]`。

---

## 3. 字段映射表（适配层已实现）

### AIChat

| OpenAI 字段 | AIChat 字段 |
|---|---|
| `messages[-1].content` | `query` |
| `messages[0..n-2]` 两两配对 | `conversation: [{question, answer}]` |
| `model`（`aichat-3` → `3`） | `model` |
| 响应 `choices[0].delta.content` | SSE 帧里的 `content` |
| 流结束 | `event == "end"` |

### NowAI

| OpenAI 字段 | NowAI 字段 |
|---|---|
| `messages[]` | `contents: [{role, content}]` |
| 响应 `delta.content` | NDJSON 每行的 `content` |
| 流结束 | `status == "done"` |

---

## 4. Viddo v4 适配层（需要新写）

v4 是**异步任务**模型，不是流式对话，需要适配层做四步：

```
1. POST /v4/getUuid          拿 uId
2. POST /v4/upload           multipart(decrypt/sign/content)，返回任务 key
3. POST /v4/downLoad/{key}   轮询，直到 status 完成
4. 把结果 URL 包成 OpenAI 的 chat.completion 返回
```

### 4.1 请求构造（已复刻，见 `Viddo-VideoShow/server/v4_client.py`）

```python
payload = {
    "appTime": str(int(time.time()*1000)),
    "priority": "99",              # VIP 档；普通 "50"
    "uId": uid,                    # v4/getUuid 返回
    "pkgName": "com.energysh.quickarte",
    "requestType": "texttoimage",  # AiFunAction.functionTag()
    "content": prompt,
    "prompt": prompt,
    "platFormId": "",              # 可选
    "pointId": "",                 # 可选
    "consumeType": "",             # 可选
}
# decrypt = Base64(RSA/ECB/PKCS1Padding(JSON))  按 117 字节分块
# sign    = g.a(deviceId + appId + appTime)，服务端目前不校验
# multipart 字段：decrypt / sign / content
```

### 4.2 action 名（`functionTag()`）

```
texttoimage  texttovideo  refertoimage  imagetoimage  aichat
texttomusic  texttovoice  audiodriven   faceswap      jpcartoon
```

完整 50+ 项见 `Viddo-VideoShow/docs/REPORT.md` §6.3。

### 4.3 适配层骨架

```python
@app.post("/v1/chat/completions")
async def openai_compat(request: Request):
    body = await request.json()
    prompt = body["messages"][-1]["content"]
    uid = get_uuid()                       # 缓存，别每次都领
    payload = build_payload(prompt, "texttoimage")
    key = await upload(payload)            # /v4/upload
    result = await poll(key)               # /v4/downLoad/{key}，1.5s 一次
    text = result["data"]                  # 结果 URL 或文本
    # 非流式直接返回；流式就把 text 切块发 delta
    return JSONResponse({...})
```

### 4.4 当前阻塞

`v4/upload` 回 `{"code":400,"message":"该功能未配置！"}`。加密和解密都已验证通过
（错误从「参数校验失败」变成了「功能未配置」），缺的是服务端给 `YZ080` 开功能，
或者 `AiRepository.g(api, …)` 里那个外部传入的 `api` 字符串。

**换一个已开通功能的 appId 是最快的验证路径。**

---

## 5. 下游计费

new-api 按 token 计费，所以适配层要在响应里带 `usage`：

```json
{"usage": {"prompt_tokens": 12, "completion_tokens": 88, "total_tokens": 100}}
```

AIChat / NowAI 网关目前返回的 mock 响应没有 `usage`，接 new-api 前补上，
否则计费会按 0 算。估算方式：`len(text) // 4`。

---

## 6. 上线前检查清单

- [ ] 适配层 `/health` 的 `effective` 是 `real`（不是 `mock`）
- [ ] new-api 渠道「测试」通过
- [ ] `stream:true` 能收到 `data: [DONE]`
- [ ] 响应带 `usage`
- [ ] 并发 16 路不超时（本地网关压测已过，c=16 p95 434ms）
- [ ] 上游域名解析正常（AIChat：`chatai.wecall.info` 走 Cloudflare）

## 7. 什么时候能真用

| 上游 | 恢复条件 |
|---|---|
| AIChat | `chatai.wecall.info/chat_stream` 开始返回字节（现在恒 0） |
| NowAI | `pass-gpt.nowtechai.com` 从 503 恢复 |
| Viddo | `YZ080` 功能开通，或拿到正确的 `api` 路径 |
| iMemo / GPTalk / AnimeArt | 需要动态抓包补端点，且上游还活着 |
