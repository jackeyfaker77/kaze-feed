import asyncio
from datetime import UTC, datetime

import httpx

from .parsing import parse_feed
from .store import Store


class Poller:
    def __init__(self, store: Store):
        self.store = store
        self._lock = asyncio.Lock()

    async def poll(self, source: str = "", force: bool = False,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict:
        # Serialize overlapping batches, then recheck each source's interval.
        async with self._lock:
            settings = self.store.settings
            sources = self.store.sources(source)
            sources.sort(key=lambda row: (row.get("last_polled_at") or "", row["id"]))
            now = datetime.now(UTC)
            eligible = [
                row for row in sources
                if force or not row.get("last_polled_at")
                or (now - datetime.fromisoformat(row["last_polled_at"])).total_seconds()
                >= row["poll_interval_seconds"]
            ]
            selected = eligible[:settings.concurrency]
            semaphore = asyncio.Semaphore(settings.concurrency)
            async with httpx.AsyncClient(
                timeout=settings.timeout_seconds, follow_redirects=True,
                transport=transport, headers={
                    "User-Agent": "KazeFeed/0.1 (+RSS/Atom reader)",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                },
            ) as client:
                async def one(row):
                    async with semaphore:
                        return await self._source(client, row, force)
                results = await asyncio.gather(*(one(row) for row in selected))
            self.store.cleanup()
            failed = sum(result["status"] == "failed" for result in results)
            return {"ok": failed == 0, "total": len(results), "failed": failed,
                    "skipped": len(sources) - len(eligible),
                    "remaining": len(eligible) - len(selected),
                    "inserted": sum(result.get("inserted", 0) for result in results),
                    "sources": results}

    async def _source(self, client: httpx.AsyncClient, source: dict, force: bool) -> dict:
        last = source.get("last_polled_at")
        if not force and last and (
            datetime.now(UTC) - datetime.fromisoformat(last)
        ).total_seconds() < source["poll_interval_seconds"]:
            return {"source_id": source["id"], "name": source["name"], "status": "skipped"}
        headers = {}
        if source.get("etag"):
            headers["If-None-Match"] = source["etag"]
        if source.get("last_modified"):
            headers["If-Modified-Since"] = source["last_modified"]
        error = None
        for attempt in range(2):
            try:
                async with asyncio.timeout(self.store.settings.timeout_seconds), client.stream("GET", source["url"], headers=headers) as response:
                    if response.status_code == 304:
                        return self.store.save_poll(
                            source, [], status="not_modified",
                            etag=response.headers.get("etag", source.get("etag")),
                            last_modified=response.headers.get("last-modified", source.get("last_modified")),
                        )
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.store.settings.max_response_bytes:
                            raise ValueError("Feed exceeds the configured response size limit")
                    items = parse_feed(bytes(body), str(response.url), self.store.settings.max_items_per_feed)
                    return self.store.save_poll(
                        source, items, status="fetched", etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                    )
            except (httpx.HTTPError, ValueError, TimeoutError) as exc:
                error = type(exc).__name__ + ": " + str(exc)
                retryable = isinstance(exc, (httpx.TransportError, TimeoutError)) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and (exc.response.status_code == 429 or exc.response.status_code >= 500)
                )
                if not retryable or attempt == 1:
                    break
                await asyncio.sleep(0.2)
        return self.store.save_poll(source, [], status="failed", error=error)
