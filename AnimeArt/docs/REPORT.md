# AnimeArt v3.9.2 第一轮分析

包名 `com.art.fantasy`，样本 `AnimeArt v3.9.2 (Premium).apk`（86.6MB，6 dex）。

## 1. 加固形态

`lib/` 下三件套，每个 ABI 都有一份：

```
libSignatureKiller.so     # 签名校验绕过（MOD 版特征，由破解者注入）
libZFutureLib.so          # 业务 native 库
libimage_processing_util_jni.so
libumeng-spy.so           # 友盟统计
```

`libSignatureKiller` 说明这个 APK 是被第三方重打包的 MOD，原版没有这个库。

## 2. 业务代码分布

`com/art/fantasy` 下只有 54 个类，按目录拆：

```
base/  databinding/  guide/  main/  tool/  zfuture/
```

`zfuture` 是对 `libZFutureLib.so` 的 JNI 桥。真正的生成逻辑（AI 绘画/动漫化）在 native 层，
Java 层只剩 Activity 与 UI 绑定。

全库检索域名只命中广告 SDK（`safedk.com`、`vungle.com`、`supersonicads.com`、`rayjump.com`、
`applovin.com`），业务域名一个都没有——说明域名是 native 侧拼出来的，或者从加密资源里读。

`assets/` 内容极简，只有：

```
assets/SignatureKiller/origin.apk      # 破解者塞进去的原版 APK
assets/dexopt/baseline.prof
assets/fonts/Helvetica.ttc
assets/rv_binddatas.xml
```

`assets/SignatureKiller/origin.apk` 是签名校验用的原始包，可以直接拆出来对照原版。

## 3. 依赖

`libumeng-spy.so`（友盟）、`com.applovin`、`com.mbridge`、`com.unity3d.ads`、
`com.vungle` —— 典型的国内出海工具类应用广告栈。

## 4. 2026-11-12 状态

静态阶段没有拿到任何业务域名，也没有跑起来验证。这一份**只有形态结论，没有协议结论**。

## 5. 下一步

1. 先解 `assets/SignatureKiller/origin.apk`，看原版 dex 是否有残留的业务字符串
   （MOD 版可能删了原版的部分资源）。
2. `strings lib/arm64-v8a/libZFutureLib.so | grep -i 'http\|api\.'`，domain 大概率在这里。
3. 反编译 `libZFutureLib.so`（Ghidra / IDA），找 JNI 入口 `Java_com_art_fantasy_zfuture_*`。
4. 如果 native 侧域名也是加密的，直接上模拟器 + Frida。

静态性价比最低的一个样本，建议放在最后。