from datetime import UTC, datetime

import pytest

from kaze_feed.config import Settings
from kaze_feed.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(Settings(data_dir=tmp_path))


@pytest.fixture
def now():
    return datetime(2026, 10, 8, 12, tzinfo=UTC)


def rss(title="Example", *, timestamp="2026-10-08T12:00:00Z"):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Test</title>'
        '<link>https://example.test/</link><description>Test</description><item>'
        '<guid isPermaLink="false">article-1</guid>'
        f'<title>{title}</title><link>https://example.test/article/1</link>'
        '<content:encoded><![CDATA[<p>Body &amp; details</p>]]></content:encoded>'
        f'<dc:creator>Alice</dc:creator><pubDate>{timestamp}</pubDate>'
        '</item></channel></rss>'
    ).encode()
