"""Offline integration test using Kaze's actual stdio MCP client."""

import argparse
import asyncio
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading


async def check(backend: Path):
    sys.path.insert(0, str(backend))
    from agent.mcp.client import McpClient
    from agent.mcp.manage_tools import McpAddTool
    from agent.mcp.registry import McpServerRegistry
    from agent.tools.registry import ToolRegistry
    root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now(UTC).isoformat()
    state = {"title": "Kaze 集成测试", "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            body = (
                '<rss version="2.0"><channel><title>Local fixture</title>'
                '<link>https://example.test/</link><description>Fixture</description><item>'
                '<guid isPermaLink="false">fixture-1</guid>'
                f'<title>{state["title"]}</title><description>仅本地测试</description>'
                f'<link>https://example.test/one</link><pubDate>{timestamp}</pubDate>'
                '</item></channel></rss>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="kaze-feed-integration-") as data:
            client = McpClient(
                name="feed", command=[sys.executable, str(root / "run_mcp.py")],
                env={"KAZE_FEED_DATA_DIR": data},
            )

            async def call(tool_name, **arguments):
                return json.loads(await client.call(tool_name, arguments))

            try:
                names = {tool.name for tool in await client.connect()}
                expected = {"feed_manage", "feed_query", "poll_feeds",
                            "get_proactive_events", "acknowledge_events", "feed_status"}
                assert names == expected, names
                await call("feed_manage", action="subscribe", name="Local fixture",
                           url=f"http://127.0.0.1:{http.server_port}/rss")
                assert (await call("poll_feeds"))["inserted"] == 1
                events = await call("get_proactive_events", consumer="desktop:check")
                assert len(events) == 1 and events[0]["title"] == state["title"]
                identifier = events[0]["event_id"]
                before = state["requests"]
                assert (await call("feed_query", action="latest"))["total"] == 1
                assert state["requests"] == before
                await call("acknowledge_events", event_ids=[identifier],
                           consumer="desktop:check", reason="delivered",
                           delivery_ref="local-fixture-receipt")
                assert await call("get_proactive_events", consumer="desktop:check") == []
                assert len(await call("get_proactive_events", consumer="desktop:other")) == 1
                state["title"] = "标题更新仍是同一条内容"
                assert (await call("poll_feeds", force=True))["inserted"] == 0
                assert (await call("feed_query"))["items"][0]["event_id"] == identifier
                await client.disconnect()
                assert len(await client.connect()) == 6
                assert await call("get_proactive_events", consumer="desktop:check") == []
                await client.disconnect()
                registry_tools = ToolRegistry()
                config_path = Path(data) / "mcp_servers.json"
                registry = McpServerRegistry(config_path, registry_tools)
                try:
                    add = McpAddTool(registry)
                    await add.execute(
                        name="feed", command=[sys.executable, str(root / "run_mcp.py")],
                        env={"KAZE_FEED_DATA_DIR": data},
                    )
                    status_tool = registry_tools.get_tool("mcp_feed__feed_status")
                    assert status_tool is not None
                    assert json.loads(await status_tool.execute())["source_count"] == 1
                    assert json.loads(config_path.read_text(encoding="utf-8"))["servers"]["feed"]
                    await registry.shutdown()
                    registry_tools = ToolRegistry()
                    registry = McpServerRegistry(config_path, registry_tools)
                    await registry.load_and_connect_all()
                    assert registry_tools.get_tool("mcp_feed__feed_query") is not None
                finally:
                    await registry.shutdown()
                print(json.dumps({"ok": True, "tools": sorted(names), "checks": [
                    "stdio_handshake", "tool_registration", "local_feed_poll",
                    "utf8", "cached_query", "consumer_isolation", "stable_identity",
                    "ack_persists_after_server_restart",
                    "kaze_mcp_add_and_persistent_registration",
                ]}, ensure_ascii=False, indent=2))
            finally:
                await client.disconnect()
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, type=Path)
    args = parser.parse_args()
    if not (args.backend / "agent" / "mcp" / "client.py").is_file():
        parser.error("--backend must point to Kaze's apps/backend directory")
    asyncio.run(check(args.backend.resolve()))


if __name__ == "__main__":
    main()
