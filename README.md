# opencode-request-monitor

本地 OpenCode 请求抓包与比较工具。

## 功能

- 通过 `mitmdump` 抓取本地 OpenCode 请求与响应。
- 使用 FastAPI + SQLite 保存请求记录，便于后续查看和比较。
- 提供单页 Web 界面查看请求列表、详情、原始 HTTP 报文和响应摘要。
- 支持发送内容 diff、缓存异常标记、筛选和清空历史。
