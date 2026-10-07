import json
import logging
import sys

from mcp.server import MCPServer

from . import __version__
from .config import Settings
from .poller import Poller
from .store import Store


def create_server(settings: Settings | None = None) -> MCPServer:
    store = Store(settings or Settings.from_env())
    poller = Poller(store)
    server = MCPServer(
        "kaze-feed", version=__version__,
        instructions="RSS/Atom data service. Poll explicitly, query cached content, and acknowledge only after processing. Delivery is owned by the host.",
    )

    def encode(value):
        return json.dumps(value, ensure_ascii=False)

    @server.tool(structured_output=False)
    def feed_manage(action: str, name: str = "", url: str = "", source: str = "",
                    note: str = "", poll_interval_seconds: int = 300) -> str:
        """管理 RSS/Atom 订阅：list、subscribe、unsubscribe、pause、resume。

        URL 必须是 HTTP/HTTPS RSS 或 Atom 地址。删除和暂停使用精确名称或 source_id。
        订阅后用 poll_feeds 采集，不会自动推送消息。
        """
        return encode(store.manage(action, name, url, source, note, poll_interval_seconds))

    @server.tool(structured_output=False)
    def feed_query(action: str = "latest", source: str = "", keyword: str = "",
                   limit: int = 10, page: int = 1, page_size: int = 20) -> str:
        """查询已缓存的订阅内容：latest、search、summary、sources、catalog。

        查询不触发网络采集。需要刷新时先调用 poll_feeds，并检查失败来源。
        返回标题、摘要、原文、发布时间及稳定 event_id。
        """
        return encode(store.query(action, source, keyword, limit, page, page_size))

    @server.tool(structured_output=False)
    async def poll_feeds(source: str = "", force: bool = False) -> str:
        """采集到期 RSS/Atom 来源，每次最多四个，按上次采集时间轮换。

        force=true 忽略采集间隔。返回 ok、failed、remaining 和每个来源的结果。
        remaining>0 时可继续调用；失败时保留旧缓存并记录原因。
        """
        return encode(await poller.poll(source, force))

    @server.tool(structured_output=False)
    def get_proactive_events(consumer: str = "kaze", limit: int = 20) -> str:
        """读取最近 36 小时内尚未被此 consumer 消费的候选内容。

        不采集、不发送消息、不自动 ACK。consumer 应使用目标会话的 session_key。
        """
        if not consumer.strip():
            raise ValueError("consumer must not be blank")
        return encode(store.events(consumer, limit))

    @server.tool(structured_output=False)
    def acknowledge_events(event_ids: list[str], consumer: str = "kaze",
                           reason: str = "processed", ttl_hours: float | None = None,
                           delivery_ref: str = "") -> str:
        """记录条目已处理、已读、已丢弃或已送达：processed、read、discarded、delivered。

        默认永久消费，ttl_hours 为正数时可在到期后重新出现。
        delivered 必须提供宿主真实送达回执 delivery_ref；本服务不验证回执真实性。
        准备推送或发送失败都不能标记为已送达。未知 ID 单独返回 missing。
        """
        return encode(store.acknowledge(event_ids, consumer, reason, ttl_hours, delivery_ref))

    @server.tool(structured_output=False)
    def feed_status(source: str = "") -> str:
        """查看来源的最近采集时间、成功时间、失败原因和缓存条数。"""
        return encode({"version": __version__, **store.status(source)})

    return server


def main():
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    create_server().run(transport="stdio")
