---
name: feed-manage
description: 在 Kaze 中管理独立 Feed MCP 的 RSS/Atom 订阅、查看最近内容、查询采集状态和记录消费结果。用户提到 RSS、Feed、订阅、信息来源、最近文章或订阅更新时使用。
---

# Feed 管理

server 名称必须为 feed。先用 mcp_list 检查连接，再使用 mcp_feed__ 开头的工具。

## 查询与订阅

- 查看订阅：feed_manage(action="list")，依照真实返回回答。
- 新增：用户给出 RSS/Atom HTTP(S) 地址后调用 feed_manage(action="subscribe", name=名称, url=地址)。
- 用户只给网站或账号时，先查网站公开提供的 RSS/Atom 地址。没有证据时说明缺少地址，不编造 URL。
- 删除、暂停、恢复：用准确名称或 source_id。名称有歧义时请用户选定。
- 内容查询：feed_query(action="latest" 或 "search")；catalog 可分页，summary 看来源概况。
- 用户要求最新内容：先 poll_feeds。remaining>0 时可继续采集剩余到期来源，再读取缓存。
- 采集 ok=false 时说明失败来源与缓存可能较旧；用 feed_status 查详情。
- 引用时保留来源名、原文链接和发布时间。

## 消费与主动检查

get_proactive_events 仅读候选，不会采集、发送或 ACK。consumer 使用通知目标的 session_key，同一目标保持一致。

已处理、已读或丢弃时按实际含义调用 acknowledge_events：

- processed：完成约定处理。
- read：用户明确确认已读。
- discarded：按用户规则明确丢弃。
- delivered：宿主确认实际送达，并提供 delivery_ref。

默认消费永久有效；需要重新检查同一条目才传正数 ttl_hours。missing 返回的 ID 应告知用户。

delivery_ref 只能来自宿主实际回执。回复已生成、工具开始运行或模型认为成功，都不能代替回执。发送失败、取消和中断保持待处理。

当前 Kaze heartbeat 尚缺送达后 ACK 协调层。安装成功只能说明订阅和查询工具可用，不得声称自动推送闭环已完成。主动推送需要宿主提供调度、筛选、送达确认和重试机制。

## 安装与更新

按 README 运行 scripts/prepare.py --workspace 实际工作区，将输出参数交给 mcp_add。
用 mcp_list 与 mcp_feed__feed_status 验证连接。保留已有订阅、数据库、不同的用户 skill 和无关 MCP。
升级连接需按用户要求先 mcp_remove，再 mcp_add；两者不删除数据。
