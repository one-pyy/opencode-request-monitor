# opencode-request-monitor — Knowledge Database Index

Project: /root/_/opencode/my_plugins/opencode-request-monitor
Purpose: 保存抓包代理流式转发、后台上报与脚本生命周期的可复用判断。

## Summary

抓包代理即使收到上游流式响应，也可能因正文缓存和同步上报延迟客户端输出。流式转发、完整正文留存及后台上报需分别验证，脚本热重载还需兼容同步退出钩子。

---

## Issues

[issues/2026-10-12_mitmproxy-stream-buffering-and-upload-lifecycle.md] — 流式缓存、正文留存、后台上报顺序与脚本退出边界 #mitmproxy #sse #streaming #concurrency #trap
