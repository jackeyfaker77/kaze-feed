# feed-mcp 参考实现审查

日期：2026-10-08。参考：https://github.com/kachofugetsu09/feed-mcp ，提交 210a79512c5cec008dd24c70f7c9c4e2616f5034。原仓库 8 项 backend contract 测试通过，另对边界输入独立复现。

run_mcp.py 创建 stdio 服务，mcp_bridge.py 暴露订阅、查询、采集、候选读取和 ACK；feed_backend.py 用 SQLite 保存 sources、items、poll_state 与 acked_items。

poll_feeds 按调用和来源间隔采集，没有后台定时器。get_proactive_events 读取最近且未 ACK 的候选；acknowledge_events 写入有到期时间的屏蔽记录。筛选和送达由宿主负责。

| 已复现的问题 | 结果 | 本项目处理 |
| --- | --- | --- |
| RSS 命名空间正文与作者 | 仅含 content:encoded / dc:creator 时正文和作者丢失 | feedparser 处理命名空间 |
| 身份包含标题 | 同一文章改标题，事件 ID 改变 | GUID/Atom ID 优先，URL 兜底 |
| 时间保留不同 offset | 过期的 +08:00 条目通过字符串时间筛选 | 全部规范为 UTC |

其他接入差异：

- 参考查询每次强制串行采集；本项目读缓存，显式并发轮询。
- 参考单源失败只写日志，桥接仍可能返回 ok；本项目返回结构化失败结果。
- 参考 ACK 未区分 consumer；本项目按目标会话隔离。
- ACK 不代表真实送达。本项目 delivered 要求宿主回执，明确服务不独立验证回执。
- Kaze MCP 默认等待 30 秒；本项目每次最多四来源并限制单源整体超时。

参考仓库没有 LICENSE 文件。本项目根据接口和职责独立实现，没有复制其 backend、bridge 或 skill 源文件。

Kaze 简化 heartbeat 没有稳定回执与候选事件关联。可靠主动通知还需由宿主实现选择、送达后 ACK、重试和中断恢复；Feed 数据服务与 prompt 无法自行保证。
