/*
 * Hook OkHttp + HttpURLConnection and dump every outbound request.
 *
 * Usage:
 *   frida -U -f <package> -l _tools/frida_capture.js --no-pause
 *   frida -U -n <process> -l _tools/frida_capture.js
 *
 * Works for Java/Kotlin clients (GPTalk, iMemo, AIChat, AMA). Flutter targets
 * (Viddo) bypass the JVM stack entirely - capture those with mitmproxy instead.
 */
setTimeout(function () {
  if (!Java.available) {
    console.log("[!] Java bridge unavailable");
    return;
  }

  Java.perform(function () {
    function bodyOf(req) {
      try {
        var body = req.body();
        if (body === null) return "";
        var Buffer = Java.use("okio.Buffer");
        var buf = Buffer.$new();
        body.writeTo(buf);
        var s = buf.readUtf8();
        buf.clear();
        return s.length > 4000 ? s.substring(0, 4000) + "…(" + s.length + "B)" : s;
      } catch (e) {
        return "<body unreadable: " + e + ">";
      }
    }

    function report(req) {
      var line = {
        method: req.method().toString(),
        url: req.url().toString(),
        headers: req.headers().toString().trim(),
        body: bodyOf(req),
      };
      console.log("\n[HTTP] " + line.method + " " + line.url);
      if (line.headers) console.log(line.headers.split("\n").map(function (h) { return "       " + h; }).join("\n"));
      if (line.body) console.log("       >> " + line.body.replace(/\n/g, "\n       >> "));
    }

    // --- OkHttp 3/4 -------------------------------------------------------
    try {
      var Builder = Java.use("okhttp3.Request$Builder");
      var build = Builder.build;
      Builder.build.implementation = function () {
        var req = build.call(this);
        try { report(req); } catch (e) { console.log("[!] report failed: " + e); }
        return req;
      };
      console.log("[+] hooked okhttp3.Request$Builder.build");
    } catch (e) {
      console.log("[-] okhttp3.Request$Builder: " + e);
    }

    // --- HttpURLConnection ------------------------------------------------
    try {
      var URL = Java.use("java.net.URL");
      var openConnection = URL.openConnection.overload();
      openConnection.implementation = function () {
        var conn = openConnection.call(this);
        try {
          console.log("\n[URL] " + this.toString());
        } catch (e) {}
        return conn;
      };
      console.log("[+] hooked java.net.URL.openConnection");
    } catch (e) {
      console.log("[-] java.net.URL: " + e);
    }

    // --- Retrofit (path + query) -----------------------------------------
    try {
      var Retrofit = Java.use("retrofit2.Retrofit");
      console.log("[+] retrofit2 present: " + Retrofit);
    } catch (e) {
      console.log("[-] retrofit2 absent");
    }
  });
}, 0);