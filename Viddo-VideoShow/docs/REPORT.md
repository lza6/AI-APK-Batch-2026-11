# Viddo v4.0.4.1 第一轮分析

样本 `Viddo v4.0.4.1 (Pro).apk`（129MB）。Flutter 应用：`lib/arm64-v8a/libapp.so`（12.9MB）
+ `libflutter.so`（10.6MB），只有 arm64-v8a 一个 ABI，dex 层只剩插件。

## 1. 与 GPTalk 同源

`libapp.so` 字符串池里的域名分布：

```
20  gmail.com            # 支持邮箱
19  videoshowapps.com    # 主站家族
 6  flutter.io
 4  enjoymobiserver.com  # 统计（与 GPTalk 相同）
 2  manage.magicutapp    # 与 GPTalk 的 BASE_URL 同域
 1  videoshowapp.com / videosinc.com / videoshackapps.com
```

GPTalk 的 `ENJOY_BASE_URL = https://apis.videoshowapp.com/`，Viddo 的域名族与之重合，
两个 App 是同一家（EnjoyMobi / videoshow）的不同产品线：GPTalk 偏 AI 聊天，Viddo 偏 AI 视频。

原生库里还带 `libyzffmpeg.so` / `libyzijkplayer.so` / `libaveditor.so` / `libtensorflowlite.so`，
说明视频编辑与离线人脸/语言识别都在本地跑，云端只负责生成。

## 2. 静态边界

Dart AOT 把 API 端点编译进 `libapp.so` 的字符串池与常量池，`grep` 只能拿到域名，
拿不到路径与参数。要拿到完整协议必须上 `blutter`：

```
blutter <path>/lib/arm64-v8a/libapp.so <flutter_sdk_dir>
```

产物是 `pp.txt`（快照里的 Dart 对象）和反汇编；`pp.txt` 里能直接搜到 `Uri.parse` 的实参。

## 3. 2026-11-12 实测

`aicup-v2.magicutapp.com` 与 `camera.magicutapp.com` 均在线（见 `GPTalk-VideoShow/docs/REPORT.md`），
统一信封 `{success,code,data,message,currentTime,other,process}`，已知路径前缀 `/api/v1/` 一律 404。
`apis.videoshowapp.com` 是 Tomcat，根路径 404。

结论与 GPTalk 相同：**服务在线，端点在运行时才可知**。

### 3.1 从 `libapp.so` 补到的线索

Dart 字符串池里还能挖到这些完整常量：

```
https://manage.magicutapp.com/appMagicCutApi/customizepage?pageType=Viddo_PrivacyPolicy
https://manage.magicutapp.com/appMagicCutApi/customizepage?pageType=Viddo_TermsofServiceX
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientDevice/activeDeviceReport.html
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientDevice/registerNewDevice.html
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientEvent/eventDataReport.html
/api/service_apis
/api/service_configs
```

`manage.magicutapp.com` 是一套 JSP 运营后台（`/appMagicCutApi/customizepage` GET 返回 200、97KB
HTML 内容页），`/api/service_apis` 与 `/api/service_configs` 是配置接口名。

四个 host 上实测这两个接口：

| host | `/api/service_configs` | `/api/service_apis` |
|---|---|---|
| `camera.magicutapp.com` | 400（Tomcat 8.5.11） | 400 |
| `aicup-v2.magicutapp.com` | 统一信封 + 404 | 统一信封 + 404 |
| `apis.videoshowapp.com` | 404 | 404 |
| `manage.magicutapp.com` | 400 | 400 |

说明这两个接口要么需要参数/签名，要么挂在别的服务上。**端点仍未闭合，需要动态抓包**。

## 4. 下一步

1. `blutter` 反 `libapp.so`，在 `pp.txt` 里按 `magicutapp` / `videoshowapp` 检索 `Uri`。
2. 若 blutter 环境搭不起来，退一步用模拟器 + Frida 挂 `dart:io` 的 `HttpClient`，
   抓 Viddo 首页刷新时的请求。
3. 拿到端点后可直接复用 GPTalk 的信封解析，两个 App 的响应结构大概率一致。