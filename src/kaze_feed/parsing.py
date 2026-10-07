from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser


def utc_text(value: datetime | None = None) -> str:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).isoformat(timespec="microseconds")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str, *, limit: int = 4000) -> str:
    parser = _Text()
    parser.feed(value or "")
    return " ".join(unescape("".join(parser.parts)).split())[:limit]


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute HTTP or HTTPS address")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not supported")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = "[" + host + "]"
    port = parsed.port
    scheme = parsed.scheme.lower()
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host += ":" + str(port)
    return urlunsplit((scheme, host, parsed.path or "/", parsed.query, ""))


def source_id(url: str) -> str:
    return "src_" + sha256(canonical_url(url).encode()).hexdigest()[:24]


def event_id(source: str, identity: str) -> str:
    return "feed_" + sha256((source + "\n" + identity).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Item:
    identity: str
    title: str
    content: str
    url: str | None
    author: str | None
    published_at: str | None


def parse_feed(body: bytes, base_url: str, limit: int = 200) -> list[Item]:
    parsed = feedparser.parse(body)
    if not parsed.get("version"):
        raise ValueError("Response is not a recognized RSS or Atom feed")
    if parsed.get("bozo") and not parsed.entries:
        raise ValueError("Feed could not be parsed")
    items = []
    for entry in parsed.entries[:limit]:
        title = plain_text(entry.get("title", ""), limit=500)
        contents = entry.get("content") or []
        content = plain_text(
            str(contents[0].get("value", "")) if contents else str(entry.get("summary", ""))
        )
        if not title and not content:
            continue
        raw_link = str(entry.get("link", "")).strip()
        try:
            link = canonical_url(urljoin(base_url, raw_link)) if raw_link else None
        except ValueError:
            link = None
        upstream = str(entry.get("id") or "").strip()
        # Titles and dates may change without changing the identity of an article.
        identity = "id:" + upstream if upstream else "url:" + link if link else (
            "text:" + sha256((title + "\n" + content).encode()).hexdigest()
        )
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = utc_text(datetime(*stamp[:6], tzinfo=UTC)) if stamp else None
        items.append(Item(
            identity=identity, title=title or content[:100], content=content,
            url=link, author=plain_text(str(entry.get("author", "")), limit=300) or None,
            published_at=published,
        ))
    return items
