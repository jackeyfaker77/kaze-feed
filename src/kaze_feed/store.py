from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import sqlite3

from .config import Settings
from .parsing import Item, canonical_url, event_id, source_id, utc_text


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '',
                    poll_interval_seconds INTEGER NOT NULL,
                    last_polled_at TEXT, last_success_at TEXT, last_status TEXT,
                    last_error TEXT, etag TEXT, last_modified TEXT
                );
                CREATE TABLE IF NOT EXISTS items (
                    event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL
                        REFERENCES sources(id) ON DELETE CASCADE,
                    identity TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
                    url TEXT, author TEXT, published_at TEXT,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    UNIQUE(source_id, identity)
                );
                CREATE INDEX IF NOT EXISTS items_source ON items(source_id);
                CREATE INDEX IF NOT EXISTS items_published ON items(published_at);
                CREATE TABLE IF NOT EXISTS acknowledgements (
                    event_id TEXT NOT NULL REFERENCES items(event_id) ON DELETE CASCADE,
                    consumer TEXT NOT NULL, reason TEXT NOT NULL,
                    acknowledged_at TEXT NOT NULL, expires_at TEXT,
                    delivery_ref TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(event_id, consumer)
                );
                CREATE INDEX IF NOT EXISTS acknowledgements_expiry
                    ON acknowledgements(expires_at);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.settings.database, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def manage(self, action: str, name: str = "", url: str = "", source: str = "",
               note: str = "", poll_interval_seconds: int = 300) -> dict:
        action = {"add": "subscribe", "remove": "unsubscribe"}.get(action, action)
        if action == "list":
            return {"sources": self.sources(enabled_only=False)}
        with self.connection() as conn:
            if action == "subscribe":
                if not name.strip():
                    raise ValueError("A subscription name is required")
                address = canonical_url(url)
                identifier = source_id(address)
                existing = conn.execute("SELECT * FROM sources WHERE url=?", (address,)).fetchone()
                if existing:
                    return {"status": "already_subscribed", "source": dict(existing)}
                conn.execute(
                    "INSERT INTO sources(id,name,url,note,poll_interval_seconds) VALUES(?,?,?,?,?)",
                    (identifier, name.strip(), address, note.strip(), max(60, poll_interval_seconds)),
                )
                return {"status": "subscribed", "source_id": identifier, "url": address}
            if action not in {"unsubscribe", "pause", "resume"}:
                raise ValueError("action must be list, subscribe, unsubscribe, pause, or resume")
            target = source.strip() or name.strip()
            rows = conn.execute("SELECT * FROM sources WHERE id=? OR name=?", (target, target)).fetchall()
            if not rows:
                raise ValueError("Subscription not found; use feed_manage(action='list')")
            if len(rows) != 1:
                raise ValueError("Name is ambiguous; use its exact source_id")
            identifier = rows[0]["id"]
            if action == "unsubscribe":
                conn.execute("DELETE FROM sources WHERE id=?", (identifier,))
            else:
                conn.execute("UPDATE sources SET enabled=? WHERE id=?", (int(action == "resume"), identifier))
            return {"status": action, "source_id": identifier}

    def sources(self, source: str = "", *, enabled_only: bool = True) -> list[dict]:
        sql, args = "SELECT * FROM sources WHERE 1=1", []
        if enabled_only:
            sql += " AND enabled=1"
        if source:
            sql += " AND (id=? OR name=?)"
            args += [source, source]
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql + " ORDER BY name,id", args)]

    def save_poll(self, source: dict, items: list[Item], *, status: str,
                  error: str | None = None, etag: str | None = None,
                  last_modified: str | None = None, now: datetime | None = None) -> dict:
        stamp = utc_text(now)
        inserted = updated = 0
        with self.connection() as conn:
            # Unsubscribing during network I/O must not resurrect a subscription.
            if not conn.execute("SELECT 1 FROM sources WHERE id=?", (source["id"],)).fetchone():
                return {"source_id": source["id"], "status": "removed", "inserted": 0, "updated": 0}
            for item in items:
                identifier = event_id(source["id"], item.identity)
                exists = conn.execute("SELECT 1 FROM items WHERE event_id=?", (identifier,)).fetchone()
                inserted += int(exists is None)
                updated += int(exists is not None)
                conn.execute("""
                    INSERT INTO items(event_id,source_id,identity,title,content,url,author,
                                      published_at,first_seen_at,last_seen_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        title=excluded.title, content=excluded.content, url=excluded.url,
                        author=excluded.author, published_at=excluded.published_at,
                        last_seen_at=excluded.last_seen_at
                """, (identifier, source["id"], item.identity, item.title, item.content,
                      item.url, item.author, item.published_at, stamp, stamp))
            if status == "not_modified":
                conn.execute("UPDATE items SET last_seen_at=? WHERE source_id=?", (stamp, source["id"]))
            if error is None:
                conn.execute("""
                    UPDATE sources SET last_polled_at=?,last_success_at=?,last_status=?,
                        last_error=NULL,etag=?,last_modified=? WHERE id=?
                """, (stamp, stamp, status, etag, last_modified, source["id"]))
            else:
                conn.execute("""
                    UPDATE sources SET last_polled_at=?,last_status='failed',last_error=? WHERE id=?
                """, (stamp, error, source["id"]))
        return {"source_id": source["id"], "name": source["name"], "status": status,
                "inserted": inserted, "updated": updated, "error": error}

    def query(self, action: str = "latest", source: str = "", keyword: str = "",
              limit: int = 10, page: int = 1, page_size: int = 20) -> dict:
        if action in {"summary", "sources"}:
            return self.status(source=source)
        if action not in {"latest", "search", "catalog"}:
            raise ValueError("action must be latest, search, summary, sources, or catalog")
        if action == "search" and not keyword.strip():
            raise ValueError("search requires a keyword")
        sql = """SELECT i.*,s.name AS source_name,s.url AS source_url FROM items i
                 JOIN sources s ON s.id=i.source_id WHERE s.enabled=1"""
        args = []
        if source:
            sql += " AND (s.id=? OR s.name=?)"
            args += [source, source]
        if action == "search":
            sql += " AND (instr(lower(i.title),lower(?))>0 OR instr(lower(i.content),lower(?))>0)"
            args += [keyword, keyword]
        size = max(1, min(page_size if action == "catalog" else limit, 100))
        number = max(1, page) if action == "catalog" else 1
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM (" + sql + ")", args).fetchone()[0]
            rows = conn.execute(
                sql + " ORDER BY coalesce(i.published_at,i.first_seen_at) DESC,i.event_id LIMIT ? OFFSET ?",
                args + [size, (number - 1) * size],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": number,
                "has_more": number * size < total, "cached": True}

    def events(self, consumer: str = "kaze", limit: int = 20, *, now: datetime | None = None) -> list[dict]:
        instant = now or datetime.now(UTC)
        cutoff = utc_text(instant - timedelta(hours=self.settings.recent_hours))
        with self.connection() as conn:
            rows = conn.execute("""
                SELECT i.*,s.name AS source_name,s.url AS source_url FROM items i
                JOIN sources s ON s.id=i.source_id
                WHERE s.enabled=1 AND coalesce(i.published_at,i.first_seen_at)>=?
                  AND NOT EXISTS (
                      SELECT 1 FROM acknowledgements a WHERE a.event_id=i.event_id
                      AND a.consumer=? AND (a.expires_at IS NULL OR a.expires_at>?)
                  )
                ORDER BY coalesce(i.published_at,i.first_seen_at) DESC,i.event_id LIMIT ?
            """, (cutoff, consumer, utc_text(instant), max(1, min(limit, 100)))).fetchall()
        return [{"kind": "content", "source_type": "rss", **dict(row)} for row in rows]

    def acknowledge(self, event_ids: list[str], consumer: str = "kaze",
                    reason: str = "processed", ttl_hours: float | None = None,
                    delivery_ref: str = "", *, now: datetime | None = None) -> dict:
        if not consumer.strip():
            raise ValueError("consumer must not be blank")
        if reason not in {"processed", "read", "discarded", "delivered"}:
            raise ValueError("reason must be processed, read, discarded, or delivered")
        if reason == "delivered" and not delivery_ref.strip():
            raise ValueError("delivered requires a receipt reference from the host")
        if ttl_hours is not None and ttl_hours <= 0:
            raise ValueError("ttl_hours must be positive or null for a permanent acknowledgement")
        if len(event_ids) > 100:
            raise ValueError("At most 100 events can be acknowledged in one call")
        instant = now or datetime.now(UTC)
        expiry = utc_text(instant + timedelta(hours=ttl_hours)) if ttl_hours is not None else None
        acknowledged, missing = [], []
        with self.connection() as conn:
            for identifier in dict.fromkeys(event_ids):
                if not conn.execute("SELECT 1 FROM items WHERE event_id=?", (identifier,)).fetchone():
                    missing.append(identifier)
                    continue
                conn.execute("""
                    INSERT INTO acknowledgements(event_id,consumer,reason,acknowledged_at,expires_at,delivery_ref)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(event_id,consumer) DO UPDATE SET
                        reason=excluded.reason,acknowledged_at=excluded.acknowledged_at,
                        expires_at=excluded.expires_at,delivery_ref=excluded.delivery_ref
                """, (identifier, consumer, reason, utc_text(instant), expiry, delivery_ref))
                acknowledged.append(identifier)
        return {"acknowledged": acknowledged, "missing": missing, "consumer": consumer,
                "reason": reason, "expires_at": expiry, "delivery_verified_by_server": False}

    def status(self, source: str = "") -> dict:
        rows = self.sources(source=source, enabled_only=False)
        with self.connection() as conn:
            for row in rows:
                row["item_count"] = conn.execute(
                    "SELECT COUNT(*) FROM items WHERE source_id=?", (row["id"],)
                ).fetchone()[0]
        return {"sources": rows, "source_count": len(rows),
                "item_count": sum(row["item_count"] for row in rows)}

    def cleanup(self, *, now: datetime | None = None) -> None:
        instant = now or datetime.now(UTC)
        cutoff = utc_text(instant - timedelta(days=self.settings.retention_days))
        with self.connection() as conn:
            conn.execute("DELETE FROM acknowledgements WHERE expires_at IS NOT NULL AND expires_at<=?",
                         (utc_text(instant),))
            # Keep an identity while it is still present in a polled feed.
            conn.execute("DELETE FROM items WHERE last_seen_at<?", (cutoff,))
