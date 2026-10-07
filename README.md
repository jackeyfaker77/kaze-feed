# Kaze Feed

独立的 RSS/Atom MCP 服务，供 Kaze 从私有 GitHub 仓库安装。维护订阅、增量采集、缓存查询和按会话区分的消费状态；筛选、通知和用户兴趣管理由 Kaze 负责。

需要 Python 3.12+。MCP 服务运行于独立虚拟环境，数据库保存到 Kaze 工作区的 mcp-data/kaze-feed，更新代码不会覆盖数据库。

## 让 Kaze 安装

在 Kaze 对话中发送下面这段请求：

~~~text
从 https://github.com/jackeyfaker77/kaze-feed 安装 Feed MCP。
确认当前 Kaze 的实际工作区路径，将仓库克隆到工作区下的 mcp/kaze-feed。
用 Python 3.12+ 运行 scripts/prepare.py --workspace 实际工作区路径。
将脚本输出的 JSON 原样传给 mcp_add，server 名称使用 feed。
再用 mcp_list 和 mcp_feed__feed_status 验证连接，告诉我结果。
已有同名 MCP 或不同的 feed-manage skill 时保留现有配置并说明冲突。
安装后保持订阅列表为空，等待我提供 RSS/Atom 地址。
~~~

私有仓库需要本机已经登录且有仓库访问权的 GitHub 账号。安装脚本准备自己的 .venv、安装服务，并添加工作区 feed-manage skill。注册由 Kaze 的 mcp_add 完成；脚本不会编辑 mcp_servers.json、修改 HEARTBEAT.md 或开启推送。

### Windows 手动准备

先进入 Kaze 的实际工作区。开发版通常是项目的 workspace，安装版通常是用户目录下的 .hasaki/workspace；以 Kaze 自己报告的路径为准。

~~~powershell
git clone https://github.com/jackeyfaker77/kaze-feed.git mcp/kaze-feed
python mcp/kaze-feed/scripts/prepare.py --workspace .
~~~

将输出的 JSON 交给 Kaze 调用 mcp_add。路径会转换为绝对路径，输出类似：

~~~json
{
  "name": "feed",
  "command": [
    "E:/your-workspace/mcp/kaze-feed/.venv/Scripts/python.exe",
    "E:/your-workspace/mcp/kaze-feed/run_mcp.py"
  ],
  "env": {
    "KAZE_FEED_DATA_DIR": "E:/your-workspace/mcp-data/kaze-feed"
  }
}
~~~

重复准备保留数据。已有不同的工作区 skill 时停止覆盖；用 --skip-skill 保留它。开发验收可用 --skip-install 跳过已经完成的依赖安装。

## 工具

注册名为 feed 时，工具前缀为 mcp_feed__。

| 工具 | 用途 |
| --- | --- |
| feed_manage | list、subscribe、unsubscribe、pause、resume；删除用精确名称或 source_id |
| poll_feeds | 采集到期来源；每次最多四个；返回失败原因与 remaining |
| feed_query | latest、search、summary、sources、catalog；仅读缓存 |
| get_proactive_events | 查询某个 consumer 最近 36 小时内未消费的候选 |
| acknowledge_events | 记录消费状态；可指定有效期；按 consumer 隔离 |
| feed_status | 查看缓存条数、最近采集时间和来源错误 |

~~~text
mcp_feed__feed_manage(action="subscribe", name="示例", url="https://example.com/feed.xml")
mcp_feed__poll_feeds()
mcp_feed__feed_query(action="latest", limit=10)
~~~

返回 remaining>0 时可继续调用 poll_feeds。普通查询不会联网，刷新时显式采集。RSSHub 等生成的有效 RSS 地址可直接订阅；本服务不会将 Twitter/X 用户名转换成未经验证的第三方地址。

## 消费状态与主动推送

get_proactive_events 的读取不改变状态。consumer 使用目标会话的 session_key，例如 desktop:xxx，避免一个会话的 ACK 屏蔽其他会话。

~~~text
poll_feeds
  → get_proactive_events(consumer=目标会话)
  → Kaze 筛选与生成通知
  → Kaze 实际发送并取得回执
  → acknowledge_events(reason="delivered", delivery_ref=真实回执)
~~~

reason 支持 processed、read、discarded、delivered。默认 ACK 永久有效；正数 ttl_hours 使候选在到期后可能重新出现。delivered 要求 delivery_ref，但引用由宿主提供，Feed 服务不会独立验证送达。不可用“已生成回复”或“准备发送”代替回执。

当前 Kaze 的简化 heartbeat 没有稳定的送达回执和“送达后 ACK”协调层。因此**安装后可使用订阅和查询，可靠的自动推送需要 Kaze 宿主另行接入**。仅在 prompt 写“推送之后 ACK”，无法覆盖发送失败、进程中断和重复执行。

被丢弃的条目可使用 discarded 消费；发送失败保持未消费，留待宿主重试。Feed 不直接访问 Telegram、QQ 或桌面通知。

## 数据与更新

- RSS GUID / Atom ID 优先作为条目身份，缺失时用规范化原文 URL。
- 标题或发布时间更新保留 event_id；发布时间统一为 UTC。
- ETag / Last-Modified 减少重复下载；304 保留正文和消费状态。
- 单源失败保留旧缓存并返回结构化错误；一次请求整体最多 8 秒，瞬时失败重试一次。
- 30 天未再观察到的条目会被清理，消费记录随条目删除。仍在当前 feed 的身份继续保留。
- KAZE_FEED_DATA_DIR 指定数据目录；直接运行默认使用用户目录下的 .kaze-feed。

升级时在插件目录 git pull，再运行准备脚本。Kaze 当前 mcp_add 不支持原地替换已有连接；更新运行中的服务需先 mcp_remove(name="feed")，再 mcp_add。移除连接不会删除数据。

## 开发与验证

~~~powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[test]"
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/check_kaze.py --backend E:/CODE/hasaki-agent/apps/backend
~~~

最后一项使用 Kaze 真实的 stdio MCP 客户端及临时本地 HTTP feed，检查握手、六个工具、中文、采集、缓存、会话消费隔离、标题更新和重启恢复；不会连接真实信息源或修改 Kaze 的运行工作区。

源码审查见 [参考实现审查](docs/reference-review.md)。工具职责参考 kachofugetsu09/feed-mcp；核心实现独立编写，使用 MIT License。
