# opencode-request-monitor — Docs Index

Project: /root/_/opencode/my_plugins/opencode-request-monitor
Purpose: 记录请求抓包监控工具的当前实现、运行方式与维护参考。

## Summary

当前实现是 FastAPI + SQLite + mitmdump + 单 HTML 前端的本地抓包监控工具。工具支持请求列表、缓存异常标记、详情查看、发送内容 diff、返回摘要视图，以及 Burp/Yakit 风格 raw 报文视图；raw 视图直接展示抓包时保存的 HTTP 请求/响应文本，覆盖普通详情视图的格式化和摘要加工。

---

## 功能说明

[planning/功能说明.md] — 已实现：抓包列表、缓存异常标记、筛选、清空历史与 diff 查看

## 前端

[frontend/界面与交互设计.md] — 已实现：抽屉式详情页、内嵌 Monaco diff、异常状态展示与清空历史交互

## 数据库

[database/数据模型设计.md] — 已实现：SQLite `request_packets` 表、缓存统计字段、比较关系与清空策略

## API

[api/API 设计.md] — 已实现：抓包写入、列表/详情、diff 输入、统计摘要与清空历史接口

## 实现方案

[implementation/FastAPI + SQLite 实现方案.md] — 已实现：基于 FastAPI + SQLite + mitmdump 的最小闭环、端口约定与启动方式
