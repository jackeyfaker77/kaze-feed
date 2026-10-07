import asyncio
from dataclasses import replace
from datetime import timedelta

import httpx

from kaze_feed.poller import Poller
from kaze_feed.parsing import parse_feed
from kaze_feed.store import Store
from conftest import rss


async def test_source_failure_is_reported_and_other_sources_are_saved(store):
    store.manage("subscribe", name="Good", url="https://good.test/rss")
    store.manage("subscribe", name="Bad", url="https://bad.test/rss")
    def handle(request):
        return httpx.Response(401) if request.url.host == "bad.test" else httpx.Response(200, content=rss())
    result = await Poller(store).poll(transport=httpx.MockTransport(handle))
    assert result["ok"] is False
    assert result["failed"] == 1
    assert result["inserted"] == 1
    failed = [row for row in store.status()["sources"] if row["name"] == "Bad"][0]
    assert failed["last_status"] == "failed"
    assert "401" in failed["last_error"]


async def test_query_is_cached_and_polling_respects_interval(store):
    store.manage("subscribe", name="Feed", url="https://example.test/rss")
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=rss())
    poller = Poller(store)
    transport = httpx.MockTransport(handle)
    await poller.poll(transport=transport)
    store.query()
    store.query("catalog")
    result = await poller.poll(transport=transport)
    assert len(requests) == 1
    assert result["skipped"] == 1
    assert result["total"] == 0


async def test_conditional_fetch_preserves_identity_and_ack(store):
    store.manage("subscribe", name="Feed", url="https://example.test/rss")
    def handle(request):
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=rss(), headers={"etag": '"v1"'})
    poller = Poller(store)
    transport = httpx.MockTransport(handle)
    await poller.poll(transport=transport)
    identifier = store.query()["items"][0]["event_id"]
    store.acknowledge([identifier])
    result = await poller.poll(force=True, transport=transport)
    assert result["sources"][0]["status"] == "not_modified"
    assert store.query()["items"][0]["event_id"] == identifier
    assert store.events() == []


async def test_overlapping_batches_do_not_fetch_the_same_source_twice(store):
    store.manage("subscribe", name="Feed", url="https://example.test/rss")
    calls = []
    async def handle(request):
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=rss())
    poller = Poller(store)
    transport = httpx.MockTransport(handle)
    await asyncio.gather(poller.poll(transport=transport), poller.poll(transport=transport))
    assert len(calls) == 1


async def test_oversized_response_is_recorded_as_a_failure(store):
    small = Store(replace(store.settings, max_response_bytes=10))
    small.manage("subscribe", name="Feed", url="https://example.test/rss")
    result = await Poller(small).poll(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=rss())
    ))
    assert result["ok"] is False
    assert small.query()["total"] == 0


async def test_invalid_feed_is_a_failure_even_with_http_200(store):
    store.manage("subscribe", name="Feed", url="https://example.test/rss")
    result = await Poller(store).poll(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"<html>Not a feed</html>")
    ))
    assert result["failed"] == 1


def test_304_refreshes_liveness_without_erasing_ack_or_content(store, now):
    store.manage("subscribe", name="Feed", url="https://example.test/rss")
    source = store.sources()[0]
    store.save_poll(source, parse_feed(
        rss(), source["url"]), status="fetched", now=now)
    identifier = store.query()["items"][0]["event_id"]
    store.acknowledge([identifier], now=now)
    future = now + timedelta(days=31)
    store.save_poll(source, [], status="not_modified", now=future)
    store.cleanup(now=future)
    assert store.query()["total"] == 1
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM acknowledgements").fetchone()[0] == 1


async def test_poll_batches_are_bounded_and_rotate_to_remaining_sources(store):
    for number in range(6):
        store.manage("subscribe", name=str(number), url=f"https://example.test/{number}")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=rss()))
    poller = Poller(store)
    first = await poller.poll(transport=transport)
    second = await poller.poll(transport=transport)
    assert first["total"] == 4 and first["remaining"] == 2
    assert second["total"] == 2 and second["remaining"] == 0
    assert store.query()["total"] == 6
