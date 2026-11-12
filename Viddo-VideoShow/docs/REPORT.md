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

### 3.2 已确证的 analytics 网关（6 条端点）

Dart 字符串池里完整存在的 `vsAnalytics` 路径：

```
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientDevice/activeDeviceReport.html?osType=1
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientDevice/registerNewDevice.html?osType=1
https://analytics.enjoymobiserver.com/vsAnalytics/1.0.1/clientEvent/eventDataReport.html?osType=1
vsAnalytics/1.0.1/feedbackRecordClient/getReportTypeList.html?osType=1
vsAnalytics/1.0.1/feedbackRecordClient/reportFeedBackRecord.html?osType=1
vsAnalytics/1.0.1/qiniu/getUploadToken.html?osType=1
```

`analytics.enjoymobiserver.com` 是 Spring Boot，404 返回
`{"timestamp","status","error","path"}`。`qiniu/getUploadToken.html` 实测 **200**，但回的是：

```json
{"scheme":"https","osType":"1","remotePort":"50336","errorCode":"Failed in decoding inputData",
 "serverPort":"443","reqUrl":"/vsAnalytics/1.0.1/qiniu/getUploadToken.html"}
```

`errorCode` 直接点明协议：**参数叫 `inputData`，且是编码/加密后的载荷**（客户端把参数包成一个
加密串再提交）。这是 vsAnalytics 系列的统一入口形状。

### 3.3 AI 生成侧

`assets/flutter_assets/assets/data/homeData.json` 里的图片代理走：

```
http://camera.sinaweibo.com.cn//appCameraApi/getPic?picUrl=<远端图片>
```

`camera.sinaweibo.com.cn` 已下线（TLS 连接被关），但 **`appCameraApi` 前缀在
`camera.magicutapp.com` 上仍然有效**：`/appCameraApi/getPic` 返回 **302**（重定向到
`picUrl`），而其它任意 `/appCameraApi/<x>` 都是 Spring Boot 404 页。这说明
`camera.magicutapp.com` 是 Camera 产品线的 API 宿主，`getPic` 是其中一个 controller 路由。

AI 生成的 action 名（`createVideoByText` / `createVideoByImage` / `textToVideo`）在
`libapp.so` 里是**方法名而非路由**，直接拼到 `/appCameraApi/` 下全部 404。
`assets/data/homeData.json` 的 23 条 URL 全部指向 `sinaweibo` 图床，没有生成接口。

### 3.4 结论

静态能确认到「`camera.magicutapp.com/appCameraApi/` 是 API 宿主、`vsAnalytics` 是另一套
Spring Boot 网关」这一层，AI 生成的具体 action 需要 blutter 反编译 Dart 代码或动态抓包。


### 3.5 blutter 已跑通

Dart 3.4.3 / arm64 的 blutter 在这台机器上一共踩了 5 个环境坑，全部解决后产出
`pp.txt`（3.0MB / 61,178 行）、`objs.txt`、`asm/` 反汇编：

| # | 问题 | 处理 |
|---|---|---|
| 1 | `cmake` 找不到 `kernel32.lib` | 把 `vcvars64.bat` 的 LIB/INCLUDE/PATH 导入 PowerShell 进程 |
| 2 | `Failed to find all ICU components` | ICU 解压出来是 `lib64/`，FindICU 只认 `lib/`，复制一份 |
| 3 | `fatal error C1083`（路径乱码） | 中文目录被 MSVC 编码成 GBK，工程搬到 `C:\blutter_tmp` |
| 4 | `LNK2001: icu_73::UnicodeSet` | 链接用的是 Windows SDK 自带 `icuuc.lib`，在 build.ninja 里改成 ICU 73 |
| 5 | `LNK1181: ntdll.lib` | 26100 SDK 不带，把 `10.0.22621.0\um\x64` 加进 LIB |

产物在 `work/blutter_out/`。

## 4. blutter 给出的结果

### 4.1 `ServiceApis.getAnaUrl` 的真实实现

```dart
static String getAnaUrl(String url) {
  if (url.startsWith("http")) return url;
  return "https://analytics.enjoymobiserver.com/" + url;
}
```

analytics 网关的 base 硬编码为 `https://analytics.enjoymobiserver.com/`，所有相对路径都拼在它后面。

### 4.2 请求参数结构

`service_configs.dart`：`appId, appTime, appVersion, channelName, deviceUuid, isVip, lang, osVersion, phoneModel, pkgName, uuid, version, versionName`

`enjoy_analysis.dart` 额外带：`activeDuration, eventData, phoneBrand, requestId, userId, userPseudoId, uuId, osType`

渠道常量：`GOOGLE_PLAY` / `GOOGLEPLAY` / `TX009`。

### 4.3 五条端点全部可用

不带参数时服务端返回 `{"errorCode":"Failed in decoding inputData", ...}`；
**改成 POST + JSON body 后全部 200**：

| 端点 | POST JSON 结果 |
|---|---|
| `clientDevice/registerNewDevice.html?osType=1` | 200 `[{"info":"otherEx"}]` |
| `clientDevice/activeDeviceReport.html?osType=1` | 200 `[{"info":"otherEx"}]` |
| `clientEvent/eventDataReport.html?osType=1` | 200 `[{"info":"otherEx"}]` |
| `qiniu/getUploadToken.html?osType=1` | 200（空 body） |
| `feedbackRecordClient/getReportTypeList.html?osType=1` | 200（空 body） |

`inputData` 不是必需参数——它只是 GET 缺参时的报错话术。POST JSON 直接通过。

### 4.4 AI 生成侧

`text_to_video_logic.dart` 里能读出生成参数名：

```
aiType:  TextToVideo | aiTextToVideo3 | aiTextToVideoExtend
consumeType, points, platFormId, prompt, content, enContent, ratio, width, height
```

`aiType` 是业务枚举，不是 URL。AI 生成的具体 action 仍然不在 Dart 明文中
（`asm/quickart/` 下所有 `http` 常量都指向 analytics 网关或商店链接）。
`/textToVideo`、`/mainPage`、`/webPage` 是**页面路由**，不是 API。

结论：**analytics 侧协议已经完全打通且可调用；AI 生成侧要拿到 action 名仍需动态抓包**。

## 5. 下一步

1. AI 生成端点：模拟器 + Frida 挂 `dart:io` 的 `HttpClient`，或实体设备抓包。
2. analytics 网关已可用，可直接做号池/统计类集成。
3. 拿到端点后复用 GPTalk 的信封解析，两个 App 的响应结构大概率一致。
