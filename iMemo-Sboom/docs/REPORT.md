# iMemo v9.0.12 第一轮分析

包名 `com.oneweek.noteai`，样本 `iMemo v9.0.12 (Premium).apk`（91.4MB，12 dex，727,711 个字符串）。
这是 7 个样本里唯一没有应用加固的。

## 1. 业务形态

AI 笔记 / 录音转写类应用。dex 里的关键依赖：

| 依赖 | 用途 |
|---|---|
| `com.qonversion.android` | 订阅计费与分析 |
| `com.adjust.sdk` / `subscription.adjust.com` | 归因 |
| `io.realm` / `realm.mongodb.com` | 本地/云数据库（MongoDB Realm） |
| `com.onesignal` | 推送 |
| `com.google.firebase` | 基础服务 |
| `docx4j` / `xlsx4j` / `apache.poi` | 文档导出（Word/Excel） |
| `amplituda` + `avcodec` + `pdfium` | 音频波形、解码、PDF |
| `com.google.android.recaptcha` | 登录风控 |

网络层是 Retrofit（`retrofit2` + `support/request` 包）。

## 2. 上游

| 域名 | DNS | 2026-11-12 实测 |
|---|---|---|
| `noteai.sboomtools.net` | 34.172.232.235 | **443 连接被拒绝**（TLS 握手直接 `WinError 10061`） |
| `newwaylabs.co` | 15.235.114.91 | TLS 1.3 握手成功 |

`strings.txt` 里 `noteai.sboomtools.net` 出现 2 次、`newwaylabs.co` 6 次，
后者可能是官网或备用 API 宿主。`smartmovevn.zendesk.com` 是客服。

主 API 域名已经不再监听 443，`noteai` 这条产品线在上游侧关停了。

## 3. 为什么没有完整反编译

`jadx`（`-Xmx5g`，6 线程）在第 0 个类就 OOM：

```
# There is insufficient memory for the Java Runtime Environment to continue.
# Native memory allocation (malloc) failed to allocate 78944 bytes. Error detail: Chunk::new
```

同时刻机器上另有 4 个 jadx 进程各占 5–6GB（VPN v206 / Proxy Master / ExpressVPN /
VPN Proxy Master），空闲内存只剩 2.3GB。这不是样本问题，是并发预算问题。

重跑命令（等其它 jadx 结束后）：

```powershell
$env:JAVA_OPTS="-Xmx4g"
C:\tools\jadx\bin\jadx -d "iMemo-Sboom\decom\jadx" --no-res --threads-count 4 "iMemo v9.0.12 (Premium).apk"
```

## 4. 下一步

1. 重跑 jadx，在 `com/oneweek/noteai` 下找带 `@POST` / `@GET` 的接口定义与 `baseUrl`。
2. 若 `noteai.sboomtools.net` 确认永久下线，重点转向 `newwaylabs.co`——
   先 `GET /` 与 `GET /api/` 看是否同一套服务。
3. 该样本无加固，动态抓包成本最低；如果模拟器里能跑起来，一次抓包就能拿全端点。

## 5. 结论

协议层静态可达（无加固、Retrofit 注解可读），但**主上游已关闭**，即使还原出端点也无数据可出。
优先级建议排在 GPTalk / Viddo 之后。