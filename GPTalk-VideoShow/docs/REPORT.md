# GPTalk v4.0.2.2 第一轮分析

包名 `com.energysh.aichat`，样本 `GPTalk v4.0.2.2 (Premium).apk`（60.5MB，10 dex）。

## 1. 已确证的基址

`com/energysh/common/BuildConfig.java` 与 `com/energysh/aiservice/BuildConfig.java` 给出三条：

```
AI_BASE_URL     = https://aicup-v2.magicutapp.com/
BASE_URL        = https://camera.magicutapp.com/
ENJOY_BASE_URL  = https://apis.videoshowapp.com/
```

同族域名还有 `buy.videoshowapp.com`、`sit-apis.videoshowapp.com`、
`analytics.enjoymobiserver.com`（统计）。

## 2. 代码结构

| 包 | 类数 | 说明 |
|---|---|---|
| `com.energysh.aichat.app` | 42 | 应用层 |
| `com.energysh.aichat.middleware` | 19 | 中间件 |
| `com.energysh.aichat.{db,event,init,mvvm,service,ui,utils}` | 各 1–6 | 壳 |
| `com.energysh.aiservice` | 2 | 只有 `BuildConfig` + `RSAUtils` |

`com.energysh.aichat` 与 `aichatnew` 两个包下大量只有 `R$*.java`，真正的业务代码不在 dex 里。
全库检索不到任何 Retrofit/OkHttp 注解（`@POST` / `@GET` / `@Multipart` 零命中），
说明网络层来自运行时解密加载的模块。

## 3. assets 加密

`assets/` 下有 20+ 个随机文件名的大块（`pNxXYI7L0YFfgnd4` 228KB、`D3BqFr8b5PbcneJ4` 178KB …），
文件头统一是：

```
00 49 41 50 02 00 00 00 08 06 …        ("\0IAP" + 版本 2 + 长度字段)
```

配合 `libconfig.so`、`libconceal.so` 系的加载器，这是"IAP 包"——业务代码与配置在安装后首次启动时解密。
静态拿不到端点路径，只能拿到 `BuildConfig` 里的基址。

## 4. 2026-11-12 实测

`https://aicup-v2.magicutapp.com` 在线，返回统一信封：

```json
{"success":false,"code":404,"data":null,"message":"Resource not found","currentTime":1794439711445,"other":null,"process":null}
```

试过的路径全部 404：`/api/v1/config`、`/api/config`、`/api/v1/ai/config`、`/ai/config`、
`/api/v1/ai/model`、`/api/v1/chat`、`/api/v1/ai/chat`（GET 与 POST 均是）。
`camera.magicutapp.com` 根路径 302；`apis.videoshowapp.com` 是 Tomcat，根路径 404。

## 5. 同族新增线索（来自 Viddo 的 `libapp.so`）

同公司的 Viddo 把这家公司的服务版图暴露得更全：

```
https://manage.magicutapp.com/appMagicCutApi/customizepage   # JSP 运营后台，200
/api/service_apis                                            # 配置接口名
/api/service_configs                                         # 配置接口名
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/...   # 设备注册与事件上报
```

`manage.magicutapp.com` 实测在线（根路径 400/Tomcat，`/appMagicCutApi/customizepage` 200、97KB HTML）。
`/api/service_apis` 与 `/api/service_configs` 在四个 host 上均 400/404，需要参数或签名，
GPTalk 侧大概率也用同一套服务发现机制。

## 6. 下一步

要补齐端点只有一条路：在模拟器里跑起来，用 Frida 挂 `HttpURLConnection` / OkHttp 的
`Request.Builder`，把真实 URL 打出来。`\0IAP` 包的解密函数在 `libconfig.so` 里，
可以先 `strings lib/arm64-v8a/libconfig.so | grep -i 'aes\|decrypt'` 判断是不是标准 AES。

静态阶段能交付的就是：三条基址、统一响应信封（`success/code/data/message/currentTime/other/process`）、
加密包格式（`\0IAP` v2）。这些足以在抓到第一个真实请求后 10 分钟内拼出完整协议。