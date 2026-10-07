from datetime import timedelta

import pytest

from kaze_feed.parsing import parse_feed, utc_text
from kaze_feed.store import Store
from conftest import rss


def seed(store, now, title="Example", timestamp="2026-10-08T12:00:00Z"):
    store.manage("subscribe", name="Example", url="https://example.test/rss")
    source = store.sources()[0]
    store.save_poll(source, parse_feed(rss(title, timestamp=timestamp), source["url"]), status="fetched", now=now)
    return store.query()["items"][0]["event_id"]


def test_subscriptions_are_idempotent_and_unsubscribe_uses_exact_names(store):
    store.manage("subscribe", name="Tech", url="https://example.test/rss")
    duplicate = store.manage("subscribe", name="Other", url="https://EXAMPLE.test:443/rss#x")
    store.manage("subscribe", name="Tech extra", url="https://example.test/other")
    assert duplicate["status"] == "already_subscribed"
    store.manage("unsubscribe", name="Tech")
    assert [row["name"] for row in store.sources()] == ["Tech extra"]


def test_ack_survives_restart_and_title_update_and_is_per_consumer(store, now):
    identifier = seed(store, now)
    store.acknowledge([identifier], consumer="desktop:a", now=now)
    seed(store, now + timedelta(minutes=5), title="Edited")
    reopened = Store(store.settings)
    assert reopened.query()["total"] == 1
    assert reopened.query()["items"][0]["title"] == "Edited"
    assert reopened.events("desktop:a", now=now) == []
    assert reopened.events("desktop:b", now=now)[0]["event_id"] == identifier


def test_ack_expiry_and_unknown_ids_are_explicit(store, now):
    identifier = seed(store, now)
    result = store.acknowledge([identifier, "missing"], ttl_hours=1, now=now)
    assert result["missing"] == ["missing"]
    assert store.events(now=now + timedelta(minutes=30)) == []
    assert len(store.events(now=now + timedelta(hours=2))) == 1


def test_delivered_requires_host_receipt_and_does_not_claim_verification(store, now):
    identifier = seed(store, now)
    with pytest.raises(ValueError, match="receipt"):
        store.acknowledge([identifier], reason="delivered")
    result = store.acknowledge([identifier], reason="delivered", delivery_ref="host-message-1")
    assert result["delivery_verified_by_server"] is False


def test_offset_timestamp_does_not_pass_the_recent_window(store, now):
    # 38 hours old in UTC, although its +08:00 date text would pass a raw comparison.
    seed(store, now, timestamp="2026-10-07T06:00:00+08:00")
    assert store.events(now=now) == []
    assert store.query()["items"][0]["published_at"] == utc_text(now - timedelta(hours=38))


def test_reading_candidates_does_not_acknowledge_them(store, now):
    seed(store, now)
    assert store.events(now=now) == store.events(now=now)
    assert len(store.events(now=now)) == 1


def test_pause_hides_events_and_resume_restores_them(store, now):
    seed(store, now)
    store.manage("pause", name="Example")
    assert store.events(now=now) == []
    store.manage("resume", name="Example")
    assert len(store.events(now=now)) == 1


def test_unsubscribe_removes_items_and_consumption_state(store, now):
    identifier = seed(store, now)
    store.acknowledge([identifier], now=now)
    store.manage("unsubscribe", name="Example")
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM acknowledgements").fetchone()[0] == 0
