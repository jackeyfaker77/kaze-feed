from datetime import UTC, datetime

import pytest

from kaze_feed.parsing import canonical_url, parse_feed, plain_text, utc_text
from conftest import rss


def test_namespaced_body_author_and_identity_survive_an_edited_title():
    first = parse_feed(rss(), "https://example.test/rss")[0]
    edited = parse_feed(rss("Edited"), "https://example.test/rss")[0]
    assert first.content == "Body & details"
    assert first.author == "Alice"
    assert first.identity == edited.identity == "id:article-1"


def test_atom_identity_relative_link_and_html():
    body = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title>
    <entry><id>tag:example.test,2026:1</id><title>Article</title>
    <link href="/one"/><content type="html">&lt;p&gt;Body&lt;/p&gt;</content>
    <updated>2026-10-08T20:00:00+08:00</updated></entry></feed>"""
    row = parse_feed(body, "https://example.test/feed")[0]
    assert row.identity == "id:tag:example.test,2026:1"
    assert row.url == "https://example.test/one"
    assert row.content == "Body"
    assert row.published_at == utc_text(datetime(2026, 10, 8, 12, tzinfo=UTC))


def test_url_is_the_identity_when_guid_is_missing():
    xml = rss().replace(b'<guid isPermaLink="false">article-1</guid>', b"")
    assert parse_feed(xml, "https://example.test/")[0].identity == "url:https://example.test/article/1"


@pytest.mark.parametrize("address", ["file:///C:/secret", "ftp://example.test/a", "relative/rss", "https://user:pass@example.test/rss"])
def test_subscription_rejects_non_http_and_embedded_credentials(address):
    with pytest.raises(ValueError):
        canonical_url(address)


def test_host_port_and_fragment_normalization():
    assert canonical_url("HTTPS://Example.test:443/feed#top") == "https://example.test/feed"


def test_html_is_not_accepted_as_a_feed():
    with pytest.raises(ValueError):
        parse_feed(b"<html><body>Service unavailable</body></html>", "https://example.test/")


def test_html_conversion_keeps_characters_and_omits_scripts():
    assert plain_text("<p>A &amp; B</p><script>secret</script><p>&#20013;&#25991;</p>") == "A & B 中文"
